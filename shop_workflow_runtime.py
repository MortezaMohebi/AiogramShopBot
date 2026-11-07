"""Run shared Workflow workers with explicit deployment and per-tenant opt-in."""

from __future__ import annotations

import asyncio
import signal

from db import create_db_and_tables, session_maker
from services.shop_runtime.workers import run_workers
from services.shop_service_controls import watch_controls


async def main() -> None:
    """Verify schema before work; this process never enables a Store or customer Bot."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    signal_installed = False
    try:
        # Docker sends SIGTERM. Cooperative shutdown lets in-flight durable
        # receipts commit before this one shared queue drainer exits.
        try:
            loop.add_signal_handler(signal.SIGTERM, stop.set)
            signal_installed = True
        except NotImplementedError:
            # Windows development loops retain normal process termination.
            pass
        await create_db_and_tables()
        async with watch_controls(session_maker):
            await run_workers(session_maker, stop=stop)
    finally:
        if signal_installed:
            loop.remove_signal_handler(signal.SIGTERM)


if __name__ == "__main__":
    asyncio.run(main())
