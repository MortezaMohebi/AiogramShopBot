"""CLI entry point for one shared, durable Telegram/Bale broadcast worker.

Start only after database migration, merchant consent checks and a live
Bot API test have passed. This process never publishes web endpoints and
does not start interactive bot polling or Telegram webhooks.
"""

from __future__ import annotations

import asyncio
import logging
import signal


from db import create_db_and_tables, engine, session_maker
from services.shop_broadcast_worker import BroadcastWorker, registry_transport
from services.shop_service_controls import watch_controls

LOG = logging.getLogger(__name__)


async def main() -> None:
    """Open long-lived sessions and drain all explicitly started campaigns."""
    # Never let an old schema silently truncate paid budgets or recipient
    # receipts. The API process uses the same Alembic-head validation.
    await create_db_and_tables()
    # The dispatch path checks the current Registry gate for every campaign.
    runner = BroadcastWorker(registry_transport_factory=registry_transport)

    try:
        async with watch_controls(session_maker):
            task = asyncio.create_task(runner.run_forever(), name="shared-shop-broadcast")
            loop = asyncio.get_running_loop()
            try:
                # Cancelled in-flight sends are quarantined rather than repeated.
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.add_signal_handler(sig, task.cancel)
                await task
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(main())
