"""Store/Bot checkout policy and official platform payment invariants.

Telegram digital products/services inside bots must use Stars (XTR). An IRR
internal merchant credit wallet cannot bypass the platform payment rule.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import Platform
from models.shop_checkout_policy import ShopBotCheckoutPolicy, ShopStoreCheckoutPolicy
from models.shop_multibot import ShopBot, ShopStore
from utils.shop_text import clean_text
from services import shop_admin_security as security


@dataclass(frozen=True, slots=True)
class CheckoutRules:
    """The effective Store-approved checkout mode and sales terms."""

    store_id: str
    bot_id: str
    mode: str
    terms_version: str
    terms_text: str
    policy_token: str


def decide_checkout_mode(
    store_policy: ShopStoreCheckoutPolicy | None,
    bot_policy: ShopBotCheckoutPolicy | None,
) -> str:
    """Default to manual approval unless explicitly overridden."""
    if bot_policy is not None and bot_policy.mode_override in {
        "manual", "instant",
    }:
        return bot_policy.mode_override
    if store_policy is not None and store_policy.mode == "instant":
        return "instant"
    return "manual"


def terms_configured(policy: ShopStoreCheckoutPolicy | None) -> bool:
    """Confirm that a dated, bounded customer terms document is available."""
    return bool(
        policy is not None
        and isinstance(policy.terms_version, str)
        and 1 <= len(policy.terms_version) <= 32
        and isinstance(policy.terms_text, str)
        and 12 <= len(policy.terms_text.strip()) <= 6000
    )


def legal_credit_for_items(
    platform: Platform, types: set[str],
) -> bool:
    """Allow only fulfillable orders and honor Telegram's Stars-only digital rule."""
    return (
        bool(types)
        and types <= {"physical", "digital"}
        and len(types) == 1
        and not (
            platform == Platform.TELEGRAM
            and "digital" in types
        )
    )


async def checkout_rules(
    db: AsyncSession, *, bot_id: str,
) -> CheckoutRules:
    """Read verified Bot ownership and its Store's immutable policy values."""
    bot = await db.get(ShopBot, bot_id)
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    store = await db.get(ShopStore, bot.store_id)
    if store is None or store.state != "active":
        raise security.SecurityRejected("store_not_active", 409)
    default = await db.get(ShopStoreCheckoutPolicy, store.id)
    override = await db.get(ShopBotCheckoutPolicy, bot.id)
    if override is not None and override.store_id != store.id:
        raise security.SecurityRejected("checkout_store_mismatch", 409)
    mode = decide_checkout_mode(default, override)
    terms_version = default.terms_version if default else ""
    terms_text = default.terms_text.strip() if default else ""
    # Short fingerprint prevents stale Callback buttons from accepting a
    # later edition of sales terms or a changed Store/Bot checkout policy.
    digest = hashlib.sha256((
        f"{store.id}:{bot.id}:{default.version if default else 0}:"
        f"{override.version if override else 0}:{mode}:"
        f"{terms_version}:{terms_text}"
    ).encode("utf-8")).hexdigest()[:12]
    return CheckoutRules(
        store_id=store.id, bot_id=bot.id,
        mode=mode, terms_version=terms_version,
        terms_text=terms_text, policy_token=digest,
    )


async def checkout_policy_snapshot(
    db: AsyncSession, *, store_id: str,
    bot_id: str | None = None,
) -> dict:
    """Expose non-secret Store/optional Bot terms and approval settings."""
    store = await db.get(ShopStore, store_id)
    if store is None:
        raise security.SecurityRejected("store_not_found", 404)
    default = await db.get(ShopStoreCheckoutPolicy, store_id)
    bot_policy = None
    if bot_id is not None:
        bot = await db.get(ShopBot, bot_id)
        if bot is None or bot.store_id != store_id:
            raise security.SecurityRejected("checkout_store_mismatch", 409)
        bot_policy = await db.get(ShopBotCheckoutPolicy, bot_id)
    return {
        "store_id": store_id, "bot_id": bot_id,
        "version": bot_policy.version if bot_id and bot_policy else
                   default.version if default else 0,
        "mode": decide_checkout_mode(default, bot_policy),
        "mode_override": bot_policy.mode_override if bot_policy else None,
        "terms_version": default.terms_version if default else "v1",
        "terms_text": default.terms_text if default else "",
        "terms_ready": terms_configured(default),
    }


async def save_store_checkout(
    db: AsyncSession, *, store_id: str, actor_id: int,
    expected_version: int, mode: str, terms_version: str, terms_text: str,
) -> dict:
    """Update merchant checkout rules after version and terms validation."""
    terms_text = clean_text(terms_text, multiline=True)
    if (
        mode not in {"manual", "instant"}
        or not 1 <= len(terms_version) <= 32
        or len(terms_text) > 6000
        or (mode == "instant" and len(terms_text) < 12)
    ):
        raise security.SecurityRejected("invalid_checkout_policy", 422)
    row = await db.scalar(select(ShopStoreCheckoutPolicy).where(
        ShopStoreCheckoutPolicy.store_id == store_id,
    ).with_for_update())
    if row is None:
        if expected_version != 0:
            raise security.SecurityRejected("configuration_changed", 409)
        if await db.get(ShopStore, store_id) is None:
            raise security.SecurityRejected("store_not_found", 404)
        row = ShopStoreCheckoutPolicy(store_id=store_id)
        db.add(row)
    elif row.version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)
    row.mode = mode
    row.terms_version = terms_version.strip()
    row.terms_text = terms_text
    row.version = row.version + 1 if expected_version else 1
    row.updated_by = actor_id
    await db.commit()
    return await checkout_policy_snapshot(db, store_id=store_id)


async def save_bot_checkout(
    db: AsyncSession, *, bot_id: str, actor_id: int,
    expected_version: int, mode_override: str | None,
) -> dict:
    """Override only this bot's approval mode; terms remain Store-owned."""
    if mode_override not in {"instant", "manual", None}:
        raise security.SecurityRejected("invalid_checkout_policy", 422)
    bot = await db.get(ShopBot, bot_id)
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    policy = await db.scalar(select(ShopBotCheckoutPolicy).where(
        ShopBotCheckoutPolicy.bot_id == bot_id,
    ).with_for_update())
    if policy is None:
        if expected_version != 0:
            raise security.SecurityRejected("configuration_changed", 409)
        policy = ShopBotCheckoutPolicy(
            bot_id=bot.id, store_id=bot.store_id,
        )
        db.add(policy)
    elif policy.version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)
    store_policy = await db.get(ShopStoreCheckoutPolicy, bot.store_id)
    if mode_override == "instant" and not terms_configured(store_policy):
        raise security.SecurityRejected("checkout_terms_required", 409)
    policy.mode_override = mode_override
    policy.version = policy.version + 1 if expected_version else 1
    policy.updated_by = actor_id
    await db.commit()
    return await checkout_policy_snapshot(
        db, store_id=bot.store_id, bot_id=bot.id,
    )
