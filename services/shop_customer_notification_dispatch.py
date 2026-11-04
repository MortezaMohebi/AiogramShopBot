"""Dispatch one claimed Telegram/Bale notification with no ambiguous retry.

Provider work is performed only after an Outbox row is durably marked as
processing. The worker rechecks the exact Bot, Store, customer consent, and
product/ticket ownership. Unknown network outcomes are quarantined; a
process crash leaves the row processing for human reconciliation.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply
from models.shop_content import Product, ShopIdentity
from models.shop_customer_notifications import (
    ShopCustomerNotificationOutbox, ShopStockAlert,
)
from models.shop_customer_support import ShopSupportTicket
from models.shop_multibot import ShopBot, ShopStore
from services.shop_bot_catalog_acl import allowed_for_bot
from services.shop_customer_notifications import (
    can_deliver_at_dispatch, claim_outbox_message,
    finish_outbox_message,
)

_logger = logging.getLogger(__name__)


class NotificationTransport(Protocol):
    """A Telegram/Bale adapter with one common private-message interface."""

    async def send(self, chat_id: int, reply: BotReply) -> None:
        """Deliver one previously claimed and authorized private message."""


async def _preflight(
    db: AsyncSession, row: ShopCustomerNotificationOutbox,
) -> bool:
    """Reject revoked consent, inactive Stores and stale subscriptions."""
    bot = await db.get(ShopBot, row.bot_id)
    store = await db.get(ShopStore, row.store_id)
    if (
        bot is None or store is None or store.state != "active"
        or bot.store_id != row.store_id
    ):
        return False
    active = (
        (bot.status == "legacy" and bot.runtime_owner == "legacy")
        or (bot.status == "active" and bot.runtime_owner == "registry")
    )
    identity = await db.scalar(select(ShopIdentity).where(
        ShopIdentity.store_id == row.store_id,
        ShopIdentity.bot_id == row.bot_id,
        ShopIdentity.platform_user_id == row.platform_user_id,
        ShopIdentity.platform == bot.platform,
    ))
    owner_valid = bool(
        identity is not None
        and identity.is_blocked is False
        and identity.customer_id is not None
    )
    stock_subscribed = False
    if row.topic == "stock" and row.event_key.startswith("stock:"):
        try:
            alert_id = int(row.event_key.removeprefix("stock:"))
        except ValueError:
            return False
        alert = await db.get(ShopStockAlert, alert_id)
        if (
            alert is None or alert.bot_id != row.bot_id
            or alert.store_id != row.store_id
            or alert.platform_user_id != row.platform_user_id
            or alert.status != "queued"
            or identity is None or alert.customer_id != identity.customer_id
        ):
            return False
        product = await db.get(Product, alert.product_id)
        stock_subscribed = bool(
            product is not None
            and product.store_id == row.store_id
            and product.stock_quantity > 0
            and product.is_published
            and await allowed_for_bot(db, row.bot_id, [product.id])
        )
    elif row.topic == "ticket" and row.event_key.startswith("ticket_reply:"):
        parts = row.event_key.split(":")
        if len(parts) != 3:
            return False
        try:
            ticket_id = int(parts[1])
        except ValueError:
            return False
        ticket = await db.get(ShopSupportTicket, ticket_id)
        owner_valid = owner_valid and bool(
            ticket is not None and identity is not None
            and ticket.store_id == row.store_id
            and ticket.bot_id == row.bot_id
            and ticket.origin_identity_id == identity.id
        )

    return can_deliver_at_dispatch(
        topic=row.topic,
        advertising_consent=bool(
            identity is not None and identity.allow_announcements
        ),
        explicit_request=stock_subscribed,
        bot_active=active,
        owner_valid=owner_valid,
    )


async def deliver_once(
    db: AsyncSession, *, bot_id: str,
    transport: NotificationTransport,
) -> bool:
    """Process at most one queued message; return whether a row was claimed.

    A transport timeout is not evidence of failure or success. Do not
    automatically retry after any exception. The only automatic retry
    scenario is a request that was never claimed in the database.
    """
    row = await claim_outbox_message(db, bot_id=bot_id)
    if row is None:
        return False
    if not await _preflight(db, row):
        await finish_outbox_message(
            db, outbox_id=row.id, succeeded=False, cancelled=True,
        )
        return True

    try:
        # Bot API private-chat ID is the authenticated platform user ID.
        # Provider-specific media/transcoding is not used by this worker.
        await transport.send(
            row.platform_user_id, BotReply(row.body),
        )
    except Exception:
        _logger.warning(
            "Notification delivery outcome uncertain: outbox_id=%s bot_id=%s",
            row.id, row.bot_id,
        )
        await finish_outbox_message(
            db, outbox_id=row.id, succeeded=False,
        )
        return True

    await finish_outbox_message(
        db, outbox_id=row.id, succeeded=True,
    )
    return True
