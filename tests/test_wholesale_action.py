"""Exercise real, private wholesale applications through Layer 2."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select

from models.shop_action import ShopActionAuthorization, ShopActionExecution
from models.shop_multibot import LEGACY_BOT_IDS
from models.shop_wholesale import ShopWholesaleApplication
from models.shop_workflow_runtime import WorkflowUpload
from services.shop_actions.approvals import issue_authorization
from services.shop_actions.catalog import actions
from services.shop_actions.contracts import ActionRejected, Invocation, redact
from services.shop_actions.execution import invoke
from services.shop_actions.simulation import simulate_action
from tests.test_action_security import buyer as buyer, db as db


def application_input(**changes):
    """Describe an independently checked, complete wholesale form in rials."""
    return {
        "name": "مریم آزمایشی",
        "phone": "+989121234567",
        "company": "فروشگاه خصوصی نمونه",
        "city": "تهران",
        "estimated_monthly_amount": 500_000_000,
        **changes,
    }


def request(data=None, **changes):
    """Give each new form a distinct stable Layer 2 operation identity."""
    return Invocation(
        **{
            "invocation_id": str(uuid4()),
            "action_key": "wholesale.create_application",
            "idempotency_key": str(uuid4()),
            "input": application_input() if data is None else data,
            **changes,
        }
    )


async def confirm(db, principal, operation):
    """Issue the existing opaque proof for this exact customer operation."""
    token = await issue_authorization(
        db,
        subject=principal,
        approver=principal,
        invocation=operation,
        purpose="customer_confirmation",
        registry=actions(),
    )
    return operation.model_copy(update={"confirmation_receipt": token})


async def upload(db, principal, **changes):
    """Persist verified evidence without downloading or sending files."""
    record = WorkflowUpload(
        id=str(uuid4()),
        store_id=principal.store_id,
        bot_id=principal.bot_id,
        customer_id=principal.customer_id,
        user_id=principal.platform_user_id,
        kind="document",
        file_id="private-provider-file-id-never-in-public-results",
        size=100,
        mime_type="application/pdf",
        sha256="a" * 64,
        verified=True,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    for name, value in changes.items():
        setattr(record, name, value)
    db.add(record)
    await db.commit()
    return record


def test_wholesale_registry_advertises_the_real_executor_and_private_inputs():
    """A real domain adapter must replace the previous unavailable metadata."""
    spec = actions().resolve("wholesale.create_application", "1.0.0")
    assert spec.descriptor.service_available
    assert spec.adapter is not None and spec.preflight is not None
    assert spec.descriptor.confirmation == "customer_confirmation"
    payload = application_input(document_handle=str(uuid4()))
    assert redact(payload, spec.descriptor.sensitive_inputs) == {
        "name": "[redacted]",
        "phone": "[redacted]",
        "company": "[redacted]",
        "city": "[redacted]",
        "estimated_monthly_amount": "[redacted]",
        "document_handle": "[redacted]",
    }


def test_company_only_v1_input_remains_valid_with_explicit_empty_defaults():
    """An existing pinned company-only form keeps its typed v1 input shape."""
    spec = actions().resolve("wholesale.create_application", "1.0.0")
    assert spec.input({"company": "Legacy business"}).model_dump() == {
        "company": "Legacy business",
        "name": "",
        "phone": "",
        "city": "",
        "estimated_monthly_amount": 0,
        "document_handle": None,
    }


@pytest.mark.asyncio
async def test_confirmed_application_is_durable_idempotent_and_private(
    buyer,
    caplog,
):
    """Require confirmation and never duplicate forms or leak their PII."""
    db, principal = buyer
    caplog.set_level("INFO", logger="shop.actions")
    evidence = await upload(db, principal)
    data = application_input(document_handle=evidence.id)
    operation = request(data)
    pending = await invoke(db, principal, operation)
    assert pending.status == "pending_approval", pending.model_dump()
    table = ShopWholesaleApplication.__table__
    assert await db.scalar(select(func.count()).select_from(table)) == 0
    approved = await confirm(db, principal, operation)
    created = await invoke(db, principal, approved)
    replayed = await invoke(db, principal, approved)
    assert created.status == replayed.status == "succeeded", (
        created.model_dump()
    )
    assert created.output == replayed.output
    assert set(created.output) == {"request_id", "status"}
    assert created.output["status"] == "submitted"
    assert await db.scalar(select(func.count()).select_from(table)) == 1
    row = (await db.execute(select(table))).mappings().one()
    assert row["id"] == created.output["request_id"]
    assert row["store_id"] == principal.store_id
    assert row["bot_id"] == principal.bot_id
    assert row["customer_id"] == principal.customer_id
    assert row["origin_identity_id"] == principal.identity_id
    assert row["platform"] == principal.platform
    assert row["platform_user_id"] == principal.platform_user_id
    for name, value in data.items():
        assert row[name] == value
    receipt = await db.get(ShopActionExecution, operation.invocation_id)
    proof = await db.scalar(select(ShopActionAuthorization))
    assert proof.consumed_invocation_id == operation.invocation_id
    public = " ".join(
        (
            created.model_dump_json(),
            receipt.result_json,
            caplog.text,
            str([record.__dict__ for record in caplog.records]),
        )
    )
    for value in (
        *data.values(),
        evidence.file_id,
        approved.confirmation_receipt,
    ):
        assert str(value) not in public


@pytest.mark.asyncio
async def test_wholesale_dry_run_never_mutates_any_rows(buyer):
    """Validate live preview ownership without any SQL mutation."""
    db, principal = buyer
    evidence = await upload(db, principal)
    mutations = []

    def track_mutations(_conn, _cursor, statement, *_args):
        """Observe actual SQL rather than relying only on final row counts."""
        if statement.lstrip().split(None, 1)[0].upper() in {
            "INSERT",
            "UPDATE",
            "DELETE",
        }:
            mutations.append(statement)

    engine = db.session.get_bind()
    event.listen(engine, "before_cursor_execute", track_mutations)
    try:
        result = await invoke(
            db,
            principal,
            request(
                application_input(document_handle=evidence.id), mode="dry_run"
            ),
        )
    finally:
        event.remove(engine, "before_cursor_execute", track_mutations)
    assert result.status == "skipped" and result.dry_run, result.model_dump()
    assert result.output is None and not result.exact_preview
    assert result.error.code == "action_exact_preview_unavailable"
    assert mutations == []
    assert (
        await db.scalar(select(func.count()).select_from(ShopActionExecution))
        == 0
    )
    table = ShopWholesaleApplication.__table__
    assert await db.scalar(select(func.count()).select_from(table)) == 0
    assert (
        await db.scalar(select(func.count()).select_from(WorkflowUpload)) == 1
    )


@pytest.mark.asyncio
async def test_wholesale_requires_the_existing_customer_scope(buyer):
    """Deny missing scopes before claiming any application receipt."""
    db, principal = buyer
    limited = replace(principal, scopes=principal.scopes - {"support.write"})
    result = await invoke(db, limited, request())
    assert (
        result.status == "failed" and result.error.code == "action_forbidden"
    )
    assert (
        await db.scalar(select(func.count()).select_from(ShopActionExecution))
        == 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("claim", ["store_id", "bot_id", "customer_id"])
async def test_wholesale_rejects_changed_ownership_claims(buyer, claim):
    """Prevent a valid form from borrowing another owner's scope."""
    db, principal = buyer
    value = (
        principal.customer_id + 1 if claim == "customer_id" else str(uuid4())
    )
    changed = replace(principal, **{claim: value})
    result = await invoke(db, changed, request())
    assert (
        result.status == "failed"
        and result.error.code == "action_identity_changed"
    )
    assert (
        await db.scalar(select(func.count()).select_from(ShopActionExecution))
        == 0
    )


