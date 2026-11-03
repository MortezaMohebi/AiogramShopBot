"""Provider-appropriate payment rail policy with explicit per-bot grants.

Legacy Telegram/Bale rails remain backwards compatible. A registered bot
cannot inherit a platform-wide provider token, payment permission, or wallet
simply because another bot uses the same messaging platform.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_multibot import LEGACY_BOT_IDS, ShopBot
from models.shop_payment_rail import ShopPaymentRail
from models.shop_store_commerce import (
    ShopBotCommercePolicy, ShopBotPaymentAccess, ShopPaymentAccount,
)

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


async def payment_account(
    db: AsyncSession, *, bot_id: str, rail_type: str,
) -> ShopPaymentAccount | None:
    """Return one active and explicitly granted provider account for this bot."""
    bot = await db.get(ShopBot, bot_id)
    if (
        bot is None or bot.runtime_owner != "registry"
        or rail_type not in SUPPORTED.get(bot.platform, ())
        or rail_type == "store_credit"
    ):
        return None
    return await db.scalar(
        select(ShopPaymentAccount)
        .join(
            ShopBotPaymentAccess,
            ShopBotPaymentAccess.payment_account_id == ShopPaymentAccount.id,
        )
        .where(
            ShopBotPaymentAccess.bot_id == bot_id,
            ShopBotPaymentAccess.enabled.is_(True),
            ShopPaymentAccount.store_id == bot.store_id,
            ShopPaymentAccount.platform == bot.platform,
            ShopPaymentAccount.rail_type == rail_type,
            ShopPaymentAccount.state == "active",
        )
        .order_by(ShopBotPaymentAccess.priority, ShopPaymentAccount.id)
        .limit(1)
    )


async def rail_enabled(
    db: AsyncSession, platform: str, rail_type: str,
    *, bot_id: str | None = None,
) -> bool:
    """Do not confer privileges by provider-wide defaults on new bots."""
    if rail_type not in SUPPORTED.get(platform, ()):
        return False
    owner = bot_id or LEGACY_BOT_IDS[platform]
    bot = await db.get(ShopBot, owner)
    if bot is None or bot.platform != platform:
        return False

    if bot.runtime_owner == "registry":
        if rail_type == "store_credit":
            policy = await db.get(ShopBotCommercePolicy, owner)
            return bool(policy and policy.credit_enabled is True)
        return await payment_account(
            db, bot_id=owner, rail_type=rail_type,
        ) is not None

    record = await db.scalar(select(ShopPaymentRail).where(
        ShopPaymentRail.platform == platform,
        ShopPaymentRail.rail_type == rail_type,
    ))
    return record.enabled if record else True


async def list_rails(db: AsyncSession) -> list[dict]:
    """Retain the previous platform-scoped console for the legacy two bots."""
    rows = (await db.scalars(select(ShopPaymentRail))).all()
    known = {(row.platform, row.rail_type): row for row in rows}
    return [{
        "platform": platform,
        "rail_type": rail,
        "display_name": (
            known[(platform, rail)].display_name
            if (platform, rail) in known else DISPLAY[rail]
        ),
        "enabled": (
            known[(platform, rail)].enabled
            if (platform, rail) in known else True
        ),
        "configured": (platform, rail) in known,
    } for platform, rails in SUPPORTED.items() for rail in rails]
