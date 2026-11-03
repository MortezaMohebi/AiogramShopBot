"""An authenticated, HTTPS-only Cloudflare Worker session for Aiogram 3.14.

The custom HTTP session preserves Aiogram's multipart encoding, API result
validation and streaming downloads. The relay credential is sent exclusively
to the configured Worker origin and is never attached to external URLs.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID
from urllib.parse import urlsplit

from aiohttp import ClientError
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType

if TYPE_CHECKING:
    from aiogram import Bot


RELAY_AUTH_HEADER = "X-Telegram-Relay-Key"


def validate_worker_origin(raw_url: str) -> str:
    """Require a valid HTTPS Worker origin without credentials or path suffix.

    Only the hostname is configurable. The Worker itself always forwards to
    Telegram's fixed API origin, so this must not be an open HTTP proxy.
    """
    if not isinstance(raw_url, str):
        raise ValueError("TELEGRAM_WORKER_URL must be an HTTPS origin.")

    try:
        parts = urlsplit(raw_url.strip())
        port = parts.port
    except ValueError:
        raise ValueError("TELEGRAM_WORKER_URL is invalid.") from None

    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "TELEGRAM_WORKER_URL must be an HTTPS origin without a path, "
            "credentials, query, or fragment."
        )
    return f"https://{parts.netloc.rstrip('/')}"


class CloudflareWorkerSession(AiohttpSession):
    """Make authenticated Telegram API requests through one Worker origin."""

    def __init__(
        self, worker_url: str, relay_secret: str, *,
        bot_id: str | None = None, credential_version: int | None = None,
    ) -> None:
        """Bind each modern relay session to one bot and key version."""
        if not isinstance(relay_secret, str) or len(relay_secret) < 32:
            raise ValueError(
                "TELEGRAM_WORKER_SECRET must contain at least 32 characters."
            )
        if bot_id is not None:
            try:
                bot_id = str(UUID(bot_id))
            except (ValueError, TypeError):
                raise ValueError("Invalid relay bot identity.") from None
            if (
                type(credential_version) is not int
                or credential_version <= 0
            ):
                raise ValueError("Invalid relay credential version.")
        elif credential_version is not None:
            raise ValueError("Legacy relay has no credential version.")
        self.worker_origin = validate_worker_origin(worker_url)
        self._relay_secret = relay_secret
        self._bot_id = bot_id
        self._credential_version = credential_version
        super().__init__(
            api=TelegramAPIServer.from_base(self.worker_origin)
        )

    def _relay_headers(self) -> dict[str, str]:
        """Return the bound Worker credentials, never both auth schemes."""
        if self._bot_id is None:
            return {RELAY_AUTH_HEADER: self._relay_secret}
        return {
            "X-Relay-Bot-ID": self._bot_id,
            "X-Relay-Key": self._relay_secret,
            "X-Relay-Version": str(self._credential_version),
        }

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,
    ) -> TelegramType:
        """Send a multipart/form request with Worker-only authentication.

        This intentionally overrides Aiogram 3.14's small POST method. Using
        default ClientSession headers would leak the relay key when Aiogram
        streams files from unrelated URLs.
        """
        session = await self.create_session()
        url = self.api.api_url(token=bot.token, method=method.__api_method__)
        form = self.build_form_data(bot=bot, method=method)

        try:
            async with session.post(
                url,
                data=form,
                timeout=self.timeout if timeout is None else timeout,
                headers=self._relay_headers(),
                allow_redirects=False,
            ) as response:
                if 300 <= response.status < 400:
                    raise TelegramNetworkError(
                        method=method,
                        message="Telegram Worker returned an unexpected redirect.",
                    )
                body = await response.text()
                if (
                    response.status >= 400
                    and not response.headers.get(
                        "content-type", ""
                    ).lower().startswith("application/json")
                ):
                    raise TelegramNetworkError(
                        method=method,
                        message=(
                            "Telegram Worker rejected the request "
                            f"(HTTP {response.status})."
                        ),
                    )
        except asyncio.TimeoutError:
            raise TelegramNetworkError(
                method=method, message="Telegram Worker request timed out."
            ) from None
        except ClientError:
            # Client exceptions can contain the URL, including bot token.
            raise TelegramNetworkError(
                method=method, message="Telegram Worker connection failed."
            ) from None

        parsed = self.check_response(
            bot=bot, method=method, status_code=response.status, content=body
        )
        return cast(TelegramType, parsed.result)

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        """Authenticate Worker file downloads without exposing the relay key.

        Arbitrary external input URLs continue through the upstream Aiogram
        implementation without the Worker header. Requests to the Worker that
        do not target the file endpoint receive no shared credential.
        """
        parts = urlsplit(url)
        trusted_file_url = (
            parts.scheme == "https"
            and f"{parts.scheme}://{parts.netloc}" == self.worker_origin
            and parts.path.startswith("/file/bot")
        )
        if not trusted_file_url:
            async for chunk in super().stream_content(
                url,
                headers=headers,
                timeout=timeout,
                chunk_size=chunk_size,
                raise_for_status=raise_for_status,
            ):
                yield chunk
            return

        request_headers = dict(headers or {})
        request_headers.update(self._relay_headers())
        session = await self.create_session()

        try:
            async with session.get(
                url,
                headers=request_headers,
                timeout=timeout,
                allow_redirects=False,
            ) as response:
                if not 200 <= response.status < 300:
                    # Do not expose token-bearing Worker paths in exceptions.
                    raise RuntimeError(
                        f"Telegram Worker download returned HTTP {response.status}."
                    )
                async for chunk in response.content.iter_chunked(chunk_size):
                    yield chunk
        except (asyncio.TimeoutError, ClientError):
            raise RuntimeError("Telegram Worker file download failed.") from None
