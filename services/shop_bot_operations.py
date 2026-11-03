"""Per-bot operational settings with optimistic locking and fail-closed state.

Legacy receivers keep handling payment confirmations while ordinary shopping,
callbacks and outbound broadcasts obey the requested state. New draft bots
cannot be activated until the later isolated multi-bot runtime is accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_bot_operations import ShopBotOperations
from models.shop_bot_profile import ShopBotProfile
from models.shop_multibot import LEGACY_BOT_IDS, ShopBot, ShopBotRegistryEvent
from models.shop_staff import ShopStaff
from services import shop_admin_security as security

OPERATING_STATES = frozenset({"active", "maintenance", "paused", "disabled"})
DEFAULT_MAINTENANCE = "فروشگاه موقتاً در حال نگهداری است. لطفاً بعداً مراجعه کنید."
DEFAULT_PAUSED = "خدمات این ربات موقتاً متوقف شده است. لطفاً بعداً مراجعه کنید."
_OPS_TITLES = {
    "active": "فعال",
    "maintenance": "حالت نگهداری",
    "paused": "متوقف",
    "disabled": "غیرفعال",
}


@dataclass(frozen=True, slots=True)
class EffectiveBotState:
    """Immutable state used by the actual legacy receiver and broadcast gates."""

    bot_id: str
    state: str
    message: str
    runtime_ready: bool


def _public_https_url(value: str) -> str:
    """Accept an optional public HTTPS support link without URL credentials."""
    raw = value.strip()
    if not raw:
        return ""
    if len(raw) > 500:
        raise security.SecurityRejected("invalid_support_url", 422)
    try:
        url = urlsplit(raw)
        host = url.hostname
        port = url.port
    except ValueError:
        raise security.SecurityRejected("invalid_support_url", 422) from None
    if (
        url.scheme != "https" or not host
        or url.username is not None or url.password is not None
        or port not in (None, 443)
        or url.fragment
        or host == "localhost" or host.endswith((".local", ".internal"))
    ):
        raise security.SecurityRejected("invalid_support_url", 422)
    return raw


def _message(text: str | None, limit: int = 4096) -> str | None:
    """Bound and sanitize an optional public-facing message."""
    if text is None or not text.strip():
        return None
    clean = text.strip()
    if len(clean) > limit or any(
        ord(char) < 32 and char not in ("\n", "\t") for char in clean
    ):
        raise security.SecurityRejected("invalid_request", 422)
    return clean


def _get_or_add(db: Session, bot: ShopBot) -> ShopBotOperations:
    """Return locked policy or create its safe per-bot default."""
    row = db.scalar(select(ShopBotOperations).where(
        ShopBotOperations.bot_id == bot.id,
    ).with_for_update())
    if row is not None:
        return row
    inherited = db.get(ShopBotProfile, bot.platform) if (
        bot.runtime_owner == "legacy"
    ) else None
    row = ShopBotOperations(
        bot_id=bot.id,
        desired_state=(
            "maintenance" if inherited and inherited.maintenance_enabled
            else "active" if bot.runtime_owner == "legacy"
            else "disabled"
        ),
        environment=inherited.environment if inherited else "staging",
        owner_staff_id=inherited.owner_staff_id if inherited else None,
    )
    db.add(row)
    db.flush()
    return row


def update_details(
    db: Session, *, bot_id: str, actor_id: int, expected_version: int,
    name: str, owner_staff_id: int | None, environment: str,
    welcome_message: str | None, maintenance_message: str | None,
    support_url: str,
) -> None:
    """Edit public profile and private ownership, never a provider identity."""
    from services.shop_bot_registry import _safe_name

    bot = db.scalar(select(ShopBot).where(
        ShopBot.id == bot_id,
    ).with_for_update())
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    if bot.version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)
    if environment not in {"codespaces", "staging", "production"}:
        raise security.SecurityRejected("invalid_request", 422)
    if owner_staff_id is not None:
        owner = db.get(ShopStaff, owner_staff_id)
        if owner is None or not owner.is_active:
            raise security.SecurityRejected("staff_not_found", 404)
    ops = _get_or_add(db, bot)
    bot.name = _safe_name(name)
    ops.owner_staff_id = owner_staff_id
    ops.environment = environment
    ops.welcome_message = _message(welcome_message)
    ops.maintenance_message = _message(maintenance_message)
    ops.support_url = _public_https_url(support_url) or None
    ops.updated_by = actor_id
    bot.version += 1
    db.add(ShopBotRegistryEvent(
        id=str(uuid4()), bot_id=bot.id,
        actor_id=actor_id, action="bot_updated",
    ))
    security.audit(db, actor_id, "bots.profile_updated", bot.id)


def change_state(
    db: Session, *, bot_id: str, actor_id: int,
    expected_version: int, state: str, reason: str,
) -> str:
    """Apply an immediate legacy shopping gate without stopping receivers.

    The current Telegram/Bale runtime is shared and cannot serve registry-
    owned bots. Such bots stay disabled until an isolated dispatcher exists.
    """
    if state not in OPERATING_STATES:
        raise security.SecurityRejected("invalid_bot_state", 422)
    bot = db.scalar(select(ShopBot).where(
        ShopBot.id == bot_id,
    ).with_for_update())
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    if bot.version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)
    if bot.runtime_owner != "legacy" or bot.status != "legacy":
        raise security.SecurityRejected("bot_runtime_not_ready", 409)
    cleaned_reason = reason.strip()
    if state in {"paused", "disabled"} and not 8 <= len(cleaned_reason) <= 500:
        raise security.SecurityRejected("bot_state_reason_required", 422)
    ops = _get_or_add(db, bot)
    if ops.desired_state == state:
        raise security.SecurityRejected("bot_state_unchanged", 409)

    ops.desired_state = state
    ops.reason = cleaned_reason if state != "active" else None
    ops.updated_by = actor_id
    # Other legacy management screens must see an identical maintenance
    # status, otherwise they could silently overrule the new bot registry.
    inherited = db.get(ShopBotProfile, bot.platform)
    if inherited is not None:
        inherited.maintenance_enabled = state == "maintenance"
    bot.version += 1
    db.add(ShopBotRegistryEvent(
        id=str(uuid4()), bot_id=bot.id,
        actor_id=actor_id, action="bot_updated",
    ))
    security.audit(db, actor_id, "bots.state_changed", bot.id)
    return state


async def legacy_state(db: AsyncSession, platform: str) -> EffectiveBotState:
    """Resolve the effective real-time gate for one original provider bot."""
    bot_id = LEGACY_BOT_IDS.get(platform)
    if bot_id is None:
        raise security.SecurityRejected("invalid_bot_platform", 422)
    ops = await db.get(ShopBotOperations, bot_id)
    if ops is None:
        previous = await db.get(ShopBotProfile, platform)
        state = (
            "maintenance" if previous and previous.maintenance_enabled
            else "active"
        )
        message = DEFAULT_MAINTENANCE
    else:
        state = ops.desired_state
        message = (
            ops.maintenance_message
            if ops.maintenance_message and state == "maintenance"
            else DEFAULT_PAUSED if state == "paused"
            else DEFAULT_MAINTENANCE
        )
    if state not in OPERATING_STATES:
        raise security.SecurityRejected("invalid_bot_state", 503)
    return EffectiveBotState(
        bot_id=bot_id, state=state, message=message,
        runtime_ready=True,
    )


def operation_data(db: Session, bot: ShopBot) -> dict:
    """Display the actual operational gate, not a guessed provider online state."""
    ops = db.get(ShopBotOperations, bot.id)
    if ops is None:
        profile = db.get(ShopBotProfile, bot.platform) if (
            bot.runtime_owner == "legacy"
        ) else None
        state = (
            "maintenance" if profile and profile.maintenance_enabled
            else "active" if bot.runtime_owner == "legacy"
            else "disabled"
        )
    else:
        state = ops.desired_state
    return {
        "desired_state": state,
        "state_label": _OPS_TITLES[state],
        "runtime_ready": bot.runtime_owner == "legacy",
        "welcome_message": ops.welcome_message if ops else None,
        "maintenance_message": ops.maintenance_message if ops else None,
        "support_url": ops.support_url if ops else None,
        "owner_staff_id": ops.owner_staff_id if ops else None,
        "environment": ops.environment if ops else "staging",
        "reason": ops.reason if ops else None,
        "updated_at": (
            ops.updated_at.isoformat() if ops and ops.updated_at else None
        ),
    }
