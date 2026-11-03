"""Validated Telegram/Bale bot settings and stable provider identity.

Only the currently configured provider credential may verify its identity.
Maintenance mode can be switched without webhook registration or token rotation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_bot_profile import ShopBotProfile

SUPPORTED_UPDATES = frozenset({
    "message", "callback_query", "pre_checkout_query",
    "edited_message", "my_chat_member",
})
SUPPORTED_PLATFORMS = ("telegram", "bale")


@dataclass(frozen=True, slots=True)
class BotOptions:
    """Current effective receiver and maintenance policy for one provider."""

    platform: str
    display_name: str
    owner_staff_id: int | None
    environment: str
    provider_bot_id: int | None
    provider_username: str | None
    maintenance_enabled: bool
    request_timeout_seconds: int
    poll_timeout_seconds: int
    allowed_updates: tuple[str, ...]
    verified_at: datetime | None


def validate_allowed_updates(value: list[str]) -> tuple[str, ...]:
    """Reject unknown or duplicated update names rather than dropping them."""
    if not isinstance(value, list) or len(value) > len(SUPPORTED_UPDATES):
        raise ValueError("Invalid allowed updates")
    if len(set(value)) != len(value) or not set(value) <= SUPPORTED_UPDATES:
        raise ValueError("Invalid allowed updates")
    return tuple(sorted(value))


async def get_bot_options(db: AsyncSession, platform: str) -> BotOptions:
    """Load a bot policy; missing records preserve operational defaults."""
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError("Unknown bot provider")
    row = await db.get(ShopBotProfile, platform)
    if row is None:
        return BotOptions(
            platform=platform, display_name="", owner_staff_id=None,
            environment="staging", provider_bot_id=None,
            provider_username=None, maintenance_enabled=False,
            request_timeout_seconds=15, poll_timeout_seconds=10,
            allowed_updates=(), verified_at=None,
        )
    try:
        updates = validate_allowed_updates(json.loads(row.allowed_updates_json))
    except (TypeError, ValueError):
        # A corrupt policy must never silently expand an explicit filter.
        raise ValueError("Corrupt provider allowed_updates policy") from None
    return BotOptions(
        platform=row.platform,
        display_name=row.display_name,
        owner_staff_id=row.owner_staff_id,
        environment=row.environment,
        provider_bot_id=row.provider_bot_id,
        provider_username=row.provider_username,
        maintenance_enabled=row.maintenance_enabled,
        request_timeout_seconds=row.request_timeout_seconds,
        poll_timeout_seconds=row.poll_timeout_seconds,
        allowed_updates=updates,
        verified_at=row.verified_at,
    )


def safe_data(options: BotOptions) -> dict:
    """Expose non-secret receiver configuration for the management dashboard."""
    return {
        "platform": options.platform,
        "display_name": options.display_name,
        "owner_staff_id": options.owner_staff_id,
        "environment": options.environment,
        "provider_bot_id": str(options.provider_bot_id) if options.provider_bot_id else None,
        "provider_username": options.provider_username,
        "maintenance_enabled": options.maintenance_enabled,
        "request_timeout_seconds": options.request_timeout_seconds,
        "poll_timeout_seconds": options.poll_timeout_seconds,
        "allowed_updates": list(options.allowed_updates),
        "verified_at": options.verified_at.isoformat() if options.verified_at else None,
    }
