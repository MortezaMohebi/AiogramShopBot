"""Telegram transport using the existing Aiogram 3 Bot session."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from channels.contracts import BotReply, ViewOutcome, ViewResult

if TYPE_CHECKING:
    from aiogram import Bot

    from services.shop_digital_fulfillment import DigitalSend


_UNEDITABLE = frozenset({
    "message to edit not found",
    "message can't be edited",
    "message can not be edited",
    "there is no text in the message to edit",
    "there is no media in the message to edit",
})


def _view_failure(error: Exception, *, editing: bool) -> ViewOutcome:
    """Classify explicit edit refusals without exposing provider diagnostics."""
    from aiogram.exceptions import (
        TelegramBadRequest, TelegramEntityTooLarge, TelegramForbiddenError,
        TelegramNotFound, TelegramRetryAfter, TelegramUnauthorizedError,
    )

    if isinstance(error, (TelegramBadRequest, TelegramNotFound)):
        message = error.message.lower().removeprefix("bad request: ").strip()
        if editing and (
            message == "message is not modified"
            or message.startswith("message is not modified: ")
        ):
            return ViewOutcome.NO_CHANGE
        if editing and message in _UNEDITABLE:
            return ViewOutcome.CANNOT_EDIT
        return ViewOutcome.REJECTED
    if isinstance(error, (
        TelegramEntityTooLarge, TelegramForbiddenError,
        TelegramRetryAfter, TelegramUnauthorizedError,
    )):
        return ViewOutcome.REJECTED
    return ViewOutcome.UNKNOWN


class TelegramTransport:
    """Deliver normalized shop replies through the existing Aiogram bot."""

    def __init__(self, bot: Bot, *, bot_id: str | None = None) -> None:
        """Keep each bot's remote-file cache and session isolated."""
        self.bot = bot
        self.bot_id = bot_id

    async def clear_inline(self, chat_id: int, message_id: int) -> None:
        """Disable controls on a superseded UI message without deleting media."""
        from aiogram.exceptions import TelegramBadRequest

        try:
            await self.bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=message_id,
                reply_markup=None,
            )
        except TelegramBadRequest:
            pass

    async def _preview(
        self, chat_id: int, reply: BotReply, markup,
        edit_message_id: int | None, *, strict: bool = False,
    ) -> int | None:
        """Replace a card image in place using the current bot's file cache."""
        from aiogram.exceptions import TelegramBadRequest
        from aiogram.types import FSInputFile, InputMediaPhoto

        from config import SHOP_MEDIA_ROOT
        from dashboard.media_storage import safe_media_path
        from services.shop_media_delivery import (
            bot_fingerprint, cached_file_id, remember_file_id,
        )

        preview = reply.preview
        if preview is None or preview.kind != "photo":
            raise ValueError("Product preview must be a photo.")
        bot_key = bot_fingerprint(self.bot.token)
        cached = await cached_file_id(
            platform="telegram", bot_key=bot_key, bot_id=self.bot_id,
            storage_key=preview.storage_key, kind="photo",
        )
        source = cached or FSInputFile(
            safe_media_path(SHOP_MEDIA_ROOT, preview.storage_key),
        )
        caption = reply.text[:1024]
        message = None
        if edit_message_id:
            try:
                message = await self.bot.edit_message_media(
                    chat_id=chat_id, message_id=edit_message_id,
                    media=InputMediaPhoto(media=source, caption=caption),
                    reply_markup=markup,
                )
            except TelegramBadRequest as error:
                if strict:
                    raise
                outcome = _view_failure(error, editing=True)
                if outcome is ViewOutcome.NO_CHANGE:
                    return edit_message_id
                if outcome is not ViewOutcome.CANNOT_EDIT:
                    raise
                await self.clear_inline(chat_id, edit_message_id)
        if message is None:
            if strict and edit_message_id is not None:
                return None
            message = await self.bot.send_photo(
                chat_id=chat_id, photo=source, caption=caption,
                reply_markup=markup, parse_mode=None,
            )
        remote_id = message.photo[-1].file_id if getattr(message, "photo", None) else None
        if not cached and remote_id:
            try:
                await remember_file_id(
                    platform="telegram", bot_key=bot_key, bot_id=self.bot_id,
                    storage_key=preview.storage_key, kind="photo",
                    file_id=remote_id,
                )
            except Exception:
                # Delivery succeeded; cache failure cannot trigger a resend.
                import logging

                logging.warning("Telegram preview file cache write failed.")
        return getattr(message, "message_id", None)

    async def send_media(self, chat_id: int, attachment) -> int | None:
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
        value = cached or FSInputFile(path, filename=attachment.filename)
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
        elif kind == "animation":
            message = await self.bot.send_animation(
                chat_id, value, caption=caption, parse_mode=None,
            )
            # Telegram may report a GIF as a document after sendAnimation.
            # Keep the returned ID in this bot's animation namespace.
            remote_file = message.animation or message.document
            remote_id = remote_file.file_id if remote_file else None
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
        return getattr(message, "message_id", None)


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

    async def send_runtime(self, chat_id: int, payload) -> list[str]:
        """Send one prepared Runtime intent and return its exact provider receipts.

        An album is one physical API call. Its caption belongs to the first
        item; no untracked follow-up text or keyboard message is emitted.
        """
        from aiogram.exceptions import (
            TelegramBadRequest, TelegramForbiddenError,
            TelegramRetryAfter, TelegramUnauthorizedError,
        )
        from aiogram.types import (
            FSInputFile, InlineKeyboardMarkup, InputMediaDocument,
            InputMediaPhoto, InputMediaVideo, ReplyKeyboardMarkup,
        )

        from services.shop_runtime.contracts import DeliveryRejected

        markup = None
        if payload.reply_markup:
            markup_type = (
                ReplyKeyboardMarkup if "keyboard" in payload.reply_markup
                else InlineKeyboardMarkup
            )
            markup = markup_type.model_validate(payload.reply_markup)
        try:
            if payload.kind == "text":
                result = await self.bot.send_message(
                    chat_id=chat_id, text=payload.text,
                    reply_markup=markup, parse_mode=None,
                    disable_web_page_preview=True,
                )
            elif payload.kind == "media_group":
                constructors = {
                    "photo": InputMediaPhoto, "video": InputMediaVideo,
                    "document": InputMediaDocument,
                }
                media = [
                    constructors[item.kind](
                        media=FSInputFile(item.path),
                        caption=payload.text if index == 0 else None,
                        parse_mode=None,
                    )
                    for index, item in enumerate(payload.media)
                ]
                result = await self.bot.send_media_group(
                    chat_id=chat_id, media=media,
                )
            else:
                method = {
                    "photo": self.bot.send_photo,
                    "video": self.bot.send_video,
                    "document": self.bot.send_document,
                }[payload.kind]
                result = await method(
                    chat_id=chat_id,
                    **{payload.kind: FSInputFile(payload.media[0].path)},
                    caption=payload.text or None,
                    reply_markup=markup, parse_mode=None,
                )
        except TelegramRetryAfter:
            raise DeliveryRejected("runtime_provider_rate_limited", retryable=True) from None
        except (TelegramBadRequest, TelegramForbiddenError, TelegramUnauthorizedError):
            raise DeliveryRejected("runtime_provider_rejected", retryable=False) from None
        except Exception:
            raise RuntimeError("runtime_delivery_uncertain") from None
        messages = result if payload.kind == "media_group" else [result]
        expected = len(payload.media) if payload.kind == "media_group" else 1
        if not isinstance(messages, list) or len(messages) != expected:
            raise RuntimeError("runtime_delivery_receipt_invalid")
        ids = [getattr(message, "message_id", None) for message in messages]
        if any(type(value) is not int or value <= 0 for value in ids):
            raise RuntimeError("runtime_delivery_receipt_invalid")
        return [str(value) for value in ids]

    async def send_view(
        self, chat_id: int, reply: BotReply, *,
        edit_message_id: int | None = None,
    ) -> ViewResult:
        """Attempt one navigation presentation without an implicit replacement."""
        if reply.preview is not None and reply.preview.kind != "photo":
            return ViewResult(ViewOutcome.REJECTED)
        if edit_message_id is not None and (
            reply.cards or reply.attachments
            or reply.request_contact or reply.show_main_keyboard
        ):
            return ViewResult(ViewOutcome.CANNOT_EDIT)
        if reply.cards:
            for index, card in enumerate(reply.cards):
                result = await self.send_view(chat_id, card)
                if result.outcome is not ViewOutcome.CONFIRMED:
                    return ViewResult(ViewOutcome.UNKNOWN) if index else result
            result = await self.send_view(chat_id, replace(reply, cards=()))
            if result.outcome is not ViewOutcome.CONFIRMED:
                return ViewResult(ViewOutcome.UNKNOWN)
            return result
        try:
            message_id = await self._send(
                chat_id, reply, edit_message_id=edit_message_id, strict=True,
            )
        except Exception as error:
            outcome = _view_failure(error, editing=edit_message_id is not None)
            if outcome is ViewOutcome.NO_CHANGE:
                return ViewResult(outcome, edit_message_id)
            return ViewResult(outcome)
        if (
            type(message_id) is not int or message_id <= 0
            or (edit_message_id is not None and message_id != edit_message_id)
        ):
            return ViewResult(ViewOutcome.UNKNOWN)
        return ViewResult(ViewOutcome.CONFIRMED, message_id)

    async def send(
        self, chat_id: int, reply: BotReply, *,
        edit_message_id: int | None = None,
    ) -> int | None:
        """Send plain text with an optional inline keyboard."""
        return await self._send(chat_id, reply, edit_message_id=edit_message_id)

    async def _send(
        self, chat_id: int, reply: BotReply, *,
        edit_message_id: int | None, strict: bool = False,
    ) -> int | None:
        """Build Telegram markup and send or edit with the chosen fallback owner."""
        from aiogram.types import (
            InlineKeyboardButton, InlineKeyboardMarkup,
            KeyboardButton, ReplyKeyboardMarkup,
        )

        if reply.cards:
            # The previous page's controls must not remain active after the
            # next page is shown. Preserve its photo and all requested media.
            if edit_message_id is not None:
                await self.clear_inline(chat_id, edit_message_id)
            for card in reply.cards:
                await self.send(chat_id, card)
            # Only the footer owns page navigation and the tracked UI ID.
            return await self.send(chat_id, replace(reply, cards=()))

        main = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🛍 فروشگاه"), KeyboardButton(text="🛒 سبد خرید")],
                [KeyboardButton(text="📦 سفارش‌های من"), KeyboardButton(text="💬 پشتیبانی")],
            ],
            resize_keyboard=True, is_persistent=True,
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
        if reply.show_main_keyboard and reply.rows:
            await self.bot.send_message(
                chat_id=chat_id, text="🛍 فروشگاه",
                reply_markup=main, parse_mode=None,
            )
        elif reply.show_main_keyboard and not reply.request_contact:
            markup = main
        for attachment in reply.attachments:
            await self.send_media(chat_id, attachment)
        if reply.preview is not None:
            return await self._preview(
                chat_id, reply, markup, edit_message_id, strict=strict,
            )
        if edit_message_id and not reply.attachments and not reply.request_contact:
            try:
                edited = await self.bot.edit_message_text(
                    chat_id=chat_id, message_id=edit_message_id,
                    text=reply.text,
                    reply_markup=markup,
                    parse_mode=None, disable_web_page_preview=True,
                )
                return getattr(
                    edited, "message_id", None if strict else edit_message_id,
                )
            except Exception as error:
                if strict:
                    raise
                outcome = _view_failure(error, editing=True)
                if outcome is ViewOutcome.NO_CHANGE:
                    return edit_message_id
                if outcome is not ViewOutcome.CANNOT_EDIT:
                    raise
                await self.clear_inline(chat_id, edit_message_id)
        # The upstream bot defaults to HTML; product content must be plain.
        message = await self.bot.send_message(
            chat_id=chat_id,
            text=reply.text,
            reply_markup=markup,
            parse_mode=None,
            disable_web_page_preview=True,
        )
        return getattr(message, "message_id", None)

    async def acknowledge(self, query_id: str) -> None:
        """Clear the Telegram inline-button loading indicator."""
        await self.bot.answer_callback_query(callback_query_id=query_id)
