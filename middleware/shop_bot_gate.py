"""Global legacy Telegram gate for independent bot pause and maintenance.

The gate surrounds every Aiogram message and callback handler, including
legacy menus. Financial pre-checkout and successful-payment updates are never
suppressed, because previously issued invoices still require reconciliation.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from db import session_maker
from services.shop_bot_operations import legacy_state


class ShopBotOperationMiddleware(BaseMiddleware):
    """Apply the current Telegram bot state before any handler can sell."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Gate ordinary updates; pass through financial settlement events."""
        if not isinstance(event, Update):
            return await handler(event, data)
        # A payment provider may report an invoice that was issued before
        # maintenance/disable. Such messages must reach the settlement flow.
        if event.pre_checkout_query is not None or (
            event.message is not None
            and event.message.successful_payment is not None
        ) or (
            event.callback_query is not None
            and isinstance(event.callback_query.data, str)
            and event.callback_query.data.startswith("shop:refundorder:")
        ):
            return await handler(event, data)
        message = event.message
        callback = event.callback_query
        if message is None and callback is None:
            return await handler(event, data)

        async with session_maker() as db:
            status = await legacy_state(db, "telegram")
        if status.state == "active":
            return await handler(event, data)

        if callback is not None:
            # Telegram callback buttons must be acknowledged even while off.
            if status.state == "disabled":
                await callback.answer()
            else:
                await callback.answer(
                    text=status.message[:200], show_alert=True,
                )
            return None

        if message is not None and status.state != "disabled":
            await message.answer(status.message, parse_mode=None)
        return None
