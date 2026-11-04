"""Stock outbox keys support the first subscriptions and remain bounded."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from channels.contracts import Platform
from models.shop_customer_notifications import ShopCustomerNotificationOutbox
from models.shop_multibot import DEFAULT_STORE_ID
from services.shop_bot_context import resolve_legacy_bot_context
from services.shop_customer_notifications import (
    claim_outbox_message,
    enqueue_notification,
    finish_outbox_message,
    prepare_stock_alerts,
    toggle_stock_alert,
)
from services.shop_customer_notification_dispatch import deliver_once
from services.shop_identity import register_customer
from tests.test_shared_cart import db, seed


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_first_nine_stock_subscriptions_queue_once(db, platform):
    """Single-digit alert IDs must not be rejected as short idempotency keys."""
    product, _ = seed(db)
    product.stock_quantity = 0
    db.session.commit()
    context = await resolve_legacy_bot_context(
        db, authenticated_platform=platform,
    )
    for user_id in range(101, 110):
        await register_customer(db, platform=platform, platform_user_id=user_id)
        await toggle_stock_alert(
            db, context=context, user_id=user_id, product_id=product.id,
        )
    product.stock_quantity = 9
    db.session.commit()
    assert await prepare_stock_alerts(db, store_id=DEFAULT_STORE_ID) == 9
    messages = db.session.scalars(
        select(ShopCustomerNotificationOutbox)
        .order_by(ShopCustomerNotificationOutbox.id)
    ).all()
    assert [row.event_key for row in messages] == [
        "stock:1", "stock:2", "stock:3", "stock:4", "stock:5",
        "stock:6", "stock:7", "stock:8", "stock:9",
    ]
    assert all(row.status == "queued" for row in messages)
    assert await prepare_stock_alerts(db, store_id=DEFAULT_STORE_ID) == 0
    assert db.session.query(ShopCustomerNotificationOutbox).count() == 9


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_key",
    ["short", "qa\nevent-key", "qa\x00event-key", " " * 8, "x" * 121],
    ids=["too-short", "line-break", "nul", "whitespace", "too-long"],
)
async def test_invalid_outbox_keys_do_not_enqueue(db, event_key):
    """Opaque event references must remain bounded printable identifiers."""
    await register_customer(
        db, platform=Platform.TELEGRAM, platform_user_id=101,
    )
    context = await resolve_legacy_bot_context(
        db, authenticated_platform=Platform.TELEGRAM,
    )
    assert not await enqueue_notification(
        db, context=context, user_id=101, topic="order",
        event_key=event_key, body="پیام عملیاتی آزمایشی",
    )
    assert db.session.query(ShopCustomerNotificationOutbox).count() == 0


class NotificationRecorder:
    """Capture real dispatch sends and optionally lose the provider response."""

    def __init__(self, *, uncertain=False):
        """Retain observable send attempts, including an ambiguous one."""
        self.messages = []
        self.uncertain = uncertain

    async def send(self, chat_id, reply):
        """Record accepted messages before a possible synthetic timeout."""
        self.messages.append((chat_id, reply.text))
        if self.uncertain:
            raise TimeoutError("Synthetic accepted response lost")


async def queued_stock(db, platform):
    """Create a real first-generation subscription and its queued outbox row."""
    product, _ = seed(db)
    product.stock_quantity = 0
    db.session.commit()
    context = await resolve_legacy_bot_context(db, authenticated_platform=platform)
    await register_customer(db, platform=platform, platform_user_id=101)
    await toggle_stock_alert(db, context=context, user_id=101, product_id=product.id)
    product.stock_quantity = 2
    db.session.commit()
    assert await prepare_stock_alerts(db, store_id=DEFAULT_STORE_ID) == 1
    first = db.session.scalars(select(ShopCustomerNotificationOutbox)).one()
    return context, product, first


async def rearm_stock(db, context, product, *, cancel_first):
    """Make a separate explicit request after another out-of-stock interval."""
    product.stock_quantity = 0
    db.session.commit()
    if cancel_first:
        await toggle_stock_alert(db, context=context, user_id=101, product_id=product.id)
    await toggle_stock_alert(db, context=context, user_id=101, product_id=product.id)
    product.stock_quantity = 2
    db.session.commit()
    assert await prepare_stock_alerts(db, store_id=DEFAULT_STORE_ID) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("uncertain", [False, True], ids=["sent", "uncertain"])
async def test_new_explicit_stock_request_queues_a_distinct_notice(db, platform, uncertain):
    """Rearming creates a new notice while old sent/unknown receipts stay final."""
    context, product, first = await queued_stock(db, platform)
    transport = NotificationRecorder(uncertain=uncertain)
    assert await deliver_once(db, bot_id=context.bot_id, transport=transport)
    original_status = "needs_review" if uncertain else "sent"
    assert first.status == original_status
    await rearm_stock(db, context, product, cancel_first=uncertain)
    transport.uncertain = False
    assert await deliver_once(db, bot_id=context.bot_id, transport=transport)
    assert not await deliver_once(db, bot_id=context.bot_id, transport=transport)
    notices = db.session.scalars(select(ShopCustomerNotificationOutbox).order_by(
        ShopCustomerNotificationOutbox.id,
    )).all()
    assert len(notices) == 2 and len(transport.messages) == 2
    assert notices[0].status == original_status and notices[1].status == "sent"
    assert notices[0].event_key != notices[1].event_key


@pytest.mark.asyncio
async def test_cancelled_stock_generation_cannot_borrow_new_subscription(db):
    """An old queued notice is cancelled even after a new request is queued."""
    context, product, old = await queued_stock(db, Platform.TELEGRAM)
    await rearm_stock(db, context, product, cancel_first=True)
    transport = NotificationRecorder()
    assert await deliver_once(db, bot_id=context.bot_id, transport=transport)
    assert old.status == "cancelled" and transport.messages == []
    assert await deliver_once(db, bot_id=context.bot_id, transport=transport)
    assert len(transport.messages) == 1


@pytest.mark.asyncio
async def test_old_stock_completion_does_not_finish_the_new_generation(db):
    """A late old send receipt must not consume a newly requested alert."""
    context, product, old = await queued_stock(db, Platform.BALE)
    claimed = await claim_outbox_message(db, bot_id=context.bot_id)
    assert claimed.id == old.id
    await rearm_stock(db, context, product, cancel_first=True)
    await finish_outbox_message(db, outbox_id=old.id, succeeded=True)
    transport = NotificationRecorder()
    assert await deliver_once(db, bot_id=context.bot_id, transport=transport)
    assert len(transport.messages) == 1
