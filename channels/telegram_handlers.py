"""A thin Aiogram router for the shared product catalog.

Legacy checkout handlers remain unchanged until the order model is migrated.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply, InboundEvent, Platform
from channels.telegram import TelegramTransport
from services.shop_channel_catalog import CatalogFlow
from services.bale_wallet import BaleWalletService
from services.shop_identity import is_blocked, register_customer
import config


shop_catalog_router = Router(name="shop_catalog")


def _flow() -> CatalogFlow:
    """Build a shared catalog controller using configured currency display."""
    return CatalogFlow(
        currency_label=config.SHOP_CURRENCY_LABEL,
        display_unit=config.SHOP_DISPLAY_UNIT,
    )


@shop_catalog_router.message(Command("orders"))
@shop_catalog_router.message(F.text == "📦 سفارش‌های من")
async def show_shop_orders(message: Message, session: AsyncSession) -> None:
    """Show new shared orders belonging to this Telegram account only."""
    if message.from_user is None or message.chat.type != "private":
        return
    text = await BaleWalletService.list_orders(
        session, platform="telegram", platform_user_id=message.from_user.id
    )
    await TelegramTransport(message.bot).send(
        message.chat.id, BotReply(text)
    )


@shop_catalog_router.message(Command("catalog"))
@shop_catalog_router.message(F.text.in_({"🛍 محصولات", "🏠 صفحه اول"}))
async def show_shop_catalog(message: Message, session: AsyncSession) -> None:
    """Open the same published catalog shown by the Bale adapter."""
    # Keep the storefront private, matching Bale's event normalization.
    if message.from_user is None or message.chat.type != "private":
        return
    await register_customer(
        session,
        platform=Platform.TELEGRAM,
        platform_user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    if await is_blocked(
        session, platform=Platform.TELEGRAM,
        platform_user_id=message.from_user.id
    ):
        return
    event = InboundEvent(
        platform=Platform.TELEGRAM,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text="🛍 محصولات",
    )
    reply = await _flow().reply(event, session)
    if reply is not None:
        await TelegramTransport(message.bot).send(event.chat_id, reply)


@shop_catalog_router.callback_query(F.data.startswith("shop:"))
async def shop_catalog_button(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Handle shop callbacks without sharing Aiogram objects with the core."""
    await callback.answer()
    if await is_blocked(
        session, platform=Platform.TELEGRAM,
        platform_user_id=callback.from_user.id
    ):
        return
    if callback.message is None or callback.message.chat.type != "private":
        return
    event = InboundEvent(
        platform=Platform.TELEGRAM,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        callback_data=callback.data,
        callback_query_id=callback.id,
    )
    # Telegram still uses the upstream cart/checkout flow for purchases.
    # Never claim an unpaid native invoice is available without a configured
    # and fully verified payment provider.
    if callback.data and callback.data.startswith("shop:checkout:"):
        reply = BotReply(
            "برای خرید در تلگرام از «دسته‌بندی‌ها» و «سبد خرید» استفاده کنید."
        )
    elif callback.data == "shop:orders":
        text = await BaleWalletService.list_orders(
            session, platform="telegram", platform_user_id=event.user_id
        )
        reply = BotReply(text)
    else:
        reply = await _flow().reply(event, session)
    if reply is not None:
        await TelegramTransport(callback.bot).send(event.chat_id, reply)
