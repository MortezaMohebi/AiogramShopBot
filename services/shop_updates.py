"""Idempotent receipt recording for provider webhook update identifiers.

A received update is claimed before any external send. Replayed updates are
never executed twice. A failed or interrupted delivery remains visible as
`needs_review` / `processing` for human reconciliation, not blind replay.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from channels.contracts import Platform
from models.shop_delivery import ShopInboundUpdate
from services.shop_media_delivery import bot_fingerprint


async def claim_update(
    *, platform: Platform, token: str, update_id: int,
    bot_id: str | None = None,
) -> tuple[bool, str]:
    """Claim a unique update for one bot and platform, safely under concurrency."""
    if type(update_id) is not int or update_id < 0:
        raise ValueError("Bot API update_id must be a nonnegative integer.")

    from db import session_maker

    fingerprint = bot_fingerprint(token)
    from models.shop_scope import legacy_id

    owner = bot_id or legacy_id(platform.value)
    scope = (
        ShopInboundUpdate.platform == platform.value,
        ShopInboundUpdate.bot_fingerprint == fingerprint,
        ShopInboundUpdate.update_id == update_id,
    )
    async with session_maker() as session:
        existing = await session.scalar(
            select(ShopInboundUpdate.status).where(*scope)
        )
        if existing is not None:
            return False, existing
        try:
            async with session.begin_nested():
                session.add(
                    ShopInboundUpdate(
                        bot_id=owner,
                        platform=platform.value,
                        bot_fingerprint=fingerprint,
                        update_id=update_id,
                        status="processing",
                    )
                )
                await session.flush()
        except IntegrityError:
            # Simultaneous delivery of one update must not spawn two handlers.
            status = await session.scalar(
                select(ShopInboundUpdate.status).where(*scope)
            )
            return False, status or "processing"
        await session.commit()
        return True, "processing"


async def finish_update(
    *,
    platform: Platform,
    token: str,
    update_id: int,
    success: bool,
    bot_id: str | None = None,
) -> None:
    """Mark a claimed update processed or pending manual investigation."""
    from db import session_maker

    fingerprint = bot_fingerprint(token)
    from models.shop_scope import legacy_id

    owner = bot_id or legacy_id(platform.value)
    async with session_maker() as session:
        entry = await session.scalar(
            select(ShopInboundUpdate).where(
                ShopInboundUpdate.bot_id == owner,
                ShopInboundUpdate.platform == platform.value,
                ShopInboundUpdate.bot_fingerprint == fingerprint,
                ShopInboundUpdate.update_id == update_id,
            ).with_for_update()
        )
        if entry is None:
            raise RuntimeError("Unclaimed webhook update cannot be finalized.")
        if entry.status != "processing":
            return
        entry.status = "processed" if success else "needs_review"
        entry.completed_at = datetime.now(timezone.utc)
        await session.commit()
