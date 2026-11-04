"""PostgreSQL-backed broadcast send pacing shared by worker instances.

Every outgoing text or media send reserves a bot-wide and per-recipient slot.
Reservations commit before network I/O, so restarts and extra worker processes
cannot exceed the configured channel limits. A reserved but unsent slot is
conservatively considered consumed; it is never reclaimed by guessing.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

import config
from channels.contracts import Platform
from models.shop_engagement import ShopBroadcastRateSlot
from models.shop_scope import legacy_id
from services.shop_media_delivery import bot_fingerprint


def channel_rate(platform: Platform, *, bale_mode: str) -> int:
    """Select an explicit safe cap for the actual platform API in use."""
    if platform == Platform.TELEGRAM:
        return config.SHOP_BROADCAST_TELEGRAM_MPS
    if platform == Platform.BALE and bale_mode == "business":
        return config.SHOP_BROADCAST_BALE_BUSINESS_MPS
    if platform == Platform.BALE and bale_mode == "standard":
        return config.SHOP_BROADCAST_BALE_STANDARD_MPS
    raise ValueError("Unsupported broadcast channel or Bale mode.")


def slot_intervals(rate: int) -> tuple[timedelta, timedelta]:
    """Return safe global and per-private-chat intervals, rounded upward."""
    if type(rate) is not int or not 1 <= rate <= 20:
        raise ValueError("Broadcast rate is outside its safe range.")
    global_gap = timedelta(microseconds=(1_000_000 + rate - 1) // rate)
    # Telegram recommends no more than one message/s to an individual chat.
    # The same conservative limit is applied to Bale.
    return global_gap, timedelta(seconds=1)


async def reserve_message_slot(
    *,
    platform: Platform,
    token: str,
    user_id: int,
    bale_mode: str,
    bot_id: str | None = None,
) -> None:
    """Reserve and wait for one safe Bot API message time.

    PostgreSQL `INSERT .. ON CONFLICT DO NOTHING` plus `FOR UPDATE` locks
    serialize reservations across multiple processes and campaigns.
    """
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("Broadcast target must be a positive private ID.")
    from db import session_maker

    fingerprint = bot_fingerprint(token)
    owner_id = bot_id or legacy_id(platform.value)
    gap_global, gap_chat = slot_intervals(channel_rate(platform, bale_mode=bale_mode))
    async with session_maker() as session:
        # Insert both rows first, always ordering by recipient ID to avoid
        # circular lock attempts when multiple worker processes compete.
        for scope_id in (0, user_id):
            stmt = insert(ShopBroadcastRateSlot).values(
                platform=platform.value,
                bot_id=owner_id,
                bot_fingerprint=fingerprint,
                recipient_id=scope_id,
                next_send_at=datetime.now(UTC),
            )
            await session.execute(
                stmt.on_conflict_do_nothing(constraint="uq_shop_broadcast_rate_slot")
            )
        result = await session.execute(
            select(ShopBroadcastRateSlot)
            .where(
                ShopBroadcastRateSlot.platform == platform.value,
                ShopBroadcastRateSlot.bot_id == owner_id,
                ShopBroadcastRateSlot.bot_fingerprint == fingerprint,
                ShopBroadcastRateSlot.recipient_id.in_((0, user_id)),
            )
            .order_by(ShopBroadcastRateSlot.recipient_id)
            .with_for_update()
        )
        slots = {slot.recipient_id: slot for slot in result.scalars().all()}
        if len(slots) != 2:
            raise RuntimeError("Broadcast pacing rows are unavailable.")

        now = await session.scalar(select(func.clock_timestamp()))
        if now is None:
            raise RuntimeError("Database time is unavailable.")
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        start = max(
            now,
            slots[0].next_send_at,
            slots[user_id].next_send_at,
        )
        slots[0].next_send_at = start + gap_global
        slots[user_id].next_send_at = start + gap_chat
        await session.commit()

    delay = max(0.0, (start - now).total_seconds())
    if delay:
        await asyncio.sleep(delay)
