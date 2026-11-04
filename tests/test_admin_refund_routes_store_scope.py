"""Exercise signed refund routing without any real money or provider calls."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

import config
from models.shop_admin_control import AdminProfile
from models.shop_content import Product, ShopOrder
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
from models.shop_staff import ShopStaff
from models.shop_uom import default_unit_id
from services.shop_uom import seed_store_units
from tests.test_campaign_admin_store_scope import (
    BOT_A, BOT_B, STORE_A, STORE_B, campaign_app,
)


class LegacyRefundBot:
    """Record attempted use of the global client without opening a socket."""

    def __init__(self):
        """Keep only synthetic call arguments."""
        self.calls = []

    async def refund_star_payment(self, **payload):
        """Simulate the real client only if incorrect routing reaches it."""
        self.calls.append(payload)
        return True


@pytest.fixture
def refund_app(campaign_app):
    """Provide an enrolled finance session with explicit Store memberships."""
    campaign_app.db.get(ShopStaff, 7).role = "finance"
    campaign_app.db.add(AdminProfile(
        staff_id=7, display_name="Finance fixture", time_zone="UTC",
        mfa_secret="offline-enrollment-marker", last_totp_step=-1,
        recovery_hashes="[]",
    ))
    for store_id in (STORE_A, STORE_B):
        seed_store_units(campaign_app.db, store_id)
    campaign_app.db.commit()
    campaign_app.legacy.state.telegram_bot = LegacyRefundBot()
    return campaign_app


def paid_case(app, *, store_id=STORE_A, stars=False):
    """Persist an exact paid Order, receipt and requested offline refund."""
    payload = "offline-invoice-" + uuid4().hex
    bot_id = BOT_A if store_id == STORE_A else BOT_B
    provider = "telegram_stars" if stars else "telegram_fiat"
    product = Product(
        store_id=store_id, sku=payload, name="محصول آزمایشی", description="شرح",
        price=100, uom_id=default_unit_id(store_id),
    )
    app.db.add(product)
    app.db.flush()
    now = datetime.now(timezone.utc)
    order = ShopOrder(
        store_id=store_id, bot_id=bot_id, platform="telegram",
        platform_user_id=101, chat_id=101, product_id=product.id,
        product_name_snapshot="محصول آزمایشی", quantity=1,
        unit_price_irr=100, total_irr=100, provider=provider, status="paid",
        invoice_payload=payload, paid_at=now,
        telegram_payment_charge_id="offline-charge-" + uuid4().hex,
        payment_currency="XTR" if stars else "IRR",
        payment_amount=25 if stars else 100,
        total_stars_snapshot=25 if stars else None,
    )
    app.db.add(order)
    app.db.flush()
    receipt = ShopPaymentAttempt(
        store_id=store_id, bot_id=bot_id, order_id=order.id,
        platform="telegram", provider=provider,
        currency=order.payment_currency, amount=order.payment_amount,
        payload=payload, status="paid", completed_at=now,
    )
    case = ShopRefundCase(
        order_id=order.id, status="requested", reason="Offline refund request",
        actor="customer:101",
    )
    app.db.add_all([receipt, case])
    app.db.commit()
    return order, receipt, case


def decision(**changes):
    """Prepare explicit evidence without granting any extra authority."""
    return {
        "action": "manual", "provider_reference": "offline-proof-123",
        "confirmation": "REFUND_VERIFIED", **changes,
    }


@pytest.mark.asyncio
async def test_finance_can_record_manual_refund_in_current_store(refund_app):
    """Nondefault Stores use the same audited refund core as legacy Stores."""
    order, receipt, case = paid_case(refund_app)
    response = await refund_app.request(
        "POST", f"/refunds/{case.id}/resolve", payload=decision(),
    )
    assert response.status_code == 200, response.text
    assert (case.status, order.status, receipt.status) == (
        "confirmed", "refunded", "refunded",
    )
    assert case.provider_reference == "offline-proof-123"
    assert case.resolution_note == "Verified by staff:7"
    assert refund_app.legacy.state.telegram_bot.calls == []


@pytest.mark.asyncio
async def test_refund_cannot_mutate_another_selected_store(refund_app):
    """A finance role and active read selection cannot override current Store."""
    order, receipt, case = paid_case(refund_app, store_id=STORE_B)
    response = await refund_app.request(
        "POST", f"/refunds/{case.id}/resolve", payload=decision(),
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "store_switch_required"
    assert (case.status, order.status, receipt.status) == (
        "requested", "paid", "paid",
    )
    assert refund_app.legacy.state.telegram_bot.calls == []


@pytest.mark.asyncio
async def test_refund_still_requires_explicit_confirmation(refund_app):
    """Store authorization cannot substitute for an operator's confirmation."""
    order, receipt, case = paid_case(refund_app)
    response = await refund_app.request(
        "POST", f"/refunds/{case.id}/resolve",
        payload=decision(confirmation=""),
    )
    assert response.status_code == 422, response.text
    assert (case.status, order.status, receipt.status) == (
        "requested", "paid", "paid",
    )


@pytest.mark.asyncio
async def test_registry_stars_cannot_fall_back_to_global_client(
    refund_app, monkeypatch,
):
    """Unavailable original Registry credentials never select the legacy bot."""
    monkeypatch.setattr(config, "TELEGRAM_STARS_REFUNDS_ENABLED", True)
    order, receipt, case = paid_case(refund_app, stars=True)
    response = await refund_app.request(
        "POST", f"/refunds/{case.id}/resolve",
        payload=decision(action="stars", confirmation="REFUND_STARS_EXECUTE"),
    )
    assert response.status_code == 409, response.text
    assert "ربات اصلی" in response.json()["detail"]
    assert (case.status, order.status, receipt.status) == (
        "requested", "paid", "paid",
    )
    assert refund_app.legacy.state.telegram_bot.calls == []
