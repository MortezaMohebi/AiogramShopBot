"""Bale transport implementing the documented regular Bot API.

Bale follows Telegram's JSON envelope but has important differences in
formatting and webhook authentication. Keep this transport independent.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.shop_digital_fulfillment import DigitalSend

from aiohttp import ClientError, ClientSession, ClientTimeout

from channels.contracts import BotReply, MediaAttachment, ViewOutcome, ViewResult


_UNEDITABLE = frozenset({
    "message to edit not found",
    "message can't be edited",
    "message can not be edited",
    "there is no text in the message to edit",
})


def _view_failure(method: str, status: int, data: object) -> ViewOutcome:
    """Use a recognized Bale rejection, never a broad HTTP fallback."""
    if status >= 500 or not isinstance(data, dict) or data.get("ok") is not False:
        return ViewOutcome.UNKNOWN
    code = data.get("error_code")
    code = code if type(code) is int else None
    if status == 429 or code == 429:
        return ViewOutcome.REJECTED
    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        return ViewOutcome.UNKNOWN
    message = description.lower().removeprefix("bad request: ").strip()
    if method == "editMessageText" and (status in {400, 404} or code in (400, 404)):
        if message == "message is not modified" or message.startswith("message is not modified: "):
            return ViewOutcome.NO_CHANGE
        if message in _UNEDITABLE:
            return ViewOutcome.CANNOT_EDIT
    return ViewOutcome.REJECTED if 400 <= status < 500 or (
        type(code) is int and 400 <= code < 500
    ) else ViewOutcome.UNKNOWN


class BaleApiError(RuntimeError):
    """A sanitized Bale API error that never exposes the bot token."""

    def __init__(
        self, message: str, *, view_outcome: ViewOutcome = ViewOutcome.UNKNOWN,
    ) -> None:
        """Keep only a typed classification from the provider response."""
        super().__init__(message)
        self.view_outcome = view_outcome


class BaleTransport:
    """Send ordinary Bot API requests to Bale, not its paid business API."""

    BASE_URL = "https://tapi.bale.ai"

    def __init__(
        self, token: str, session: ClientSession, *,
        business_mode: bool = False,
        bot_id: str | None = None,
    ) -> None:
        """Bind one Bale bot to the normal or paid business API explicitly."""
        if not token or "/" in token or "?" in token or "#" in token:
            raise ValueError("Bale bot token is invalid.")
        self._bot_token = token
        self.bot_id = bot_id
        self._business_mode = business_mode
        route = "business/bot" if business_mode else "bot"
        self._url_prefix = f"{self.BASE_URL}/{route}{token}"
        self._session = session

    async def clear_inline(self, chat_id: int, message_id: int) -> None:
        """Remove an obsolete inline keyboard while retaining its message."""
        try:
            await self._call("editMessageReplyMarkup", {
                "chat_id": chat_id, "message_id": message_id,
                "reply_markup": {"inline_keyboard": []},
            })
        except BaleApiError:
            pass

    async def _call(
        self, method: str, body: dict[str, Any], *, timeout_seconds: int = 15
    ) -> Any:
        """Validate the Bale response envelope without logging credentials."""
        try:
            async with self._session.post(
                f"{self._url_prefix}/{method}",
                json=body,
                timeout=ClientTimeout(total=timeout_seconds),
            ) as response:
                data = await response.json(content_type=None)
                code = data.get("error_code") if isinstance(data, dict) else None
                if (
                    response.status >= 400
                    or not isinstance(data, dict)
                    or data.get("ok") is not True
                ):
                    raise BaleApiError(
                        f"Bale API {method} failed (HTTP {response.status}, "
                        f"code {code if type(code) is int else None}).",
                        view_outcome=_view_failure(method, response.status, data),
                    )
                return data.get("result")
        except (ClientError, asyncio.TimeoutError, ValueError):
            # Avoid exceptions from aiohttp that contain a token-bearing URL.
            raise BaleApiError(f"Bale API {method} request failed.") from None

    async def send_media(
        self, chat_id: int, media: MediaAttachment, *,
        reply_markup: dict[str, Any] | None = None,
    ) -> int | None:
        """Send bounded multipart media, reusing only this Bale bot's own file ID."""
        import logging

        from aiohttp import FormData

        from channels.media_policy import MediaLimitError, bale_media_method
        from config import SHOP_MEDIA_ROOT
        from dashboard.media_storage import safe_media_path
        from services.shop_media_delivery import (
            bot_fingerprint, cached_file_id, remember_file_id,
        )

        path = safe_media_path(SHOP_MEDIA_ROOT, media.storage_key)
        try:
            size_bytes = path.stat().st_size
        except OSError:
            raise BaleApiError(
                "Bale media original file is unavailable.",
                view_outcome=ViewOutcome.REJECTED,
            ) from None
        try:
            selected = bale_media_method(media.kind, media.mime_type, size_bytes)
        except MediaLimitError as error:
            # Message is a safe validation failure with no credential data.
            raise BaleApiError(str(error), view_outcome=ViewOutcome.REJECTED) from None

        bot_key = bot_fingerprint(self._bot_token)
        cached = await cached_file_id(
            platform="bale",
            bot_key=bot_key,
            bot_id=self.bot_id,
            storage_key=media.storage_key,
            kind=selected.kind,
        )
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "caption": media.caption[:1024],
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        if self._business_mode and selected.name == "sendVoice":
            raise BaleApiError(
                "Bale business broadcast does not support sendVoice."
            )
        if self._business_mode and not cached:
            raise BaleApiError(
                "Bale business media requires a cached file_id from the "
                "same bot. Prepare the media with the regular Bot API first."
            )

        if cached:
            # Bale file IDs are unique per bot. Never borrow another bot's ID.
            payload[selected.field] = cached
            message = await self._call(selected.name, payload)
            return message.get("message_id") if isinstance(message, dict) else None

        form = FormData()
        form.add_field("chat_id", str(chat_id))
        if reply_markup:
            import json

            form.add_field(
                "reply_markup", json.dumps(reply_markup, ensure_ascii=False),
            )
        if media.caption:
            form.add_field("caption", media.caption[:1024])
        try:
            with path.open("rb") as source:
                form.add_field(
                    selected.field,
                    source,
                    filename=media.filename or path.name,
                    content_type=media.mime_type,
                )
                async with self._session.post(
                    f"{self._url_prefix}/{selected.name}",
                    data=form,
                    timeout=ClientTimeout(total=120),
                ) as response:
                    result = await response.json(content_type=None)
                    if (
                        response.status >= 400
                        or not isinstance(result, dict)
                        or result.get("ok") is not True
                    ):
                        raise BaleApiError(
                            f"Bale API {selected.name} rejected the media.",
                            view_outcome=_view_failure(
                                selected.name, response.status, result,
                            ),
                        )
                    message = result.get("result")
        except (OSError, ClientError, asyncio.TimeoutError, ValueError):
            raise BaleApiError("Bale media delivery failed.") from None

        remote_id = None
        if isinstance(message, dict):
            if selected.kind == "photo":
                sizes = message.get("photo")
                if isinstance(sizes, list) and sizes:
                    last = sizes[-1]
                    remote_id = (
                        last.get("file_id") if isinstance(last, dict) else None
                    )
            else:
                received = message.get(selected.kind)
                remote_id = (
                    received.get("file_id") if isinstance(received, dict)
                    else None
                )
        if isinstance(remote_id, str) and remote_id:
            try:
                await remember_file_id(
                    platform="bale",
                    bot_key=bot_key,
                    bot_id=self.bot_id,
                    storage_key=media.storage_key,
                    kind=selected.kind,
                    file_id=remote_id,
                )
            except Exception:
                # Delivery succeeded: never resend a user message just because
                # the optional file-id cache could not be updated.
                logging.warning("Bale file-id cache write was unsuccessful.")
        return message.get("message_id") if isinstance(message, dict) else None

    async def deliver_digital(self, payload: "DigitalSend") -> str:
        """Send one private paid file or license via Bale normal Bot API.

        The caller commits its single-send attempt before this method. Bale
        failures and timeouts do not trigger an automatic duplicate send.
        """
        if self._business_mode:
            raise BaleApiError("Paid goods must use the normal Bale Bot API.")
        if payload.kind == "license":
            if not payload.license_text:
                raise BaleApiError("Private license was not available.")
            answer = await self._call("sendMessage", {
                "chat_id": payload.chat_id,
                "text": f"{payload.caption}\n{payload.license_text}",
            })
        elif payload.kind == "file":
            if payload.asset_path is None or not payload.filename:
                raise BaleApiError("Private digital file was not available.")
            from aiohttp import FormData

            form = FormData()
            form.add_field("chat_id", str(payload.chat_id))
            form.add_field("caption", payload.caption[:1024])
            try:
                with payload.asset_path.open("rb") as source:
                    form.add_field(
                        "document", source,
                        filename=payload.filename,
                        content_type=payload.mime_type or "application/octet-stream",
                    )
                    async with self._session.post(
                        f"{self._url_prefix}/sendDocument",
                        data=form, timeout=ClientTimeout(total=120),
                    ) as response:
                        data = await response.json(content_type=None)
                        if (
                            response.status >= 400
                            or not isinstance(data, dict)
                            or data.get("ok") is not True
                        ):
                            raise BaleApiError("Private document API rejected request.")
                        answer = data.get("result")
            except (OSError, ClientError, asyncio.TimeoutError, ValueError):
                raise BaleApiError(
                    "Private document outcome is unknown; do not retry."
                ) from None
        else:
            raise BaleApiError("Unsupported private delivery kind.")

        if not isinstance(answer, dict):
            raise BaleApiError("Bale delivery Message receipt is unavailable.")
        message_id = answer.get("message_id")
        if type(message_id) is not int or message_id <= 0:
            raise BaleApiError("Bale did not confirm a delivery Message ID.")
        return str(message_id)

    async def send_view(
        self, chat_id: int, reply: BotReply, *,
        edit_message_id: int | None = None,
    ) -> ViewResult:
        """Present one view and leave any replacement to the coordinator."""
        if reply.preview is not None and reply.preview.kind != "photo":
            return ViewResult(ViewOutcome.REJECTED)
        if edit_message_id is not None and (
            reply.preview is not None or reply.cards or reply.attachments
            or reply.request_contact or reply.keyboard_rows is not None
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
        except BaleApiError as error:
            if error.view_outcome is ViewOutcome.NO_CHANGE:
                return ViewResult(error.view_outcome, edit_message_id)
            return ViewResult(error.view_outcome)
        except (ClientError, OSError, ValueError):
            return ViewResult(ViewOutcome.UNKNOWN)
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
        """Send UTF-8 text with standard inline callback buttons."""
        return await self._send(chat_id, reply, edit_message_id=edit_message_id)

    async def _send(
        self, chat_id: int, reply: BotReply, *,
        edit_message_id: int | None, strict: bool = False,
    ) -> int | None:
        """Build Bale markup and send or edit with the chosen fallback owner."""
        if reply.cards:
            # Keep the former page in the chat, but disable its page controls.
            # Each product is a separate photo with its own detail button.
            if edit_message_id:
                await self.clear_inline(chat_id, edit_message_id)
            for card in reply.cards:
                await self.send(chat_id, card)
            return await self.send(chat_id, replace(reply, cards=()))

        for media in reply.attachments:
            await self.send_media(chat_id, media)
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": reply.text,
        }
        if reply.request_contact:
            edit_message_id = None
            payload["reply_markup"] = {
                "keyboard": [
                    [{"text": "📱 اشتراک شمارهٔ تماس", "request_contact": True}],
                    [{"text": "🏠 منوی اصلی"}],
                ],
            }
        elif reply.rows:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [
                        {
                            "text": button.label,
                            "callback_data": button.callback_data,
                        }
                        for button in row
                    ]
                    for row in reply.rows
                ]
            }
        elif reply.keyboard_rows is not None:
            edit_message_id = None
            payload["reply_markup"] = (
                {
                    "keyboard": [
                        [{"text": label} for label in row]
                        for row in reply.keyboard_rows
                    ],
                }
                if reply.keyboard_rows
                else {"remove_keyboard": True}
            )
        if reply.preview is not None:
            if reply.preview.kind != "photo":
                raise ValueError("Product preview must be a photo.")
            if edit_message_id:
                # Bale documents text/caption/markup edits, but no media
                # replacement. Preserve old previews without active controls.
                await self.clear_inline(chat_id, edit_message_id)
            return await self.send_media(
                chat_id,
                MediaAttachment(
                    storage_key=reply.preview.storage_key, kind="photo",
                    mime_type=reply.preview.mime_type, caption=reply.text[:1024],
                ),
                reply_markup=payload.get("reply_markup"),
            )
        if edit_message_id and not reply.attachments and not reply.request_contact:
            try:
                result = await self._call("editMessageText", {
                    **payload, "message_id": edit_message_id,
                })
                default_id = None if strict else edit_message_id
                return result.get("message_id", default_id) if isinstance(result, dict) else default_id
            except BaleApiError as error:
                if strict:
                    raise
                if error.view_outcome is ViewOutcome.NO_CHANGE:
                    return edit_message_id
                if error.view_outcome is not ViewOutcome.CANNOT_EDIT:
                    raise
                await self.clear_inline(chat_id, edit_message_id)
        result = await self._call("sendMessage", payload)
        return result.get("message_id") if isinstance(result, dict) else None

    async def send_runtime(self, chat_id: int, payload) -> list[str]:
        """Send one prepared Runtime message/album with explicit message receipts.

        Keep this one-attempt API separate from legacy send(), which may send
        several attachments and a final text message without receipt IDs.
        """
        from contextlib import ExitStack
        import json

        from aiohttp import FormData

        from services.shop_runtime.contracts import DeliveryRejected

        if self._business_mode:
            raise DeliveryRejected("runtime_business_api_unsupported", retryable=False)
        body = {"chat_id": chat_id, "parse_mode": None}
        if payload.reply_markup:
            body["reply_markup"] = payload.reply_markup
        expected = len(payload.media) if payload.kind == "media_group" else 1
        try:
            with ExitStack() as sources:
                if payload.kind == "text":
                    method = "sendMessage"
                    body["text"] = payload.text
                    request = {"json": body}
                else:
                    methods = {
                        "photo": "sendPhoto", "video": "sendVideo",
                        "document": "sendDocument", "media_group": "sendMediaGroup",
                    }
                    method = methods[payload.kind]
                    form = FormData()
                    form.add_field("chat_id", str(chat_id))
                    if payload.reply_markup:
                        form.add_field("reply_markup", json.dumps(payload.reply_markup, ensure_ascii=False))
                    if payload.kind != "media_group" and payload.text:
                        form.add_field("caption", payload.text)
                    group = []
                    for index, item in enumerate(payload.media):
                        field = f"runtime_{index}" if payload.kind == "media_group" else payload.kind
                        source = sources.enter_context(item.path.open("rb"))
                        form.add_field(field, source, filename=item.path.name, content_type=item.mime_type)
                        if payload.kind == "media_group":
                            entry = {"type": item.kind, "media": f"attach://{field}"}
                            if index == 0 and payload.text:
                                entry["caption"] = payload.text
                            group.append(entry)
                    if payload.kind == "media_group":
                        form.add_field("media", json.dumps(group, ensure_ascii=False))
                    request = {"data": form}
                async with self._session.post(
                    f"{self._url_prefix}/{method}", **request,
                    timeout=ClientTimeout(total=120), allow_redirects=False,
                ) as response:
                    data = await response.json(content_type=None)
                    if not isinstance(data, dict) or data.get("ok") is not True:
                        code = data.get("error_code") if isinstance(data, dict) else None
                        # Only explicit, definite Bot API rejections are safe
                        # to classify; malformed/5xx responses stay uncertain.
                        if isinstance(data, dict) and data.get("ok") is False and type(code) is int and code in {400, 401, 403, 404, 409, 413, 422, 429}:
                            raise DeliveryRejected(
                                "runtime_provider_rate_limited" if code == 429 else "runtime_provider_rejected",
                                retryable=code == 429,
                            )
                        raise RuntimeError("runtime_delivery_uncertain")
                    if response.status >= 300:
                        raise RuntimeError("runtime_delivery_uncertain")
                    result = data.get("result")
        except DeliveryRejected:
            raise
        except Exception:
            raise RuntimeError("runtime_delivery_uncertain") from None
        messages = result if payload.kind == "media_group" else [result]
        if not isinstance(messages, list) or len(messages) != expected:
            raise RuntimeError("runtime_delivery_receipt_invalid")
        ids = [message.get("message_id") if isinstance(message, dict) else None for message in messages]
        if any(type(value) is not int or value <= 0 for value in ids):
            raise RuntimeError("runtime_delivery_receipt_invalid")
        return [str(value) for value in ids]

    async def download_runtime(self, file_id: str, *, max_bytes: int) -> bytes:
        """Download bounded evidence through this Bot's regular API credential."""
        from services.shop_runtime.adapters import safe_download_path

        if self._business_mode or type(max_bytes) is not int or not 1 <= max_bytes <= 20_000_000:
            raise BaleApiError("Runtime download is unavailable.")
        try:
            remote = await self._call("getFile", {"file_id": file_id})
            if not isinstance(remote, dict) or remote.get("file_id", file_id) != file_id:
                raise BaleApiError("Runtime download metadata is invalid.")
            size = remote.get("file_size")
            if size is not None and (type(size) is not int or size != max_bytes):
                raise BaleApiError("Runtime download size is invalid.")
            path = safe_download_path(remote.get("file_path"))
            # Download routes are fixed by the provider. Neither redirects
            # nor an incoming URL can move the request to another origin.
            async with self._session.get(
                f"{self.BASE_URL}/file/bot{self._bot_token}/{path}",
                timeout=ClientTimeout(total=30), allow_redirects=False,
            ) as response:
                if response.status != 200 or (response.content_length is not None and response.content_length > max_bytes):
                    raise BaleApiError("Runtime download was rejected.")
                result = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    if len(result) + len(chunk) > max_bytes:
                        raise BaleApiError("Runtime download size is invalid.")
                    result.extend(chunk)
            return bytes(result)
        except Exception:
            raise BaleApiError("Runtime download failed.") from None

    async def send_invoice(
        self,
        *,
        chat_id: int,
        title: str,
        description: str,
        payload: str,
        provider_token: str,
        amount_irr: int,
    ) -> None:
        """Issue a native Bale wallet invoice for one order, priced in rials."""
        if not provider_token or not provider_token.strip():
            raise ValueError("Bale wallet provider token is not configured.")
        if not 1 <= len(title) <= 32 or not 1 <= len(description) <= 255:
            raise ValueError("Bale invoice title or description is out of range.")
        if not 1 <= len(payload.encode("utf-8")) <= 128:
            raise ValueError("Bale invoice payload is out of range.")
        if type(amount_irr) is not int or amount_irr <= 0:
            raise ValueError("Bale wallet amount must be a positive rial integer.")

        await self._call(
            "sendInvoice",
            {
                "chat_id": chat_id,
                "title": title,
                "description": description,
                "payload": payload,
                "provider_token": provider_token,
                "prices": [{"label": title, "amount": amount_irr}],
            },
        )

    async def answer_pre_checkout(
        self, query_id: str, *, accepted: bool, error_message: str | None = None
    ) -> None:
        """Reply to Bale's pre-checkout request within its ten-second limit."""
        if not query_id:
            raise ValueError("A Bale pre-checkout query ID is required.")
        data: dict[str, Any] = {
            "pre_checkout_query_id": query_id,
            "ok": accepted,
        }
        if not accepted:
            data["error_message"] = (
                error_message or "سفارش فعلاً قابل پرداخت نیست."
            )[:255]
        # Bale requires a pre-checkout answer within ten seconds.
        await self._call(
            "answerPreCheckoutQuery", data, timeout_seconds=8
        )

    async def inquire_transaction(self, transaction_id: str) -> dict[str, Any]:
        """Retrieve verified transaction status from Bale before fulfillment."""
        if not transaction_id or len(transaction_id) > 128:
            raise ValueError("Invalid Bale transaction ID.")
        result = await self._call(
            "inquireTransaction", {"transaction_id": transaction_id}
        )
        if not isinstance(result, dict):
            raise BaleApiError("Bale inquiry did not return a transaction.")
        return result

    async def acknowledge(self, query_id: str) -> None:
        """Acknowledge newer Bale callbacks; old clients lack the method.

        Bale's archived documentation identifies legacy callbacks by an ID
        starting with '1'. Older clients should receive the next message.
        """
        if not query_id.startswith("1"):
            await self._call(
                "answerCallbackQuery", {"callback_query_id": query_id}
            )
