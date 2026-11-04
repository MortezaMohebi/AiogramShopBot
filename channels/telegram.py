"""Telegram transport using the existing Aiogram 3 Bot session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from channels.contracts import BotReply

if TYPE_CHECKING:
    from aiogram import Bot

    from services.shop_digital_fulfillment import DigitalSend


class TelegramTransport:
    """Deliver normalized shop replies through the existing Aiogram bot."""

    def __init__(self, bot: Bot, *, bot_id: str | None = None) -> None:
        """Keep each bot's remote-file cache and session isolated."""
        self.bot = bot
        self.bot_id = bot_id

    async def send_media(self, chat_id: int, attachment) -> None:
        """Send one original shop asset or its own bot-scoped cached file ID."""
        # Keep originals on private storage and cache provider file IDs
        # separately for each bot token. Text/keyboard logic is unchanged.
        import logging

        from aiogram.types import FSInputFile

        from channels.media_policy import (
            BALE_VOICE_LIMIT, MediaLimitError, upload_limit,
        )
        from config import SHOP_MEDIA_ROOT, SHOP_MEDIA_MAX_BYTES
        from dashboard.media_storage import safe_media_path
        from services.shop_media_delivery import (
            bot_fingerprint, cached_file_id, remember_file_id,
        )

        bot_key = bot_fingerprint(self.bot.token)
        path = safe_media_path(SHOP_MEDIA_ROOT, attachment.storage_key)
        try:
            size_bytes = path.stat().st_size
        except OSError:
            raise ValueError("The original shop media file is missing.") from None
        if not 0 < size_bytes <= upload_limit(
            attachment.kind, SHOP_MEDIA_MAX_BYTES
        ):
            raise MediaLimitError("File exceeds shop/platform upload limits.")

        kind = attachment.kind
        if attachment.mime_type == "audio/ogg":
            kind = "voice" if size_bytes <= BALE_VOICE_LIMIT else "document"
        cached = await cached_file_id(
            platform="telegram",
            bot_key=bot_key,
            bot_id=self.bot_id,
            storage_key=attachment.storage_key,
            kind=kind,
        )
        value = cached or FSInputFile(path)
        caption = attachment.caption[:1024] or None

        if kind == "photo":
            message = await self.bot.send_photo(
                chat_id, value, caption=caption, parse_mode=None
            )
            remote_id = message.photo[-1].file_id if message.photo else None
        elif kind == "video":
            message = await self.bot.send_video(
                chat_id, value, caption=caption, parse_mode=None
            )
            remote_id = message.video.file_id if message.video else None
        elif kind == "audio":
            message = await self.bot.send_audio(
                chat_id, value, caption=caption, parse_mode=None
            )
            remote_id = message.audio.file_id if message.audio else None
        elif kind == "voice":
            message = await self.bot.send_voice(
                chat_id, value, caption=caption, parse_mode=None
            )
            remote_id = message.voice.file_id if message.voice else None
        else:
            message = await self.bot.send_document(
                chat_id, value, caption=caption, parse_mode=None
            )
            remote_id = (
                message.document.file_id if message.document else None
            )

        if not cached and remote_id:
            try:
                await remember_file_id(
                    platform="telegram", bot_key=bot_key,
                    bot_id=self.bot_id,
                    storage_key=attachment.storage_key,
                    kind=kind, file_id=remote_id,
                )
            except Exception:
                # The message was already sent; never resend it because
                # an optimization-only database write failed.
                logging.warning("Telegram media cache write failed.")


    async def deliver_digital(self, payload: "DigitalSend") -> str:
        """Send a private purchase once and return the confirmed Message ID.

        The caller owns the durable one-attempt receipt. No document is ever
        copied to general ProductMedia, cached, or addressed by public URL.
        """
        from aiogram.types import FSInputFile

        if payload.kind == "file":
            if payload.asset_path is None or not payload.filename:
                raise ValueError("Missing private digital file.")
            result = await self.bot.send_document(
                chat_id=payload.chat_id,
                document=FSInputFile(
                    payload.asset_path, filename=payload.filename,
                ),
                caption=payload.caption[:1024], parse_mode=None,
                protect_content=True,
            )
        elif payload.kind == "license":
            if not payload.license_text:
                raise ValueError("Missing sealed license payload.")
            result = await self.bot.send_message(
                chat_id=payload.chat_id,
                text=f"{payload.caption}\n{payload.license_text}",
                parse_mode=None, protect_content=True,
            )
        else:
            raise ValueError("Unsupported private digital delivery kind.")
        if type(result.message_id) is not int or result.message_id <= 0:
            raise ValueError("Provider did not confirm delivery Message ID.")
        return str(result.message_id)

    async def send(self, chat_id: int, reply: BotReply) -> None:
        """Send plain text with an optional inline keyboard."""
        from aiogram.types import (
            InlineKeyboardButton, InlineKeyboardMarkup,
            KeyboardButton, ReplyKeyboardMarkup,
        )

        markup = None
        if reply.request_contact:
            markup = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(
                        text="📱 اشتراک شمارهٔ تماس",
                        request_contact=True,
                    )],
                    [KeyboardButton(text="🏠 منوی اصلی")],
                ],
                resize_keyboard=True,
                one_time_keyboard=True,
            )
        elif reply.rows:
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
        for attachment in reply.attachments:
            await self.send_media(chat_id, attachment)
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
