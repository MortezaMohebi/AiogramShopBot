"""Bale transport implementing the documented regular Bot API.

Bale follows Telegram's JSON envelope but has important differences in
formatting and webhook authentication. Keep this transport independent.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.shop_digital_fulfillment import DigitalSend

from aiohttp import ClientError, ClientSession, ClientTimeout

from channels.contracts import BotReply, MediaAttachment


class BaleApiError(RuntimeError):
    """A sanitized Bale API error that never exposes the bot token."""


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
                        f"code {code})."
                    )
                return data.get("result")
        except (ClientError, asyncio.TimeoutError, ValueError) as exc:
            # Avoid exceptions from aiohttp that contain a token-bearing URL.
            raise BaleApiError(f"Bale API {method} request failed.") from None

    async def send_media(self, chat_id: int, media: MediaAttachment) -> None:
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
            raise BaleApiError("Bale media original file is unavailable.") from None
        try:
            selected = bale_media_method(media.kind, media.mime_type, size_bytes)
        except MediaLimitError as error:
            # Message is a safe validation failure with no credential data.
            raise BaleApiError(str(error)) from None

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
            await self._call(selected.name, payload)
            return

        form = FormData()
        form.add_field("chat_id", str(chat_id))
        if media.caption:
            form.add_field("caption", media.caption[:1024])
        try:
            with path.open("rb") as source:
                form.add_field(
                    selected.field,
                    source,
                    filename=path.name,
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
                            f"Bale API {selected.name} rejected the media."
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
                "text": f"{payload.caption}\\n{payload.license_text}",
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

    async def send(self, chat_id: int, reply: BotReply) -> None:
        """Send UTF-8 text with standard inline callback buttons."""
        for media in reply.attachments:
            await self.send_media(chat_id, media)
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": reply.text,
        }
        if reply.request_contact:
            payload["reply_markup"] = {
                "keyboard": [
                    [{"text": "📱 اشتراک شمارهٔ تماس", "request_contact": True}],
                    [{"text": "🏠 منوی اصلی"}],
                ],
                "resize_keyboard": True,
                "one_time_keyboard": True,
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
        await self._call("sendMessage", payload)

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
