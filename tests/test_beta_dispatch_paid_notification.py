"""Native receipt dispatch shares one durable paid-confirmation attempt."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from channels.contracts import Platform
from channels.telegram import TelegramTransport
from models.shop_customer_notifications import ShopCustomerNotificationOutbox
from models.shop_payment import ShopPaymentAttempt
from services.shop_bot_context import resolve_bot_context
from tests.schema_support import TEST_BOT_IDS
from services.shop_customer_notification_dispatch import deliver_once
from services.shop_customer_notifications import enqueue_notification
from services.shop_identity import register_customer
from services.shop_multibot_dispatch import dispatch
from services.shop_payments import ShopPaymentService
from tests import test_shared_payment_settlement as payments


@pytest.fixture
def db(monkeypatch):
    """Use real disposable payment, stock and notification tables."""
    yield from payments.db.__wrapped__(monkeypatch)


class NativePaidClient:
    """Capture native Telegram/Bale messages and verified fake wallet evidence."""

    def __init__(self, *, amount: int, uncertain: bool):
        """Keep a single invoice amount and optional ambiguous network result."""
        self.amount = amount
        self.uncertain = uncertain
        self.messages = []

    async def send_message(self, **kwargs):
        """Capture TelegramTransport's request before a possible timeout."""
        self.messages.append((kwargs["chat_id"], kwargs["text"]))
        if self.uncertain:
            raise TimeoutError("Synthetic response lost after send")

    async def send(self, chat_id, reply):
        """Capture the equivalent Bale request before a possible timeout."""
        self.messages.append((chat_id, reply.text))
        if self.uncertain:
            raise TimeoutError("Synthetic response lost after send")

    async def inquire_transaction(self, transaction_id):
        """Return independent synthetic evidence without contacting Bale."""
        return {
            "status": "paid", "id": transaction_id,
            "userID": 101, "amount": self.amount,
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("uncertain", [False, True])
async def test_receipt_dispatch_consumes_the_paid_outbox_once_with_worker_off(
    db, monkeypatch, platform, uncertain,
):
    """An immediate confirmation cannot be duplicated by receipt replay or worker."""
    monkeypatch.setenv("SHOP_CUSTOMER_NOTIFICATIONS_ENABLED", "false")
    await register_customer(db, bot_id=TEST_BOT_IDS[platform.value], platform=platform, platform_user_id=101)
    context = await resolve_bot_context(
        db, authenticated_bot_id=TEST_BOT_IDS[platform.value],
        authenticated_platform=platform,
    )
    order, product, _ = payments.make_order(db, platform)
    plan = await payments.begin(db, platform, order)
    await ShopPaymentService.mark_invoice_dispatch(db, plan.attempt_id, sent=True)
    await enqueue_notification(
        db, context=context, user_id=101, topic="order",
        event_key="qa-unrelated-earlier", body="پیام مستقل قدیمی",
    )
    await db.commit()

    @asynccontextmanager
    async def sessions():
        """Use real durable receipts and claims in the disposable database."""
        yield db

    monkeypatch.setattr("services.shop_multibot_dispatch.session_maker", sessions)
    native = NativePaidClient(amount=plan.amount, uncertain=uncertain)
    receipt = {"message": {
        "from": {"id": 101}, "chat": {"id": 101, "type": "private"},
        "successful_payment": {
            "invoice_payload": plan.payload, "currency": plan.currency,
            "total_amount": plan.amount,
            "telegram_payment_charge_id": "qa-receipt-charge",
            "provider_payment_charge_id": "qa-provider-reference",
        },
    }}
    async def receive():
        """Run the authenticated Registry dispatch with a native fake transport."""
        return (await dispatch(context, native, receipt))["status"]

    assert await receive() in {"settled", "processed"}
    assert order.status == "paid" and product.stock_quantity == 1
    assert len(native.messages) == 1
    assert "تأیید شد" in native.messages[0][1]
    paid_notice = db.session.scalar(select(ShopCustomerNotificationOutbox).where(
        ShopCustomerNotificationOutbox.event_key == f"order_paid:{order.id}:{plan.attempt_id}",
    ))
    assert paid_notice.status == ("needs_review" if uncertain else "sent")
    assert await receive() in {"settled", "already_settled", "already_processed"}
    assert len(native.messages) == 1

    # Turning on a later worker may consume other work, never this confirmation.
    native.uncertain = False
    transport = (
        TelegramTransport(native, bot_id=context.bot_id)
        if platform == Platform.TELEGRAM else native
    )
    assert await deliver_once(db, bot_id=context.bot_id, transport=transport)
    assert native.messages[-1] == (101, "پیام مستقل قدیمی")
    assert not await deliver_once(db, bot_id=context.bot_id, transport=transport)
    assert len(native.messages) == 2
    assert product.stock_quantity == 1


@pytest.mark.asyncio
async def test_unregistered_bale_invoice_never_falls_back_to_old_ledger(db):
    """A receipt without a scoped payment attempt cannot mutate old order rows."""
    from services.shop_bale_payments import settle_bale_payment
    from services.shop_payments import PaymentRejected

    order, product, _ = payments.make_order(db, Platform.BALE)
    order.status = "pending_payment"
    order.provider = "bale_wallet"
    await db.commit()
    native = NativePaidClient(amount=order.total_irr, uncertain=False)
    with pytest.raises(PaymentRejected):
        await settle_bale_payment(
            db, native, bot_id=TEST_BOT_IDS["bale"], payer_id=101, chat_id=101,
            payment={"invoice_payload": order.invoice_payload},
        )
    assert order.status == "pending_payment"
    assert product.stock_quantity == 3
    assert native.messages == []
    assert db.session.scalar(select(ShopPaymentAttempt)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["status", "id", "userID", "amount"])
async def test_bale_receipt_requires_matching_independent_provider_inquiry(db, tamper):
    """A callback alone cannot mark an order paid or consume product stock."""
    from services.shop_bale_payments import settle_bale_payment
    from services.shop_payments import PaymentRejected

    order, product, _ = payments.make_order(db, Platform.BALE)
    plan = await payments.begin(db, Platform.BALE, order)
    await ShopPaymentService.mark_invoice_dispatch(db, plan.attempt_id, sent=True)
    evidence = {
        "status": "paid", "id": "confirmed-charge", "userID": 101,
        "amount": plan.amount,
    }
    evidence[tamper] = {
        "status": "pending", "id": "another-charge", "userID": 102,
        "amount": plan.amount + 1,
    }[tamper]

    class Inquiry:
        """Return one provider inquiry result without external communication."""

        async def inquire_transaction(self, transaction_id):
            """Bind the lookup to the actual callback charge identifier."""
            assert transaction_id == "confirmed-charge"
            return evidence

    with pytest.raises(PaymentRejected):
        await settle_bale_payment(
            db, Inquiry(), bot_id=TEST_BOT_IDS["bale"], payer_id=101, chat_id=101,
            payment={
                "invoice_payload": plan.payload, "currency": plan.currency,
                "total_amount": plan.amount,
                "telegram_payment_charge_id": "confirmed-charge",
                "provider_payment_charge_id": "confirmed-reference",
            },
        )
    assert order.status == "pending_payment"
    assert product.stock_quantity == 3
