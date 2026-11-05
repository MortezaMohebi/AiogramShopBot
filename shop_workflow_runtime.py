"""Run shared Workflow workers with explicit deployment and per-tenant opt-in."""

from __future__ import annotations

import asyncio
import logging

import config
from db import create_db_and_tables, session_maker
from services.shop_runtime.workers import run_workers


async def main() -> None:
    """Verify schema before work; this process never enables a Store or customer Bot."""
    if (
        not config.SHOP_WORKFLOW_RUNTIME_ENABLED
        or config.SHOP_WORKFLOW_RUNTIME_KILL_SWITCH
    ):
        logging.info("Workflow Runtime is disabled.")
        return
    await create_db_and_tables()
    await run_workers(session_maker)


if __name__ == "__main__":
    asyncio.run(main())
