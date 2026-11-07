"""Opt-in worker for verified paid, private Telegram/Bale digital goods.

Never contacts Provider before the durable delivery is marked 'sending'.
A transport error or a process crash cannot silently replay a license.
The worker does not modify financial settlement or publish digital assets.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from sqlalchemy import select

from db import create_db_and_tables, engine, session_maker
from models.shop_digital_delivery import ShopDigitalDelivery
from models.shop_multibot import ShopBot, ShopStore
from services.shop_digital_fulfillment import (
    claim_one_delivery, complete_delivery, quarantine_delivery,
)
from services.shop_service_controls import service_enabled, watch_controls
from workers.shop_customer_notifications import _transport_for_bot

_logger = logging.getLogger(__name__)


async def _pending_bot_ids() -> list[str]:
    """Bound active Bot selection to queued paid-delivery work only."""
    async with session_maker() as db:
        result = await db.scalars(select(ShopBot.id).join(
            ShopDigitalDelivery,
            ShopDigitalDelivery.bot_id == ShopBot.id,
        ).join(
            ShopStore, ShopStore.id == ShopBot.store_id,
        ).where(
            ShopDigitalDelivery.state == "queued",
            ShopDigitalDelivery.store_id == ShopBot.store_id,
            ShopStore.state == "active",
            ShopBot.runtime_owner == "registry",
            ShopBot.status == "active",
        ).distinct().order_by(ShopBot.id).limit(50))
        return list(result.all())


async def _deliver_one(bot_id: str) -> bool:
    """Attempt at most one external send, never retry an uncertain receipt."""
    async with session_maker() as db:
        item = await claim_one_delivery(db, bot_id=bot_id)
    if item is None:
        return False
    try:
        async with _transport_for_bot(bot_id) as transport:
            provider_message_id = await transport.deliver_digital(item)
    except asyncio.CancelledError:
        # A cancelled in-flight task may still have delivered. Do not
        # unclaim 'sending' on shutdown; leave it for explicit review.
        raise
    except Exception:
        _logger.warning(
            "Digital Provider outcome unknown for delivery_id=%s; quarantined.",
            item.delivery_id,
        )
        async with session_maker() as db:
            await quarantine_delivery(
                db, delivery_id=item.delivery_id,
                failure_code="provider_outcome_unknown",
            )
        return True
    try:
        async with session_maker() as db:
            await complete_delivery(
                db, delivery_id=item.delivery_id,
                provider_message_id=provider_message_id,
            )
    except Exception:
        # The Provider may have sent successfully. The durable 'sending'
        # claim prevents automatic replay after DB or receipt error.
        _logger.exception(
            "Delivered asset needs manual receipt reconciliation: delivery_id=%s",
            item.delivery_id,
        )
    return True


async def main() -> None:
    """Poll only after an operator explicitly enables verified digital delivery."""
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
            while not stop.is_set():
                bot_ids = await _pending_bot_ids() if service_enabled("digital-delivery") else []
                for bot_id in bot_ids:
                    if stop.is_set() or not service_enabled("digital-delivery"):
                        break
                    try:
                        await _deliver_one(bot_id)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        _logger.exception(
                            "Digital fulfillment worker stopped an unsafe attempt for Bot %s.",
                            bot_id,
                        )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
