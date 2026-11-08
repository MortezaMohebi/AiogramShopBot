"""Opt-in Telegram/Bale customer notification worker for the Beta.

Start with SHOP_CUSTOMER_NOTIFICATIONS_ENABLED=true only after fake-Provider
and real Provider smoke tests are approved. This process never activates Bot
credentials, overwrites existing webhooks, creates invoices or retries an
ambiguous send. A claimed message that survives a crash requires review.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from sqlalchemy import select

import config
from channels.telegram import TelegramTransport
from db import create_db_and_tables, engine, session_maker
from models.shop_customer_notifications import ShopCustomerNotificationOutbox
from models.shop_multibot import ShopBot, ShopStore
from services.shop_bot_secrets import resolve_active_token
from services.shop_customer_notification_dispatch import (
    NotificationTransport, deliver_once,
)
from services.shop_customer_notifications import prepare_stock_alerts
from services.shop_service_controls import service_enabled, watch_controls

_logger = logging.getLogger(__name__)
_POLL_SECONDS = 5


@asynccontextmanager
async def _transport_for_bot(
    bot_id: str,
) -> AsyncIterator[NotificationTransport]:
    """Resolve a server-selected Bot and its correct secret, never a user ID."""
    async with session_maker() as db:
        bot = await db.get(ShopBot, bot_id)
        if (
            bot is None
            or not (
                bot.runtime_owner == "registry" and bot.status == "active"
            )
        ):
            raise ValueError("Bot is not active for notification delivery.")
        token = await db.run_sync(
            lambda session: resolve_active_token(session, bot_id=bot_id),
        )
        platform = bot.platform

    from services.shop_multibot_client import provider_client

    async with provider_client(platform, token, bot_id=bot_id) as client:
        if platform == "telegram":
            yield TelegramTransport(client, bot_id=bot_id)
        else:
            yield client


async def _active_bot_ids() -> list[str]:
    """Bound scheduled work to active Stores, Bots and queued notifications."""
    async with session_maker() as db:
        query = select(ShopBot.id).join(
            ShopCustomerNotificationOutbox,
            ShopCustomerNotificationOutbox.bot_id == ShopBot.id,
        ).join(
            ShopStore, ShopStore.id == ShopBot.store_id,
        ).where(
            ShopStore.state == "active",
            ShopCustomerNotificationOutbox.status == "queued",
            ShopBot.runtime_owner == "registry",
            ShopBot.status == "active",
        ).distinct().order_by(ShopBot.id).limit(50)
        return (await db.scalars(query)).all()


async def _queue_stock_alerts() -> None:
    """Produce bounded, per-Store stock notices before the normal Outbox pass."""
    async with session_maker() as db:
        stores = (await db.scalars(select(ShopStore.id).where(
            ShopStore.state == "active",
        ).order_by(ShopStore.id).limit(100))).all()
    for store_id in stores:
        async with session_maker() as db:
            try:
                await prepare_stock_alerts(db, store_id=store_id, limit=50)
            except Exception:
                # Failure must not create duplicate messages or stop all Bots.
                await db.rollback()
                _logger.exception(
                    "Stock alert staging failed for Store %s", store_id,
                )


async def main() -> None:
    """Continuously dispatch bounded notifications only when opted in."""
    # The same database check used by the bot runtime rejects missing tables.
    await create_db_and_tables()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        async with watch_controls(session_maker):
            next_stock_scan = 0.0
            while not stop.is_set():
                now = loop.time()
                if service_enabled("customer-notifications") and now >= next_stock_scan:
                    await _queue_stock_alerts()
                    next_stock_scan = now + 60.0
                bot_ids = await _active_bot_ids() if service_enabled("customer-notifications") else []
                for bot_id in bot_ids:
                    if stop.is_set() or not service_enabled("customer-notifications"):
                        break
                    try:
                        async with _transport_for_bot(bot_id) as transport:
                            async with session_maker() as db:
                                await deliver_once(
                                    db, bot_id=bot_id, transport=transport,
                                )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        _logger.exception(
                            "Notification worker failed before a confirmed send; "
                            "inspect Outbox before retry. bot_id=%s",
                            bot_id,
                        )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=_POLL_SECONDS)
                except asyncio.TimeoutError:
                    pass
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
