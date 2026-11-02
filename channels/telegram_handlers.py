"""A thin Aiogram router for the shared product catalog.

Legacy checkout handlers remain unchanged until the order model is migrated.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import InboundEvent, Platform
from channels.telegram import TelegramTransport
from services.shop_channel_catalog import CatalogFlow
import config


shop_catalog_router = Router(name="shop_catalog")


def _flow() -> CatalogFlow:
    """Build a shared catalog controller using configured currency display."""
    return CatalogFlow(currency_label=config.SHOP_CURRENCY_LABEL)


@shop_catalog_router.message(Command("catalog"))
@shop_catalog_router.message(F.text.in_({"🛍 محصولات", "🏠 صفحه اول"}))
async def show_shop_catalog(message: Message, session: AsyncSession) -> None:
    """Open the same published catalog shown by the Bale adapter."""
    if message.from_user is None:
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
    if callback.message is None:
        return
    event = InboundEvent(
        platform=Platform.TELEGRAM,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        callback_data=callback.data,
        callback_query_id=callback.id,
    )
    reply = await _flow().reply(event, session)
    if reply is not None:
        await TelegramTransport(callback.bot).send(event.chat_id, reply)
