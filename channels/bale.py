"""Bale transport implementing the documented regular Bot API.

Bale follows Telegram's JSON envelope but has important differences in
formatting and webhook authentication. Keep this transport independent.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from channels.contracts import BotReply, MediaAttachment


class BaleApiError(RuntimeError):
    """A sanitized Bale API error that never exposes the bot token."""


class BaleTransport:
    """Send ordinary Bot API requests to Bale, not its paid business API."""

    BASE_URL = "https://tapi.bale.ai"

    def __init__(self, token: str, session: ClientSession) -> None:
        """Bind a Bale bot token and a reusable HTTP session."""
        if not token or "/" in token or "?" in token or "#" in token:
            raise ValueError("Bale bot token is invalid.")
        self._url_prefix = f"{self.BASE_URL}/bot{token}"
        self._session = session

    async def _call(self, method: str, body: dict[str, Any]) -> Any:
        """Validate the Bale response envelope without logging credentials."""
        try:
            async with self._session.post(
                f"{self._url_prefix}/{method}",
                json=body,
                timeout=ClientTimeout(total=15),
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
        """Upload a private image, video, audio or document to the Bale Bot API."""
        from aiohttp import FormData
        from config import SHOP_MEDIA_ROOT
        from dashboard.media_storage import safe_media_path

        method_by_kind = {
            "photo": ("sendPhoto", "photo"),
            "video": ("sendVideo", "video"),
            "audio": ("sendAudio", "audio"),
            "document": ("sendDocument", "document"),
        }
        selected = method_by_kind.get(media.kind)
        if selected is None:
            raise BaleApiError("Unsupported Bale media kind.")
        method, field_name = selected
        path = safe_media_path(SHOP_MEDIA_ROOT, media.storage_key)

        form = FormData()
        form.add_field("chat_id", str(chat_id))
        if media.caption:
            form.add_field("caption", media.caption[:1024])
        # File content is streamed from the original private store, never
        # fetched from a Telegram-specific or Bale-specific file_id.
        try:
            with path.open("rb") as source:
                form.add_field(
                    field_name,
                    source,
                    filename=path.name,
                    content_type=media.mime_type,
                )
                async with self._session.post(
                    f"{self._url_prefix}/{method}",
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
                            f"Bale API {method} rejected the media upload."
                        )
        except (OSError, ClientError, asyncio.TimeoutError, ValueError):
            raise BaleApiError("Bale media delivery failed.") from None

    async def send(self, chat_id: int, reply: BotReply) -> None:
        """Send UTF-8 text with standard inline callback buttons."""
        for media in reply.attachments:
            await self.send_media(chat_id, media)
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": reply.text,
        }
        if reply.rows:
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
        await self._call("answerPreCheckoutQuery", data)

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
