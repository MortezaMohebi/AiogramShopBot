"""A thin Aiogram router for the shared product catalog.

Legacy checkout handlers remain unchanged until the order model is migrated.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from sqlalchemy import select

from db import get_db_session
from models.shop_checkout import ShopCart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply, InboundEvent, Platform
from channels.telegram import TelegramTransport
from services.shop_channel_catalog import CatalogFlow
from services.shop_cart import ShopCartFlow
from services.shop_orders import ShopOrdersFlow
from services.shop_identity import is_blocked, register_customer
import config


shop_catalog_router = Router(name="shop_catalog")


class AwaitingShopInput(BaseFilter):
    """Match free-form text only while a known shopping form is awaiting it."""

    async def __call__(self, message: Message) -> bool:
        """Do not intercept unrelated legacy Telegram chat messages."""
        if (
            message.from_user is None or message.chat.type != "private"
            or not message.text or message.text.startswith("/")
        ):
            return False
        async with get_db_session() as session:
            return bool(await session.scalar(
                select(ShopCart.id).where(
                    ShopCart.platform == Platform.TELEGRAM.value,
                    ShopCart.platform_user_id == message.from_user.id,
                    ShopCart.awaiting_input.is_not(None),
                )
            ))


async def _shop_reply(
    event: InboundEvent, session: AsyncSession
) -> BotReply | None:
    """Select the common cart first, then catalog for non-cart actions."""
    orders = await ShopOrdersFlow(config.SHOP_DISPLAY_UNIT).reply(event, session)
    if orders is not None:
        return orders
    cart = await ShopCartFlow(config.SHOP_DISPLAY_UNIT).reply(event, session)
    if cart is not None:
        return cart
    return await _flow().reply(event, session)


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
    reply = await _shop_reply(
        InboundEvent(
            platform=Platform.TELEGRAM,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            text="/orders",
        ),
        session,
    )
    if reply is not None:
        await TelegramTransport(message.bot).send(message.chat.id, reply)


@shop_catalog_router.message(Command("cart"))
@shop_catalog_router.message(Command("checkout"))
@shop_catalog_router.message(F.text == "🛒 سبد خرید")
@shop_catalog_router.message(AwaitingShopInput())
async def shopping_basket_text(message: Message, session: AsyncSession) -> None:
    """Process shopping commands and the next address/coupon text message."""
    if message.from_user is None or message.chat.type != "private":
        return
    if await is_blocked(
        session, platform=Platform.TELEGRAM,
        platform_user_id=message.from_user.id,
    ):
        return
    event = InboundEvent(
        platform=Platform.TELEGRAM,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=message.text,
    )
    reply = await _shop_reply(event, session)
    if reply is not None:
        await TelegramTransport(message.bot).send(message.chat.id, reply)


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
    reply = await _shop_reply(event, session)
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
    reply = await _shop_reply(event, session)
    if reply is not None:
        await TelegramTransport(callback.bot).send(event.chat_id, reply)
