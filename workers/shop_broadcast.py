"""CLI entry point for one shared, durable Telegram/Bale broadcast worker.

Start only after database migration, merchant consent checks and a live
Bot API test have passed. This process never publishes web endpoints and
does not start interactive bot polling or Telegram webhooks.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from aiohttp import ClientSession, ClientTimeout

import config
from channels.telegram import TelegramTransport
from db import create_db_and_tables, engine
from services.shop_broadcast_worker import BroadcastWorker
from utils.telegram import create_bot, create_telegram_session
from utils.telegram_rotating_session import RotatingTelegramSession
from services.shop_telegram_transport_control import sync_broadcast_session


async def main() -> None:
    """Open long-lived sessions and drain all explicitly started campaigns."""
    if not (
        config.SHOP_BROADCAST_WORKER_ENABLED
        and config.SHOP_CAMPAIGN_DISPATCH_ENABLED
    ):
        logging.warning(
            "Broadcast worker is disabled by configuration; no messages sent."
        )
        return

    # Never let an old schema silently truncate paid budgets or recipient
    # receipts. The API process uses the same Alembic-head validation.
    await create_db_and_tables()
    telegram_bot = (
        create_bot(
            config.TOKEN,
            RotatingTelegramSession(create_telegram_session()),
        )
        if config.TOKEN else None
    )
    if telegram_bot is not None:
        # An authenticated getMe probe is required before the worker can
        # switch to a new committed proxy/Worker route.
        await sync_broadcast_session(telegram_bot)
    bale_session = (
        ClientSession(timeout=ClientTimeout(total=120))
        if config.BALE_BOT_TOKEN else None
    )
    runner = BroadcastWorker(
        telegram=(
            TelegramTransport(telegram_bot) if telegram_bot else None
        ),
        bale_session=bale_session,
        telegram_transport_sync=(
            (lambda: sync_broadcast_session(telegram_bot))
            if telegram_bot is not None else None
        ),
    )

    task = asyncio.create_task(
        runner.run_forever(), name="shared-shop-broadcast"
    )
    loop = asyncio.get_running_loop()
    try:
        # The runtime currently supports Linux Docker/Ubuntu; on shutdown
        # a cancelled in-flight send is quarantined rather than repeated.
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, task.cancel)
        await task
    finally:
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if bale_session is not None:
            await bale_session.close()
        if telegram_bot is not None:
            await telegram_bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(main())
