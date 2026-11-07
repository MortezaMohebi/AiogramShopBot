"""Provider-appropriate payment rail policy with explicit per-bot grants.

A registered bot cannot inherit a platform-wide provider token, payment
permission or wallet because another bot uses the same messaging platform.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_multibot import ShopBot
from models.shop_scope import require_bot_id, require_registry_bot
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
    bot = await db.get(ShopBot, require_bot_id(bot_id))
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
    bot = await require_registry_bot(db, bot_id, platform)
    if rail_type == "store_credit":
        policy = await db.get(ShopBotCommercePolicy, bot.id)
        return bool(policy and policy.credit_enabled is True)
    return await payment_account(
        db, bot_id=bot.id, rail_type=rail_type,
    ) is not None
