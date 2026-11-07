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
from models.shop_content import Product, ShopIdentity, ShopOrder
from models.shop_bot_operations import ShopBotOperations
from models.shop_customer_notifications import (
    ShopCustomerNotificationOutbox, ShopStockAlert,
)
from models.shop_customer_support import ShopSupportTicket
from models.shop_multibot import ShopBot, ShopStore
from models.shop_payment import ShopPaymentAttempt
from services.shop_bot_catalog_acl import allowed_for_bot
from services.shop_customer_access import customer_access_allowed
from services.shop_customer_notifications import (
    can_deliver_at_dispatch, claim_outbox_message,
    finish_outbox_message, stock_event_alert_id, stock_event_matches,
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
    operations = await db.get(ShopBotOperations, row.bot_id)
    if operations is not None and (
        operations.desired_state == "disabled"
        or (
            operations.desired_state in {"paused", "maintenance"}
            and row.topic not in {"order", "ticket"}
        )
    ):
        return False
    active = (
        (
            bot.runtime_owner == "registry"
            and (
                bot.status == "active"
                or (
                    row.topic in {"order", "ticket"}
                    and bot.status in {"paused", "maintenance"}
                )
            )
        )
    )
    identity = await db.scalar(select(ShopIdentity).where(
        ShopIdentity.store_id == row.store_id,
        ShopIdentity.bot_id == row.bot_id,
        ShopIdentity.platform_user_id == row.platform_user_id,
        ShopIdentity.platform == bot.platform,
    ))
    owner_valid = bool(
        identity is not None
        and identity.customer_id is not None
        and await customer_access_allowed(db, identity)
    )
    stock_subscribed = False
    if row.topic == "stock" and row.event_key.startswith("stock:"):
        alert_id = stock_event_alert_id(row.event_key)
        if alert_id is None:
            return False
        alert = await db.get(ShopStockAlert, alert_id)
        if (
            alert is None or alert.bot_id != row.bot_id
            or alert.store_id != row.store_id
            or alert.platform_user_id != row.platform_user_id
            or alert.status != "queued"
            or identity is None or alert.customer_id != identity.customer_id
            or not stock_event_matches(alert, row)
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
    event_key: str | None = None,
) -> bool:
    """Process at most one queued message; return whether a row was claimed.

    A transport timeout is not evidence of failure or success. Do not
    automatically retry after any exception. The only automatic retry
    scenario is a request that was never claimed in the database.
    """
    row = await claim_outbox_message(db, bot_id=bot_id, event_key=event_key)
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


async def deliver_order_paid_once(
    db: AsyncSession, *, order_id: int, bot_id: str,
    transport: NotificationTransport,
) -> bool:
    """Consume exactly one persisted paid notice for its original Bot.

    The immediate success reply and the scheduled worker share this durable
    claim, including timeout quarantine. Neither can resend the other's send
    or consume an unrelated queued notification while handling a payment.
    """
    result = await db.execute(select(
        ShopPaymentAttempt, ShopOrder.platform_user_id,
    ).join(
        ShopOrder, ShopOrder.id == ShopPaymentAttempt.order_id,
    ).join(
        ShopBot, ShopBot.id == ShopOrder.bot_id,
    ).where(
        ShopOrder.id == order_id,
        ShopOrder.bot_id == bot_id,
        ShopOrder.store_id == ShopBot.store_id,
        ShopOrder.platform == ShopBot.platform,
        ShopOrder.status.in_(("paid", "paid_unfulfilled")),
        ShopPaymentAttempt.bot_id == bot_id,
        ShopPaymentAttempt.store_id == ShopOrder.store_id,
        ShopPaymentAttempt.platform == ShopOrder.platform,
        ShopPaymentAttempt.status == "paid",
    ))
    record = result.first()
    if record is None:
        return False
    attempt, user_id = record
    event_key = f"order_paid:{order_id}:{attempt.id}"
    owned = await db.scalar(select(ShopCustomerNotificationOutbox.id).where(
        ShopCustomerNotificationOutbox.event_key == event_key,
        ShopCustomerNotificationOutbox.topic == "order",
        ShopCustomerNotificationOutbox.store_id == attempt.store_id,
        ShopCustomerNotificationOutbox.bot_id == bot_id,
        ShopCustomerNotificationOutbox.platform_user_id == user_id,
    ))
    if owned is None:
        return False
    return await deliver_once(
        db, bot_id=bot_id, event_key=event_key, transport=transport,
    )
