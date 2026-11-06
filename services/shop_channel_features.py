"""Effective channel capabilities with independent per-bot policy overrides.

Registered bots default to DENY until an authorized operator configures
each feature in the bot's registry; platform-wide flags never grant access.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_scope import require_registry_bot
from models.shop_store_commerce import ShopBotCommercePolicy

PLATFORMS = ("telegram", "bale")


@dataclass(frozen=True, slots=True)
class ChannelFeatures:
    """Effective, authenticated Bot API feature settings."""

    platform: str
    cart_enabled: bool
    store_credit_enabled: bool
    store_credit_label: str


async def get_features(
    session: AsyncSession, platform: str, *,
    bot_id: str | None = None,
) -> ChannelFeatures:
    """Require authenticated Registry ownership and explicit feature grants."""
    if platform not in PLATFORMS:
        raise ValueError("Unsupported provider")
    bot = await require_registry_bot(session, bot_id, platform)
    policy = await session.get(ShopBotCommercePolicy, bot.id)
    cart = False
    credit = False
    label = "اعتبار فروشگاه"
    if policy:
        if policy.cart_enabled is not None:
            cart = policy.cart_enabled
        if policy.credit_enabled is not None:
            credit = policy.credit_enabled
        if policy.credit_label:
            label = policy.credit_label
    return ChannelFeatures(
        platform=platform,
        cart_enabled=cart,
        store_credit_enabled=credit,
        store_credit_label=label,
    )


def inline_credit_label(features: ChannelFeatures) -> str:
    """Truncate a UTF-8 label to the platform's callback display budget."""
    label = features.store_credit_label.strip()
    while len(label.encode("utf-8")) > 64:
        label = label[:-1]
    return label or "اعتبار فروشگاه"


def to_data(features: ChannelFeatures) -> dict:
    """Serialize only client-safe, non-financial feature preferences."""
    return {
        "platform": features.platform,
        "cart_enabled": features.cart_enabled,
        "store_credit_enabled": features.store_credit_enabled,
        "store_credit_label": features.store_credit_label,
    }
