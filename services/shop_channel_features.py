"""Single source of truth for provider-specific shop capability toggles."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_channel_features import ShopChannelFeature

PLATFORMS = ("telegram", "bale")


@dataclass(frozen=True, slots=True)
class ChannelFeatures:
    """Effective feature state without creating database rows on reads."""

    platform: str
    cart_enabled: bool
    store_credit_enabled: bool
    store_credit_label: str


async def get_features(
    session: AsyncSession, platform: str,
) -> ChannelFeatures:
    """Load current state; a missing record preserves legacy behavior."""
    if platform not in PLATFORMS:
        raise ValueError("Unsupported provider")
    row = await session.get(ShopChannelFeature, platform)
    if row is None:
        return ChannelFeatures(
            platform=platform,
            cart_enabled=True,
            store_credit_enabled=True,
            store_credit_label="اعتبار فروشگاه",
        )
    return ChannelFeatures(
        platform=row.platform,
        cart_enabled=row.cart_enabled,
        store_credit_enabled=row.store_credit_enabled,
        store_credit_label=row.store_credit_label,
    )


def to_data(features: ChannelFeatures) -> dict:
    """Expose only allowlisted settings, never financial ledger data."""
    return {
        "platform": features.platform,
        "cart_enabled": features.cart_enabled,
        "store_credit_enabled": features.store_credit_enabled,
        "store_credit_label": features.store_credit_label,
    }
