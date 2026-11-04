"""Opt-in digital entitlement dispatcher for confirmed Telegram/Bale payments.

No provider request runs unless SHOP_DIGITAL_DELIVERY_ENABLED=true.
The worker uses the original authenticated Bot's token and existing relay
selection. It never creates invoices, retries an uncertain file send or
mistakes a precheckout ACK for payment. Interrupted claims are quarantined.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from sqlalchemy import select

from db import create_db_and_tables, engine, session_maker
from models.shop_digital_delivery import ShopDigitalDelivery
from models.shop_multibot import ShopBot, ShopStore
from services.shop_digital_fulfillment import (
    deliver_one, quarantine_interrupted,
)
from workers.shop_customer_notifications import _transport_for_bot

LOGGER = logging.getLogger(__name__)
_LOOP_SECONDS = 5


async def _candidate_bots() -> list[str]:
    """List only active Stores with paid digital deliveries awaiting dispatch."""
    async with session_maker() as db:
        return list((await db.scalars(select(ShopBot.id).join(
            ShopDigitalDelivery,
            ShopDigitalDelivery.bot_id == ShopBot.id,
        ).join(
            ShopStore, ShopStore.id == ShopBot.store_id,
        ).where(
            ShopStore.state == "active",
            ShopDigitalDelivery.status == "queued",
            (
                (ShopBot.status == "legacy")
                & (ShopBot.runtime_owner == "legacy")
            ) | (
                (ShopBot.status == "active")
                & (ShopBot.runtime_owner == "registry")
            ),
        ).distinct().order_by(ShopBot.id).limit(100))).all())


async def _quarantine_orphans() -> None:
    """Never repeat an upload that could have succeeded before a crash."""
    async with session_maker() as db:
        ids = (await db.scalars(select(
            ShopDigitalDelivery.bot_id,
        ).where(
            ShopDigitalDelivery.status == "sending",
        ).distinct().limit(500))).all()
    for bot_id in ids:
        async with session_maker() as db:
            changed = await quarantine_interrupted(
                db, bot_id=bot_id,
            )
            if changed:
                LOGGER.warning(
                    "Quarantined %s interrupted paid delivery claims for bot %s.",
                    changed, bot_id,
                )


async def main() -> None:
    """Drain one paid delivery at a time per Bot with no provider retry."""
    if os.environ.get("SHOP_DIGITAL_DELIVERY_ENABLED") != "true":
        LOGGER.warning(
            "Paid digital delivery is disabled: no Bot API calls performed."
        )
        return
    await create_db_and_tables()
    await _quarantine_orphans()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        while not stop.is_set():
            for bot_id in await _candidate_bots():
                if stop.is_set():
                    break
                try:
                    # Uses the same approved Server-only per-Bot secret and
                    # Cloudflare relay selection as operational notifications.
                    async with _transport_for_bot(bot_id) as transport:
                        async with session_maker() as db:
                            await deliver_one(
                                db, bot_id=bot_id, transport=transport,
                            )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception(
                        "Digital delivery stopped; investigate pending "
                        "receipts before intervention. bot_id=%s", bot_id,
                    )
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=_LOOP_SECONDS,
                )
            except asyncio.TimeoutError:
                pass
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
