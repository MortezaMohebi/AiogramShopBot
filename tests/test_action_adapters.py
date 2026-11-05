"""Typed Actions exercise the existing commerce services and their ownership rules."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from models.shop_action import ShopActionExecution
from models.shop_bot_catalog_acl import ShopBotProductRule
from models.shop_checkout import ShopCart, ShopCartItem
from models.shop_content import Product, ShopOrder
from models.shop_customer_support import ShopSupportMessage, ShopSupportTicket
from services.shop_actions.approvals import issue_authorization
from services.shop_actions.catalog import actions
from services.shop_actions.contracts import Invocation
from services.shop_actions.execution import invoke
from tests.test_action_security import buyer, db
from tests.test_shared_cart import seed


def request(key, data=None, **overrides):
    """Give every new business operation its own exact idempotent identity."""
    return Invocation(
        **(
            {
                "invocation_id": str(uuid4()),
                "action_key": key,
                "input": data or {},
                "idempotency_key": str(uuid4()),
            }
            | overrides
        )
    )


@pytest.mark.asyncio
async def test_catalog_search_visibility_price_and_uom(buyer):
    """Public data follows the same Bot ACL and native currency/unit rules."""
    db, principal = buyer
    first, second = seed(db)
    db.add(
        ShopBotProductRule(bot_id=principal.bot_id, product_id=second.id, effect="deny")
    )
    await db.commit()
    found = await invoke(
        db, principal, request("catalog.search_products", {"query": "محصول"})
    )
    assert found.status == "succeeded", found.model_dump()
    assert [item["id"] for item in found.output["items"]] == [first.id]
    detail = await invoke(
        db, principal, request("catalog.get_product", {"product_id": first.id})
    )
    assert detail.output["price_irr"] == 1000
    assert detail.output["uom"]["ratio_num"] == detail.output["uom"]["ratio_den"] == 1
    denied = await invoke(
        db, principal, request("catalog.get_product", {"product_id": second.id})
    )
    assert (
        denied.status == "failed" and denied.error.code == "action_product_unavailable"
    )
    visible = await invoke(
        db,
        principal,
        request("catalog.validate_product_visibility", {"product_id": second.id}),
    )
    assert visible.output == {"visible": False}


@pytest.mark.asyncio
async def test_cart_add_update_read_remove_reuse_live_quote(buyer):
    """Absolute quantities and current prices round-trip through real cart rows."""
    db, principal = buyer
    product, _ = seed(db)
    added = await invoke(
        db,
        principal,
        request("cart.add_item", {"product_id": product.id, "quantity": 2}),
    )
    assert added.status == "succeeded", added.model_dump()
    assert added.output["items"][0]["quantity"] == 2
    revision = added.output["revision"]
    updated = await invoke(
        db,
        principal,
        request(
            "cart.update_quantity",
            {
                "product_id": product.id,
                "quantity": 3,
                "expected_cart_revision": revision,
            },
        ),
    )
    assert updated.output["subtotal_irr"] == 3000
    read = await invoke(db, principal, request("cart.get"))
    assert read.output["items"][0]["quantity"] == 3
    removed = await invoke(
        db,
        principal,
        request(
            "cart.remove_item",
            {
                "product_id": product.id,
                "expected_cart_revision": read.output["revision"],
            },
        ),
    )
    assert removed.status == "succeeded" and removed.output["items"] == []
    assert await db.scalar(select(func.count()).select_from(ShopCartItem)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["stock", "acl"])
async def test_cart_removal_can_clean_up_multiple_unquotable_lines(buyer, invalid):
    """Cleanup must commit while other stale lines remain, without leaking details."""
    db, principal = buyer
    first, second = seed(db)
    for product in (first, second):
        result = await invoke(
            db, principal, request("cart.add_item", {"product_id": product.id})
        )
        assert result.status == "succeeded"
    if invalid == "stock":
        first.stock_quantity = second.stock_quantity = 0
    else:
        for product in (first, second):
            db.add(
                ShopBotProductRule(
                    bot_id=principal.bot_id, product_id=product.id, effect="deny"
                )
            )
    await db.commit()
    removed = await invoke(
        db,
        principal,
        request(
            "cart.remove_item",
            {
                "product_id": first.id,
                "expected_cart_revision": result.output["revision"],
            },
        ),
    )
    assert removed.status == "succeeded", removed.model_dump()
    assert not removed.output["quote_available"]
    assert removed.output["total_irr"] is None and removed.output["items"] == []
    assert removed.output["unquoted_items"] == [
        {"product_id": second.id, "quantity": 1}
    ]
    assert (
        first.name not in removed.model_dump_json()
        and second.name not in removed.model_dump_json()
    )
    final = await invoke(
        db,
        principal,
        request(
            "cart.remove_item",
            {
                "product_id": second.id,
                "expected_cart_revision": removed.output["revision"],
            },
        ),
    )
    assert final.status == "succeeded" and final.output["items"] == []
    assert final.output["quote_available"] and final.output["total_irr"] == 0
    assert await db.scalar(select(func.count()).select_from(ShopCartItem)) == 0


@pytest.mark.asyncio
async def test_cart_mutation_dry_run_never_creates_cart_or_receipt(buyer):
    """Checking valid stock must not create an empty cart or claim an operation."""
    db, principal = buyer
    product, _ = seed(db)
    result = await invoke(
        db,
        principal,
        request(
            "cart.add_item", {"product_id": product.id, "quantity": 2}, mode="dry_run"
        ),
    )
    assert result.status == "skipped" and result.dry_run and not result.exact_preview
    assert await db.scalar(select(func.count()).select_from(ShopCart)) == 0
    assert await db.scalar(select(func.count()).select_from(ShopActionExecution)) == 0
    assert product.stock_quantity == 5


@pytest.mark.asyncio
async def test_cart_dry_run_checks_real_stock(buyer):
    """No-effect mode still rejects a quantity impossible in the live service."""
    db, principal = buyer
    product, _ = seed(db)
    result = await invoke(
        db,
        principal,
        request(
            "cart.add_item", {"product_id": product.id, "quantity": 6}, mode="dry_run"
        ),
    )
    assert result.status == "failed" and result.error.code == "action_cart_rejected"
    assert await db.scalar(select(func.count()).select_from(ShopCart)) == 0


@pytest.mark.asyncio
async def test_clear_confirmation_cannot_clear_newer_cart_contents(buyer):
    """An older cart revision invalidates its otherwise valid confirmation proof."""
    db, principal = buyer
    product, _ = seed(db)
    added = await invoke(
        db, principal, request("cart.add_item", {"product_id": product.id})
    )
    clear = request("cart.clear", {"expected_cart_revision": added.output["revision"]})
    pending = await invoke(db, principal, clear)
    assert pending.status == "pending_approval"
    token = await issue_authorization(
        db,
        subject=principal,
        approver=principal,
        invocation=clear,
        purpose="customer_confirmation",
        registry=actions(),
    )
    await invoke(db, principal, request("cart.add_item", {"product_id": product.id}))
    result = await invoke(
        db, principal, clear.model_copy(update={"confirmation_receipt": token})
    )
    assert (
        result.status == "failed"
        and result.error.code == "action_cart_revision_conflict"
    )
    line = await db.scalar(select(ShopCartItem))
    assert line.quantity == 2


@pytest.mark.asyncio
async def test_confirmed_clear_executes_once(buyer):
    db, principal = buyer
    product, _ = seed(db)
    added = await invoke(
        db, principal, request("cart.add_item", {"product_id": product.id})
    )
    clear = request("cart.clear", {"expected_cart_revision": added.output["revision"]})
    token = await issue_authorization(
        db,
        subject=principal,
        approver=principal,
        invocation=clear,
        purpose="customer_confirmation",
        registry=actions(),
    )
    approved = clear.model_copy(update={"confirmation_receipt": token})
    first = await invoke(db, principal, approved)
    second = await invoke(db, principal, approved)
    assert first.status == second.status == "succeeded"
    assert first.output == second.output and first.output["items"] == []


@pytest.mark.asyncio
async def test_checkout_returns_missing_requirements_without_order_or_payment(buyer):
    db, principal = buyer
    product, _ = seed(db)
    await invoke(db, principal, request("cart.add_item", {"product_id": product.id}))
    for key in ("checkout.validate", "checkout.prepare"):
        result = await invoke(db, principal, request(key))
        assert result.status == "succeeded", result.model_dump()
        assert result.output["ready"] is False
        assert "shipping_address" in result.output["missing"]
        assert result.output["total_irr"] == 1000
    assert await db.scalar(select(func.count()).select_from(ShopOrder)) == 0
    assert product.stock_quantity == 5


@pytest.mark.asyncio
async def test_support_action_reuses_real_ticket_without_leaking_body(buyer):
    db, principal = buyer
    result = await invoke(
        db,
        principal,
        request(
            "support.create_request",
            {"topic": "general", "body": "شرح خصوصی درخواست آزمایشی"},
        ),
    )
    assert result.status == "succeeded", result.model_dump()
    ticket = await db.get(ShopSupportTicket, result.output["ticket_id"])
    assert (
        ticket.customer_id == principal.customer_id
        and ticket.bot_id == principal.bot_id
    )
    message = await db.scalar(select(ShopSupportMessage))
    assert message.body == "شرح خصوصی درخواست آزمایشی"
    receipt = await db.get(ShopActionExecution, result.execution_receipt)
    assert message.body not in receipt.result_json


@pytest.mark.asyncio
async def test_order_status_cannot_read_another_numeric_customer(buyer):
    db, principal = buyer
    product, _ = seed(db)
    order = ShopOrder(
        store_id=principal.store_id,
        bot_id=principal.bot_id,
        platform=principal.platform,
        platform_user_id=202,
        chat_id=202,
        product_name_snapshot=product.name,
        product_id=product.id,
        quantity=1,
        unit_price_irr=1000,
        total_irr=1000,
        provider="manual_review",
        status="paid",
        invoice_payload=uuid4().hex,
    )
    db.add(order)
    await db.commit()
    denied = await invoke(
        db, principal, request("order.get_status", {"order_id": order.id})
    )
    assert denied.status == "failed" and denied.error.code == "action_order_unavailable"
    listed = await invoke(db, principal, request("order.list_customer_orders"))
    assert listed.output["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,data",
    [
        ("returns.create_request", {"order_id": 1, "reason": "damaged"}),
        ("wholesale.create_application", {"company": "QA"}),
        ("notification.notify_admin", {"message": "QA"}),
        ("order.list_return_eligible_orders", {}),
    ],
)
async def test_missing_services_are_truthfully_unavailable(buyer, key, data):
    db, principal = buyer
    result = await invoke(db, principal, request(key, data))
    assert result.status == "unavailable" and result.output is None
