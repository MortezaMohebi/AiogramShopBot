"""Prevent charging unsupported mixed Bale fulfillment and preserve old receipts."""

from uuid import uuid4
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from channels.contracts import Platform
from models.shop_checkout import ShopOrderLine
from models.shop_content import Product, ShopIdentity
from models.shop_digital_delivery import ShopDigitalDelivery, ShopDigitalLicense
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
from services.shop_payments import PaymentRejected, ShopPaymentService
from services.shop_wallet import ShopWalletService, StoreCreditRejected
from services.shop_checkout_policy import legal_credit_for_items
from tests import test_shared_payment_settlement as payments


@pytest.fixture
def db(monkeypatch):
    """Reuse the complete payment schema and private licensed-product fixture."""
    yield from payments.db.__wrapped__(monkeypatch)


def mixed_order(db, *, issued=False):
    """Reproduce a historical Bale basket containing physical and digital goods."""
    order, digital, _ = payments.make_order(db, Platform.BALE, digital=True)
    physical = Product(
        sku="QA-MIXED-" + uuid4().hex,
        name="Physical",
        description="QA",
        price=1000,
        stock_quantity=3,
        product_type="physical",
        requires_shipping=True,
        is_published=True,
    )
    db.add(physical)
    db.session.flush()
    db.add(
        ShopOrderLine(
            order_id=order.id,
            product_id=physical.id,
            product_name_snapshot=physical.name,
            sku_snapshot=physical.sku,
            quantity=1,
            unit_price_irr=1000,
            total_irr=1000,
        )
    )
    order.subtotal_irr += 1000
    order.shipping_irr = 500
    order.total_irr = order.subtotal_irr + order.shipping_irr
    order.shipping_address = "نشانی آزمایشی تهران"
    order.shipping_method_snapshot = "پست"
    if issued:
        order.provider = "bale_wallet"
        order.status = "pending_payment"
        order.payment_currency = "IRR"
        order.payment_amount = order.total_irr
        db.add(
            ShopPaymentAttempt(
                store_id=order.store_id,
                bot_id=order.bot_id,
                order_id=order.id,
                platform="bale",
                provider="bale_wallet",
                currency="IRR",
                amount=order.total_irr,
                payload=order.invoice_payload,
                status="invoice_sent",
            )
        )
    db.session.commit()
    return order, physical, digital


@pytest.mark.asyncio
async def test_bale_mixed_order_cannot_issue_native_invoice(db):
    """An unsupported fulfillment must fail before accepting a customer's money."""
    order, _, _ = mixed_order(db)
    with pytest.raises(PaymentRejected):
        await payments.begin(db, Platform.BALE, order)
    assert order.status == "approved_unpaid"
    assert db.session.scalar(select(ShopPaymentAttempt)) is None


@pytest.mark.asyncio
async def test_old_bale_mixed_invoice_precheckout_is_declined(db):
    """A stale provider invoice is refused even after checkout is guarded."""
    order, _, _ = mixed_order(db, issued=True)
    accepted, reason = await ShopPaymentService.precheckout(
        db,
        platform=Platform.BALE,
        payer_id=101,
        payload=order.invoice_payload,
        currency="IRR",
        amount=order.total_irr,
    )
    assert accepted is False and reason


@pytest.mark.asyncio
async def test_old_paid_bale_mixed_receipt_records_refund_obligation(db):
    """Already received money remains auditable without partially consuming stock."""
    order, physical, digital = mixed_order(db, issued=True)
    paid, changed = await ShopPaymentService.settle(
        db,
        platform=Platform.BALE,
        payer_id=101,
        chat_id=101,
        payload=order.invoice_payload,
        currency="IRR",
        amount=order.total_irr,
        charge_id="qa-old-bale-mixed-charge",
        provider_charge_id="qa-reference",
    )
    assert changed is True and paid.status == "paid_unfulfilled"
    assert physical.stock_quantity == digital.stock_quantity == 3
    attempt = db.session.scalar(select(ShopPaymentAttempt))
    assert attempt.status == "paid" and attempt.completed_at and paid.paid_at
    assert (
        db.session.scalar(
            select(ShopRefundCase).where(
                ShopRefundCase.order_id == order.id,
            )
        ).status
        == "requested"
    )
    assert db.session.scalar(select(ShopDigitalDelivery)) is None
    assert all(
        row.state == "available"
        for row in db.session.scalars(select(ShopDigitalLicense))
    )


@pytest.mark.asyncio
async def test_bale_mixed_store_credit_is_hidden_and_cannot_debit(db, monkeypatch):
    """An old mixed request cannot bypass fulfillment through merchant credit."""
    from services import shop_wallet

    async def features(*_args, **_kwargs):
        return SimpleNamespace(store_credit_enabled=True)

    async def enabled(*_args, **_kwargs):
        return True

    monkeypatch.setattr(shop_wallet, "get_features", features)
    monkeypatch.setattr(shop_wallet, "rail_enabled", enabled)
    order, physical, digital = mixed_order(db)
    identity = ShopIdentity(
        store_id=order.store_id,
        bot_id=order.bot_id,
        platform="bale",
        platform_user_id=101,
    )
    db.add(identity)
    await db.commit()
    await ShopWalletService.apply(
        db,
        identity_id=identity.id,
        delta_irr=10000,
        operation_key="qa-mixed-funding-" + uuid4().hex,
        reason="Synthetic fixture",
        actor="qa",
    )
    await db.commit()
    with pytest.raises(StoreCreditRejected):
        await ShopWalletService.pay_order(
            db,
            platform=Platform.BALE,
            user_id=101,
            order_id=order.id,
        )
    assert not legal_credit_for_items(Platform.BALE, {"physical", "digital"})
    assert await ShopWalletService.balance(db, Platform.BALE, 101) == 10000
    assert physical.stock_quantity == digital.stock_quantity == 3
    assert order.status == "approved_unpaid"
