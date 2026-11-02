"""Telegram transport using the existing Aiogram 3 Bot session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from channels.contracts import BotReply

if TYPE_CHECKING:
    from aiogram import Bot


class TelegramTransport:
    """Deliver normalized shop replies through the existing Aiogram bot."""

    def __init__(self, bot: Bot) -> None:
        """Reuse the owning bot's configured session and credentials."""
        self.bot = bot

    async def send(self, chat_id: int, reply: BotReply) -> None:
        """Send plain text with an optional inline keyboard."""
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        markup = None
        if reply.rows:
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=button.label,
                            callback_data=button.callback_data,
                        )
                        for button in row
                    ]
                    for row in reply.rows
                ]
            )
        # Always send uploaded media before the page/navigation text.
        from aiogram.types import FSInputFile
        from dashboard.media_storage import safe_media_path
        from config import SHOP_MEDIA_ROOT

        for attachment in reply.attachments:
            path = safe_media_path(SHOP_MEDIA_ROOT, attachment.storage_key)
            media = FSInputFile(path)
            caption = attachment.caption[:1024] or None
            if attachment.kind == "photo":
                await self.bot.send_photo(
                    chat_id, media, caption=caption, parse_mode=None
                )
            elif attachment.kind == "video":
                await self.bot.send_video(
                    chat_id, media, caption=caption, parse_mode=None
                )
            elif attachment.kind == "audio":
                await self.bot.send_audio(
                    chat_id, media, caption=caption, parse_mode=None
                )
            else:
                await self.bot.send_document(
                    chat_id, media, caption=caption, parse_mode=None
                )
        # The upstream bot defaults to HTML; product content must be plain.
        await self.bot.send_message(
            chat_id=chat_id,
            text=reply.text,
            reply_markup=markup,
            parse_mode=None,
            disable_web_page_preview=True,
        )

    async def acknowledge(self, query_id: str) -> None:
        """Clear the Telegram inline-button loading indicator."""
        await self.bot.answer_callback_query(callback_query_id=query_id)
