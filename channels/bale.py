"""Bale transport implementing the documented regular Bot API.

Bale follows Telegram's JSON envelope but has important differences in
formatting and webhook authentication. Keep this transport independent.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from channels.contracts import BotReply


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

    async def send(self, chat_id: int, reply: BotReply) -> None:
        """Send UTF-8 text with standard inline callback buttons."""
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

    async def acknowledge(self, query_id: str) -> None:
        """Acknowledge newer Bale callbacks; old clients lack the method.

        Bale's archived documentation identifies legacy callbacks by an ID
        starting with '1'. Older clients should receive the next message.
        """
        if not query_id.startswith("1"):
            await self._call(
                "answerCallbackQuery", {"callback_query_id": query_id}
            )
