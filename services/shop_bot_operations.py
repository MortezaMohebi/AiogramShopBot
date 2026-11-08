"""Per-bot operational settings with optimistic locking and fail-closed state.

Authenticated receivers keep processing payment confirmations while shopping,
callbacks and outbound broadcasts obey each registered bot’s operational state.
"""

from __future__ import annotations

from ipaddress import ip_address
import re
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.shop_bot_operations import ShopBotOperations, ShopBotOperationsEvent
from models.shop_multibot import ShopBot, ShopBotRegistryEvent
from models.shop_multibot_receiver import ShopBotReceiver
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from utils.shop_text import clean_text

OPERATING_STATES = frozenset({"active", "maintenance", "paused", "disabled"})
_OPS_TITLES = {
    "active": "فعال",
    "maintenance": "حالت نگهداری",
    "paused": "متوقف",
    "disabled": "غیرفعال",
}


def public_https_url(value: str) -> str:
    """Accept an optional public HTTPS support link without URL credentials."""
    raw = value.strip()
    if not raw:
        return ""
    if len(raw) > 500 or "\\" in raw or any(
        char.isspace() or not char.isprintable() for char in raw
    ):
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
        or host == "localhost"
        or host.endswith((".local", ".internal", ".test", ".invalid"))
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,251}[a-z0-9]", host)
        or ".." in host or "." not in host
    ):
        raise security.SecurityRejected("invalid_support_url", 422)
    try:
        address = ip_address(host)
    except ValueError:
        # Non-IP hostnames were validated above; no network request is sent.
        address = None
    # Browsers may reinterpret abbreviated or non-decimal numeric hosts.
    numeric_suffix = re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", host.rsplit(".", 1)[-1])
    if (address is None and numeric_suffix) or (address is not None and not address.is_global):
        raise security.SecurityRejected("invalid_support_url", 422)
    return raw


def _message(text: str | None, limit: int = 4096) -> str | None:
    """Bound and sanitize an optional public-facing message."""
    if text is None or not text.strip():
        return None
    clean = clean_text(text, multiline=True)
    if len(clean) > limit:
        raise security.SecurityRejected("invalid_request", 422)
    return clean or None


def _get_or_add(db: Session, bot: ShopBot) -> ShopBotOperations:
    """Return locked policy or create its safe per-bot default."""
    row = db.scalar(select(ShopBotOperations).where(
        ShopBotOperations.bot_id == bot.id,
    ).with_for_update())
    if row is not None:
        return row
    row = ShopBotOperations(
        bot_id=bot.id, desired_state="disabled", environment="staging",
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
    if environment not in {"staging", "production"}:
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
    ops.support_url = public_https_url(support_url) or None
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
    """Apply the registered bot's storefront gate without stopping settlement."""
    if state not in OPERATING_STATES:
        raise security.SecurityRejected("invalid_bot_state", 422)
    bot = db.scalar(select(ShopBot).where(
        ShopBot.id == bot_id,
    ).with_for_update())
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    if bot.version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)
    receiver = db.get(ShopBotReceiver, bot.id)
    if not (
        bot.runtime_owner == "registry"
        and bot.status in OPERATING_STATES
        and bot.credential_version is not None
        and receiver is not None and receiver.state == "active"
    ):
        raise security.SecurityRejected("bot_runtime_not_ready", 409)
    cleaned_reason = reason.strip()
    if state in {"paused", "disabled"} and not 8 <= len(cleaned_reason) <= 500:
        raise security.SecurityRejected("bot_state_reason_required", 422)
    ops = _get_or_add(db, bot)
    if ops.desired_state == state:
        raise security.SecurityRejected("bot_state_unchanged", 409)

    previous_state = ops.desired_state
    ops.desired_state = state
    ops.reason = cleaned_reason if state != "active" else None
    db.add(ShopBotOperationsEvent(
        id=str(uuid4()), bot_id=bot.id, actor_id=actor_id,
        previous_state=previous_state, next_state=state,
        reason=cleaned_reason or None,
    ))
    ops.updated_by = actor_id
    # Keep the authenticated receiver alive for settlement and after-sale help.
    bot.status = state
    bot.version += 1
    db.add(ShopBotRegistryEvent(
        id=str(uuid4()), bot_id=bot.id,
        actor_id=actor_id, action="bot_updated",
    ))
    security.audit(db, actor_id, "bots.state_changed", bot.id)
    return state


def operation_data(db: Session, bot: ShopBot) -> dict:
    """Display the actual operational gate, not a guessed provider online state."""
    ops = db.get(ShopBotOperations, bot.id)
    state = ops.desired_state if ops is not None else "disabled"
    receiver = db.get(ShopBotReceiver, bot.id)
    return {
        "desired_state": state,
        "state_label": _OPS_TITLES[state],
        "runtime_ready": (
            bot.runtime_owner == "registry"
            and bot.credential_version is not None
            and receiver is not None
            and receiver.state == "active"
        ),
        "welcome_message": ops.welcome_message if ops else None,
        "maintenance_message": ops.maintenance_message if ops else None,
        "support_url": ops.support_url if ops else None,
        "owner_staff_id": ops.owner_staff_id if ops else None,
        "environment": "production" if ops and ops.environment == "production" else "staging",
        "reason": ops.reason if ops else None,
        "updated_at": (
            ops.updated_at.isoformat() if ops and ops.updated_at else None
        ),
    }
