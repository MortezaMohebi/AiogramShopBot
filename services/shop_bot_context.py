"""Immutable BotContext for bot-scoped catalog, cart, payments, and events.

Creation must follow authentication of the inbound webhook route or verified
polling receiver. Do not derive a bot from a user-supplied platform string,
user ID, chat ID, callback payload, or a matching numeric customer ID.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import Platform
from models.shop_multibot import LEGACY_BOT_IDS, ShopBot, ShopStore
from services.shop_admin_security import SecurityRejected


@dataclass(frozen=True, slots=True)
class BotContext:
    """Verified bot identity and store scope, deliberately excluding secrets."""

    bot_id: str
    store_id: str
    platform: Platform
    provider_bot_id: int | None
    status: str
    runtime_owner: str
    credential_version: int | None
    registry_version: int

    def owner_key(self, platform_user_id: int) -> tuple[str, int]:
        """Return a bot-scoped key; never combine unrelated bot user records."""
        if type(platform_user_id) is not int or platform_user_id <= 0:
            raise ValueError("Platform user ID must be a positive integer")
        return self.bot_id, platform_user_id


async def resolve_bot_context(
    db: AsyncSession,
    *,
    authenticated_bot_id: str,
    authenticated_platform: Platform,
    authenticated_provider_bot_id: int | None = None,
) -> BotContext:
    """Resolve only a bot already authenticated by the transport boundary.

    The later receiver implementation must verify an opaque webhook binding
    or the polling job's registered token before calling this function.
    """
    bot = await db.scalar(select(ShopBot).where(
        ShopBot.id == authenticated_bot_id,
    ))
    if bot is None:
        raise SecurityRejected("bot_not_found", 404)
    if bot.platform != authenticated_platform.value:
        raise SecurityRejected("bot_identity_mismatch", 403)
    if authenticated_provider_bot_id is not None and (
        bot.provider_bot_id is None
        or bot.provider_bot_id != authenticated_provider_bot_id
    ):
        raise SecurityRejected("bot_identity_mismatch", 403)
    store = await db.get(ShopStore, bot.store_id)
    if store is None or store.state != "active":
        raise SecurityRejected("store_not_active", 409)
    if not (
        (bot.status == "legacy" and bot.runtime_owner == "legacy")
        or (bot.status == "active" and bot.runtime_owner == "registry")
    ):
        raise SecurityRejected("bot_not_active", 409)
    return BotContext(
        bot_id=bot.id,
        store_id=bot.store_id,
        platform=authenticated_platform,
        provider_bot_id=bot.provider_bot_id,
        status=bot.status,
        runtime_owner=bot.runtime_owner,
        credential_version=bot.credential_version,
        registry_version=bot.version,
    )


async def resolve_legacy_bot_context(
    db: AsyncSession, *, authenticated_platform: Platform,
) -> BotContext:
    """Bridge the two old receivers using immutable built-in bot IDs.

    This is an opt-in compatibility helper for later runtime migration;
    Phase 1 does not wire it into the existing update handlers.
    """
    bot_id = LEGACY_BOT_IDS.get(authenticated_platform.value)
    if bot_id is None:
        raise SecurityRejected("invalid_bot_platform", 422)
    result = await resolve_bot_context(
        db,
        authenticated_bot_id=bot_id,
        authenticated_platform=authenticated_platform,
    )
    if result.runtime_owner != "legacy":
        raise SecurityRejected("invalid_bot_runtime", 409)
    return result
