"""Policy gate for configured Telegram and Bale checkout methods."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_payment_rail import ShopPaymentRail

SUPPORTED = {
    "telegram": ("store_credit", "telegram_fiat", "telegram_stars"),
    "bale": ("store_credit", "bale_wallet"),
}
DISPLAY = {
    "store_credit": "اعتبار داخلی فروشگاه",
    "telegram_fiat": "پرداخت ریالی تلگرام",
    "telegram_stars": "Telegram Stars",
    "bale_wallet": "کیف پول بله",
}


async def rail_enabled(
    db: AsyncSession, platform: str, rail_type: str,
) -> bool:
    """Honor a disabled rail; missing records preserve prior checkout policy."""
    if rail_type not in SUPPORTED.get(platform, ()):
        return False
    row = await db.scalar(select(ShopPaymentRail).where(
        ShopPaymentRail.platform == platform,
        ShopPaymentRail.rail_type == rail_type,
    ))
    return row.enabled if row else True


async def list_rails(db: AsyncSession) -> list[dict]:
    """Return every provider-supported method, including unconfigured ones."""
    rows = (await db.scalars(select(ShopPaymentRail))).all()
    existing = {(row.platform, row.rail_type): row for row in rows}
    result = []
    for platform, types in SUPPORTED.items():
        for rail in types:
            record = existing.get((platform, rail))
            result.append({
                "platform": platform,
                "rail_type": rail,
                "display_name": record.display_name if record else DISPLAY[rail],
                "enabled": record.enabled if record else True,
                "configured": record is not None,
            })
    return result
