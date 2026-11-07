"""Run shared Workflow workers with explicit deployment and per-tenant opt-in."""

from __future__ import annotations

import asyncio
import logging
import signal

import config
from db import create_db_and_tables, session_maker
from services.shop_runtime.workers import run_workers


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
        if (
            not config.SHOP_WORKFLOW_RUNTIME_ENABLED
            or config.SHOP_WORKFLOW_RUNTIME_KILL_SWITCH
        ):
            logging.info("Workflow Runtime is disabled; shared worker is idle.")
            await stop.wait()
            return
        await create_db_and_tables()
        await run_workers(session_maker, stop=stop)
    finally:
        if signal_installed:
            loop.remove_signal_handler(signal.SIGTERM)


if __name__ == "__main__":
    asyncio.run(main())
