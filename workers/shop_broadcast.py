"""CLI entry point for one shared, durable Telegram/Bale broadcast worker.

Start only after database migration, merchant consent checks and a live
Bot API test have passed. This process never publishes web endpoints and
does not start interactive bot polling or Telegram webhooks.
"""

from __future__ import annotations

import asyncio
import logging
import signal


import config
from db import create_db_and_tables, engine
from services.shop_broadcast_scope import registry_dispatch_enabled
from services.shop_broadcast_worker import BroadcastWorker, registry_transport

LOG = logging.getLogger(__name__)


async def main() -> None:
    """Open long-lived sessions and drain all explicitly started campaigns."""
    if not (
        config.SHOP_BROADCAST_WORKER_ENABLED and config.SHOP_CAMPAIGN_DISPATCH_ENABLED
    ):
        LOG.warning("Broadcast worker is disabled by configuration; no messages sent.")
        return

    # Never let an old schema silently truncate paid budgets or recipient
    # receipts. The API process uses the same Alembic-head validation.
    await create_db_and_tables()
    runner = BroadcastWorker(
        registry_transport_factory=(
            registry_transport if registry_dispatch_enabled() else None
        ),
    )

    task = asyncio.create_task(runner.run_forever(), name="shared-shop-broadcast")
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
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(main())
