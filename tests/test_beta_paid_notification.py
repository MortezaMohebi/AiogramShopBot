"""Immediate paid confirmations share the durable worker receipt."""

from __future__ import annotations

from uuid import uuid4

import pytest

from channels.contracts import Platform
from models.shop_content import ShopOrder
from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import LEGACY_BOT_IDS, ShopBot
from models.shop_payment import ShopPaymentAttempt
from services import shop_customer_notification_dispatch as dispatch
from services.shop_customer_notifications import enqueue_notification
from services.shop_bot_context import resolve_legacy_bot_context
from services.shop_identity import register_customer
from tests.test_beta_stock_queue import NotificationRecorder
from tests.test_shared_cart import db, seed


async def paid_notice(db, platform):
    """Persist a real paid Order/Attempt and an older unrelated queued notice."""
    product, _ = seed(db)
    await register_customer(db, platform=platform, platform_user_id=101)
    context = await resolve_legacy_bot_context(db, authenticated_platform=platform)
    order = ShopOrder(
        bot_id=context.bot_id, store_id=context.store_id,
        platform=platform.value, platform_user_id=101, chat_id=101,
        product_id=product.id, product_name_snapshot=product.name,
        quantity=1, unit_price_irr=1000, total_irr=1000,
        provider="telegram_fiat" if platform == Platform.TELEGRAM else "bale_wallet",
        status="paid", invoice_payload=uuid4().hex,
    )
    db.add(order)
    await db.flush()
    attempt = ShopPaymentAttempt(
        store_id=context.store_id, bot_id=context.bot_id,
        order_id=order.id, platform=platform.value, provider=order.provider,
        currency="IRR", amount=1000, payload=order.invoice_payload,
        status="paid",
    )
    db.add(attempt)
    await db.flush()
    await enqueue_notification(
        db, context=context, user_id=101, topic="order",
        event_key="qa-older-notice", body="پیام قدیمی غیرمرتبط",
    )
    key = f"order_paid:{order.id}:{attempt.id}"
    await enqueue_notification(
        db, context=context, user_id=101, topic="order",
        event_key=key, body="پرداخت همین سفارش تأیید شد",
    )
    await db.commit()
    return context, order


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("uncertain", [False, True])
async def test_immediate_paid_confirmation_does_not_consume_or_replay_other_notice(
    db, platform, uncertain,
):
    """Targeted confirmation sends once; worker keeps unrelated queued work."""
    context, order = await paid_notice(db, platform)
    transport = NotificationRecorder(uncertain=uncertain)
    assert await dispatch.deliver_order_paid_once(
        db, order_id=order.id, bot_id=context.bot_id, transport=transport,
    )
    assert transport.messages == [(101, "پرداخت همین سفارش تأیید شد")]
    assert not await dispatch.deliver_order_paid_once(
        db, order_id=order.id, bot_id=context.bot_id, transport=transport,
    )
    transport.uncertain = False
    assert await dispatch.deliver_once(db, bot_id=context.bot_id, transport=transport)
    assert transport.messages == [
        (101, "پرداخت همین سفارش تأیید شد"), (101, "پیام قدیمی غیرمرتبط"),
    ]
    assert not await dispatch.deliver_once(db, bot_id=context.bot_id, transport=transport)


@pytest.mark.asyncio
async def test_paid_confirmation_refuses_another_bot_order(db):
    """An order ID cannot select a different Bot's notification receipt."""
    _, order = await paid_notice(db, Platform.TELEGRAM)
    transport = NotificationRecorder()
    assert not await dispatch.deliver_order_paid_once(
        db, order_id=order.id, bot_id=LEGACY_BOT_IDS["bale"], transport=transport,
    )
    assert transport.messages == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,permitted", [("paused", True), ("maintenance", True), ("disabled", False)],
)
async def test_operational_paid_confirmation_during_paused_shopping(db, status, permitted):
    """Paused shopping retains paid support; disabled Bot sends fail closed."""
    context, order = await paid_notice(db, Platform.TELEGRAM)
    bot = db.session.get(ShopBot, context.bot_id)
    bot.runtime_owner = "registry"
    bot.status = status
    db.session.commit()
    transport = NotificationRecorder()
    await dispatch.deliver_order_paid_once(
        db, order_id=order.id, bot_id=context.bot_id, transport=transport,
    )
    assert bool(transport.messages) is permitted


@pytest.mark.asyncio
async def test_paid_confirmation_checks_disabled_operational_override(db):
    """An active Bot registry row cannot bypass a disabled operational request."""
    context, order = await paid_notice(db, Platform.TELEGRAM)
    db.add(ShopBotOperations(bot_id=context.bot_id, desired_state="disabled"))
    await db.commit()
    transport = NotificationRecorder()
    await dispatch.deliver_order_paid_once(
        db, order_id=order.id, bot_id=context.bot_id, transport=transport,
    )
    assert transport.messages == []


@pytest.mark.asyncio
async def test_paused_operational_override_does_not_send_marketing(db):
    """Operational support during a pause must not authorize advertising."""
    context, _ = await paid_notice(db, Platform.TELEGRAM)
    identity = await register_customer(
        db, platform=Platform.TELEGRAM, platform_user_id=101,
    )
    identity.allow_announcements = True
    db.add(ShopBotOperations(bot_id=context.bot_id, desired_state="paused"))
    await db.commit()
    assert await enqueue_notification(
        db, context=context, user_id=101, topic="marketing",
        event_key="qa-paused-marketing", body="تبلیغ متوقف‌شده",
    )
    await db.commit()
    transport = NotificationRecorder()
    assert await dispatch.deliver_once(
        db, bot_id=context.bot_id, event_key="qa-paused-marketing", transport=transport,
    )
    assert transport.messages == []
