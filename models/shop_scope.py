"""Explicit Registry ownership validation for shared commerce records.

Transport authentication supplies bot IDs. A platform name or numeric user
ID is never sufficient to select an owner for customer or financial data.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_multibot import ShopBot


def require_bot_id(bot_id: str | None) -> str:
    """Reject missing or malformed authenticated bot identifiers."""
    if (
        not isinstance(bot_id, str) or not bot_id.strip()
        or bot_id != bot_id.strip()
    ):
        raise ValueError("An explicit authenticated bot ID is required.")
    return bot_id


async def require_registry_bot(
    session: AsyncSession, bot_id: str | None, platform: str,
) -> ShopBot:
    """Validate Registry ownership without blocking receipt reconciliation.

    Active receiver authentication is enforced at the transport boundary.
    Paused or disabled bots must retain access to their existing settlements.
    """
    owner = require_bot_id(bot_id)
    bot = await session.get(ShopBot, owner)
    if (
        bot is None or bot.platform != platform
        or bot.runtime_owner != "registry"
    ):
        raise ValueError("Authenticated bot identity is invalid.")
    return bot
