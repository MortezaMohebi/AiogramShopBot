"""Exercise atomic local effects, receipts, pending proofs and safe no-effect modes."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import Field
from sqlalchemy import func, select

from models.shop_action import ShopActionAuthorization, ShopActionExecution
from models.shop_content import Product
from services.shop_actions.approvals import issue_authorization
from services.shop_actions.contracts import ActionDescriptor, Invocation, StrictModel
from services.shop_actions.execution import invoke
from services.shop_actions.registry import ActionSpec, Registry
from tests.test_action_security import buyer, db
from tests.test_shared_cart import seed


class Change(StrictModel):
    """A deterministic local write used to prove unit-of-work behavior."""

    product_id: int = Field(ge=1)
    amount: int = Field(ge=1, le=99)
    note: str = Field(default="", max_length=100)


class Changed(StrictModel):
    """Only safe stock metadata may enter the execution receipt."""

    stock: int = Field(ge=0)


async def change(db, _principal, data):
    """Use a real SQL row; the invocation boundary owns its transaction."""
    product = await db.get(Product, data.product_id)
    product.stock_quantity += data.amount
    await db.flush()
    return {"stock": product.stock_quantity}


async def broken_output(db, principal, data):
    """A malformed adapter must not commit an otherwise valid business effect."""
    await change(db, principal, data)
    return {"stock": -1, "token": "do-not-leak"}


def registry(*, confirmation="none", adapter=change, available=True):
    """Register a small explicit mutation without replacing execution policy."""
    result = Registry()
    descriptor = ActionDescriptor(
        key="cart.test_write",
        version="1.0.0",
        name="Write",
        description="QA write",
        category="cart",
        input_schema=Change.model_json_schema(),
        output_schema=Changed.model_json_schema(),
        allowed_actors=["customer"],
        required_scopes=["cart.write"],
        side_effect="business_mutation",
        transaction="atomic_local",
        idempotency="required",
        confirmation=confirmation,
        sensitive_inputs=["note"],
        service_available=available,
    )
    result.register(
        ActionSpec(
            descriptor,
            Change,
            Changed,
            adapter if available else None,
            simulate=lambda data, platform: {"stock": data["amount"]},
        )
    )
    return result


def invocation(product_id, **changes):
    """Bind retries to a fixed operation, key and exact typed business input."""
    return Invocation(
        **(
            {
                "invocation_id": str(uuid4()),
                "action_key": "cart.test_write",
                "input": {
                    "product_id": product_id,
                    "amount": 2,
                    "note": "private-support-note",
                },
                "idempotency_key": "operation-" + str(uuid4()),
                "correlation_id": "qa-1",
            }
            | changes
        )
    )


@pytest.mark.asyncio
async def test_duplicate_live_call_replays_one_effect_and_one_receipt(buyer):
    db, principal = buyer
    product, _ = seed(db)
    request = invocation(product.id)
    first = await invoke(db, principal, request, registry=registry())
    second = await invoke(db, principal, request, registry=registry())
    assert first.status == second.status == "succeeded"
    assert first.output == second.output == {"stock": 7}
    assert first.execution_receipt == second.execution_receipt == request.invocation_id
    assert (await db.get(Product, product.id)).stock_quantity == 7
    assert await db.scalar(select(func.count()).select_from(ShopActionExecution)) == 1


@pytest.mark.asyncio
async def test_changed_input_same_key_is_conflict_without_a_second_write(buyer):
    db, principal = buyer
    product, _ = seed(db)
    request = invocation(product.id)
    assert (
        await invoke(db, principal, request, registry=registry())
    ).status == "succeeded"
    changed = request.model_copy(
        update={"input": {"product_id": product.id, "amount": 4}}
    )
    result = await invoke(db, principal, changed, registry=registry())
    assert (
        result.status == "failed" and result.error.code == "action_idempotency_conflict"
    )
    assert (await db.get(Product, product.id)).stock_quantity == 7


@pytest.mark.asyncio
async def test_required_key_and_scope_fail_before_mutation(buyer):
    db, principal = buyer
    product, _ = seed(db)
    for owner, request, code in (
        (
            principal,
            invocation(product.id, idempotency_key=None),
            "action_idempotency_required",
        ),
        (
            replace(principal, scopes=frozenset()),
            invocation(product.id),
            "action_forbidden",
        ),
    ):
        result = await invoke(db, owner, request, registry=registry())
        assert result.status == "failed" and result.error.code == code
    assert (await db.get(Product, product.id)).stock_quantity == 5


@pytest.mark.asyncio
async def test_bad_output_rolls_back_business_write(buyer):
    db, principal = buyer
    product, _ = seed(db)
    product_id = product.id
    result = await invoke(
        db, principal, invocation(product_id), registry=registry(adapter=broken_output)
    )
    assert result.status == "failed" and result.error.code == "action_invalid_output"
    db.session.expire_all()
    assert (await db.get(Product, product_id)).stock_quantity == 5
    assert "do-not-leak" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_dry_run_and_simulation_have_no_business_or_receipt_writes(buyer):
    db, principal = buyer
    product, _ = seed(db)
    dry = await invoke(
        db, principal, invocation(product.id, mode="dry_run"), registry=registry()
    )
    simulated = await invoke(
        db, principal, invocation(product.id, mode="simulation"), registry=registry()
    )
    assert dry.dry_run and not dry.exact_preview and dry.status == "skipped"
    assert simulated.simulated and simulated.output == {"stock": 2}
    assert (await db.get(Product, product.id)).stock_quantity == 5
    assert await db.scalar(select(func.count()).select_from(ShopActionExecution)) == 0
    assert (
        await db.scalar(select(func.count()).select_from(ShopActionAuthorization)) == 0
    )


@pytest.mark.asyncio
async def test_pending_operation_resumes_with_bound_single_use_confirmation(buyer):
    db, principal = buyer
    product, _ = seed(db)
    request = invocation(product.id)
    actions = registry(confirmation="customer_confirmation")
    pending = await invoke(db, principal, request, registry=actions)
    assert pending.status == "pending_approval"
    token = await issue_authorization(
        db,
        subject=principal,
        approver=principal,
        invocation=request,
        purpose="customer_confirmation",
        registry=actions,
    )
    approved = request.model_copy(update={"confirmation_receipt": token})
    result = await invoke(db, principal, approved, registry=actions)
    again = await invoke(db, principal, approved, registry=actions)
    assert result.status == again.status == "succeeded"
    assert result.output == again.output == {"stock": 7}
    proof = await db.scalar(select(ShopActionAuthorization))
    assert proof.consumed_invocation_id == request.invocation_id
    assert proof.token_sha256 != token and len(proof.token_sha256) == 64
    assert await db.scalar(select(func.count()).select_from(ShopActionExecution)) == 1


@pytest.mark.asyncio
async def test_confirmation_cannot_move_to_changed_input_or_operation(buyer):
    db, principal = buyer
    product, _ = seed(db)
    request = invocation(product.id)
    actions = registry(confirmation="customer_confirmation")
    token = await issue_authorization(
        db,
        subject=principal,
        approver=principal,
        invocation=request,
        purpose="customer_confirmation",
        registry=actions,
    )
    changed = invocation(product.id, confirmation_receipt=token)
    result = await invoke(db, principal, changed, registry=actions)
    assert result.status == "failed" and result.error.code == "action_approval_invalid"
    assert (await db.get(Product, product.id)).stock_quantity == 5


@pytest.mark.asyncio
async def test_expired_confirmation_fails_without_consumption(buyer):
    db, principal = buyer
    product, _ = seed(db)
    request = invocation(product.id)
    actions = registry(confirmation="customer_confirmation")
    token = await issue_authorization(
        db,
        subject=principal,
        approver=principal,
        invocation=request,
        purpose="customer_confirmation",
        registry=actions,
    )
    proof = await db.scalar(select(ShopActionAuthorization))
    proof.issued_at = datetime.now(UTC) - timedelta(seconds=10)
    proof.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    result = await invoke(
        db,
        principal,
        request.model_copy(update={"confirmation_receipt": token}),
        registry=actions,
    )
    assert result.status == "failed" and result.error.code == "action_approval_expired"
    assert proof.consumed_invocation_id is None
    assert (await db.get(Product, product.id)).stock_quantity == 5


@pytest.mark.asyncio
async def test_sensitive_inputs_do_not_enter_receipts_or_logs(buyer, caplog):
    caplog.set_level("INFO", logger="shop.actions")
    db, principal = buyer
    product, _ = seed(db)
    request = invocation(product.id)
    result = await invoke(db, principal, request, registry=registry())
    receipt = await db.get(ShopActionExecution, request.invocation_id)
    assert result.status == "succeeded"
    assert "private-support-note" not in receipt.result_json
    assert "private-support-note" not in caplog.text
    assert request.idempotency_key not in caplog.text
    records = [item for item in caplog.records if item.name == "shop.actions"]
    assert len(records) == 1 and records[0].status == "succeeded"
    assert "private-support-note" not in str(records[0].__dict__)
    from services.shop_actions.observability import snapshot

    metrics = snapshot()
    assert any(key[0] == "invocations" for key in metrics)
    assert "private-support-note" not in str(metrics)


@pytest.mark.asyncio
async def test_missing_adapter_is_unavailable_without_production_success(buyer):
    db, principal = buyer
    product, _ = seed(db)
    result = await invoke(
        db, principal, invocation(product.id), registry=registry(available=False)
    )
    assert result.status == "unavailable" and result.output is None
    assert (await db.get(Product, product.id)).stock_quantity == 5


@pytest.mark.asyncio
async def test_confirmation_is_not_issued_for_an_action_without_that_policy(buyer):
    """Proof issuance cannot be used as a generic capability minting endpoint."""
    from services.shop_actions.contracts import ActionRejected

    db, principal = buyer
    product, _ = seed(db)
    with pytest.raises(ActionRejected, match="action_approval_forbidden"):
        await issue_authorization(
            db,
            subject=principal,
            approver=principal,
            invocation=invocation(product.id),
            purpose="customer_confirmation",
            registry=registry(),
        )


@pytest.mark.asyncio
async def test_unavailable_action_cannot_receive_a_confirmation(buyer):
    """A nonexistent executor cannot be approved speculatively for later activation."""
    from services.shop_actions.contracts import ActionRejected

    db, principal = buyer
    product, _ = seed(db)
    with pytest.raises(ActionRejected, match="action_service_unavailable"):
        await issue_authorization(
            db,
            subject=principal,
            approver=principal,
            invocation=invocation(product.id),
            purpose="customer_confirmation",
            registry=registry(confirmation="customer_confirmation", available=False),
        )
