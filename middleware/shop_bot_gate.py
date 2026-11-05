"""Global legacy Telegram gate for independent bot pause and maintenance.

The gate surrounds every Aiogram message and callback handler, including
legacy menus. Financial pre-checkout and successful-payment updates are never
suppressed, because previously issued invoices still require reconciliation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from channels.contracts import Platform, normalize_update
from channels.telegram import TelegramTransport
from db import session_maker
from services.shop_bot_context import resolve_legacy_bot_context
from services.shop_bot_operations import legacy_state
from services.shop_multibot_dispatch import paused_customer_reply
from services.shop_runtime.ingress import try_legacy_ingress


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
        ):
            return await handler(event, data)
        message = event.message
        callback = event.callback_query
        if message is None and callback is None:
            return await handler(event, data)

        async with session_maker() as db:
            status = await legacy_state(db, "telegram")
            if status.state in {"paused", "maintenance"}:
                normalized = normalize_update(
                    Platform.TELEGRAM,
                    event.model_dump(mode="json", by_alias=True, exclude_none=True),
                )
                if normalized is not None:
                    context = await resolve_legacy_bot_context(
                        db, authenticated_platform=Platform.TELEGRAM,
                    )
                    reply = await paused_customer_reply(
                        db, context=context, event=normalized,
                    )
                    if reply is not None:
                        if callback is not None:
                            await callback.answer()
                        client = callback.bot if callback is not None else message.bot
                        await TelegramTransport(
                            client, bot_id=context.bot_id,
                        ).send(normalized.chat_id, reply)
                        return None
        if status.state == "active":
            if not data.get("shop_runtime_checked"):
                runtime = await try_legacy_ingress(
                    Platform.TELEGRAM,
                    event.model_dump(mode="json", by_alias=True, exclude_none=True),
                    client=data.get("bot"),
                )
                if runtime.get("handled"):
                    return None
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
