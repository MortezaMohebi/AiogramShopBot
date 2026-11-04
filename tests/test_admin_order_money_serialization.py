"""Verify dashboard summaries preserve frozen payment currency and amount."""

from __future__ import annotations

from uuid import uuid4

import pytest

from models.shop_content import Product, ShopOrder
from models.shop_staff import ShopStaff
from models.shop_uom import default_unit_id
from tests.test_admin_refund_routes_store_scope import paid_case, refund_app
from tests.test_campaign_admin_store_scope import (
    BOT_A, STORE_A, campaign_app,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/overview", "/orders", "/refunds"])
async def test_stars_summary_uses_frozen_seven_xtr_metadata(refund_app, path):
    """A 9,000 IRR catalog value never replaces the frozen seven-Star charge."""
    order, receipt, _ = paid_case(refund_app, stars=True)
    product = refund_app.db.get(Product, order.product_id)
    product.price = 9000
    product.price_stars = 99  # A later catalog edit cannot rewrite the receipt.
    order.unit_price_irr = order.total_irr = 9000
    order.total_stars_snapshot = order.payment_amount = receipt.amount = 7
    refund_app.db.commit()
    response = await refund_app.request("GET", path)
    assert response.status_code == 200, response.text
    payload = response.json()
    records = (payload["recent_orders"] if path == "/overview"
               else payload["items"] if path == "/orders" else payload)
    assert len(records) == 1
    row = records[0]
    assert {
        "total_stars_snapshot": row.get("total_stars_snapshot"),
        "payment_currency": row.get("payment_currency"),
        "payment_amount": row.get("payment_amount"),
    } == {
        "total_stars_snapshot": 7, "payment_currency": "XTR",
        "payment_amount": "7",
    }
    book_value = row["amount_irr"] if path == "/refunds" else row["total_irr"]
    assert book_value == "9000"


@pytest.mark.asyncio
async def test_unpaid_review_summary_explicitly_includes_nullable_money_fields(
    refund_app,
):
    """A prepayment review has no inferred settled currency or Stars amount."""
    refund_app.db.get(ShopStaff, 7).role = "sales"
    product = Product(
        store_id=STORE_A, sku=uuid4().hex, name="محصول آزمایشی", description="شرح",
        price=9000, uom_id=default_unit_id(STORE_A),
    )
    refund_app.db.add(product)
    refund_app.db.flush()
    order = ShopOrder(
        store_id=STORE_A, bot_id=BOT_A, platform="telegram",
        platform_user_id=101, chat_id=101, product_id=product.id,
        product_name_snapshot="محصول آزمایشی", quantity=1, unit_price_irr=9000,
        total_irr=9000, provider="manual_review", status="pending_review",
        invoice_payload=uuid4().hex,
    )
    refund_app.db.add(order)
    refund_app.db.commit()
    response = await refund_app.request("GET", "/orders/review-queue")
    assert response.status_code == 200, response.text
    row = response.json()[0]
    fields = {"total_stars_snapshot", "payment_currency", "payment_amount"}
    assert fields.issubset(row), row
    assert {field: row[field] for field in fields} == {
        "total_stars_snapshot": None, "payment_currency": None,
        "payment_amount": None,
    }
    assert row["total_irr"] == "9000"