@pytest.mark.asyncio
async def test_changed_form_cannot_reuse_the_customer_confirmation(buyer):
    """Bind every private field, including the estimate, to confirmation."""
    db, principal = buyer
    original = request()
    approved = await confirm(db, principal, original)
    changed = approved.model_copy(
        update={
            "input": application_input(estimated_monthly_amount=600_000_000)
        }
    )
    result = await invoke(db, principal, changed)
    assert (
        result.status == "failed"
        and result.error.code == "action_approval_invalid"
    )
    proof = await db.scalar(select(ShopActionAuthorization))
    assert proof.consumed_invocation_id is None
    table = ShopWholesaleApplication.__table__
    assert await db.scalar(select(func.count()).select_from(table)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"bot_id": LEGACY_BOT_IDS["bale"]},
        {"store_id": "00000000-0000-4000-8000-000000000888"},
        {"customer_id": 999},
        {"user_id": 999},
        {"verified": False},
        {"expires_at": datetime(2020, 1, 1, tzinfo=UTC)},
    ],
)
async def test_private_document_requires_exact_verified_live_ownership(
    buyer, changes
):
    """Foreign, unverified or expired evidence never becomes an application."""
    db, principal = buyer
    evidence = await upload(db, principal, **changes)
    operation = await confirm(
        db, principal, request(application_input(document_handle=evidence.id))
    )
    result = await invoke(db, principal, operation)
    assert result.status == "failed", result.model_dump()
    assert result.error.code == "action_wholesale_document_unavailable"
    assert evidence.file_id not in result.model_dump_json()
    table = ShopWholesaleApplication.__table__
    assert await db.scalar(select(func.count()).select_from(table)) == 0


@pytest.mark.asyncio
async def test_missing_private_document_is_rejected_during_preview(buyer):
    """A guessed UUID is not evidence even in no-effect preview mode."""
    db, principal = buyer
    result = await invoke(
        db,
        principal,
        request(
            application_input(document_handle=str(uuid4())), mode="dry_run"
        ),
    )
    assert result.status == "failed", result.model_dump()
    assert result.error.code == "action_wholesale_document_unavailable"
    assert (
        await db.scalar(select(func.count()).select_from(ShopActionExecution))
        == 0
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "x" * 161},
        {"name": "private\x00name"},
        {"phone": "x" * 33},
        {"phone": "https://example.com"},
        {"company": " "},
        {"company": "x" * 201},
        {"city": "x" * 121},
        {"estimated_monthly_amount": -1},
        {"estimated_monthly_amount": 9_007_199_254_740_992},
        {"estimated_monthly_amount": "1000"},
        {"document_handle": "https://example.com/private.pdf"},
        {"document_handle": "../private.pdf"},
        {"document_handle": "private-provider-file-id"},
    ],
)
def test_private_wholesale_fields_are_bounded_and_typed(changes):
    """Reject control text, arbitrary file locators and coerced amounts."""
    spec = actions().resolve("wholesale.create_application", "1.0.0")
    with pytest.raises(ActionRejected, match="action_invalid_input"):
        spec.input(application_input(**changes))


@pytest.mark.parametrize("platform", ["telegram", "bale"])
def test_wholesale_simulator_is_deterministic_labelled_and_private(
    platform,
):
    """Return an explicit simulated label without echoing private data."""
    payload = application_input(document_handle=str(uuid4()))
    first = simulate_action(
        "wholesale.create_application",
        "1.0.0",
        payload,
        platform=platform,
    )
    second = simulate_action(
        "wholesale.create_application",
        "1.0.0",
        payload,
        platform=platform,
    )
    assert first == second == {"request_id": 90001, "status": "simulated"}
    for value in payload.values():
        assert str(value) not in str(first)
