"""Notification access follows effective CRM restriction expiry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from channels.contracts import Platform
from models.shop_customer_crm import ShopCustomerProfile
from models.shop_customer_notifications import ShopCustomerNotificationOutbox
from services.shop_bot_context import resolve_bot_context
from services.shop_customer_notification_dispatch import deliver_once
from services.shop_customer_notifications import enqueue_notification
from services.shop_identity import register_customer
from tests.test_beta_stock_queue import NotificationRecorder
from tests.test_shared_cart import db
from tests.schema_support import TEST_BOT_IDS


def block_identity(db, identity, expiry):
    """Set a real stored CRM block, retaining its documented expiry state."""
    identity.is_blocked = True
    db.add(ShopCustomerProfile(
        identity_id=identity.id, restriction_until=expiry,
    ))
    db.session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize(
    "expiry_offset,allowed", [(-1, True), (1, False), (None, False)],
    ids=["expired", "future", "permanent"],
)
async def test_enqueue_uses_effective_customer_restriction(
    db, platform, expiry_offset, allowed,
):
    """Expired restrictions permit operational notices while active bans deny."""
    context = await resolve_bot_context(
        db, authenticated_bot_id=TEST_BOT_IDS[platform.value],
        authenticated_platform=platform,
    )
    identity = await register_customer(
        db, bot_id=TEST_BOT_IDS[platform.value],
        platform=platform, platform_user_id=101,
    )
    expiry = (
        datetime.now(timezone.utc) + timedelta(days=expiry_offset)
        if expiry_offset is not None else None
    )
    block_identity(db, identity, expiry)
    accepted = await enqueue_notification(
        db, context=context, user_id=101, topic="order",
        event_key="qa-effective-restriction", body="پیام عملیاتی پس از بررسی محدودیت",
    )
    assert accepted is allowed
    assert identity.is_blocked is True


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize(
    "expiry_offset,allowed", [(-1, True), (1, False), (None, False)],
    ids=["expired", "future", "permanent"],
)
async def test_dispatch_rechecks_effective_restriction(
    db, platform, expiry_offset, allowed,
):
    """A queued message follows live expiry without lifting permanent blocks."""
    context = await resolve_bot_context(
        db, authenticated_bot_id=TEST_BOT_IDS[platform.value],
        authenticated_platform=platform,
    )
    identity = await register_customer(
        db, bot_id=TEST_BOT_IDS[platform.value],
        platform=platform, platform_user_id=101,
    )
    assert await enqueue_notification(
        db, context=context, user_id=101, topic="ticket",
        event_key="qa-live-restriction", body="پیام پشتیبانی پس از بررسی محدودیت",
    )
    await db.commit()
    expiry = (
        datetime.now(timezone.utc) + timedelta(days=expiry_offset)
        if expiry_offset is not None else None
    )
    block_identity(db, identity, expiry)
    transport = NotificationRecorder()
    assert await deliver_once(db, bot_id=context.bot_id, transport=transport)
    assert bool(transport.messages) is allowed
    row = db.session.scalars(select(ShopCustomerNotificationOutbox)).one()
    assert row.status == ("sent" if allowed else "cancelled")
