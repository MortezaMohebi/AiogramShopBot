"""Failover only for read-only Telegram methods across explicit bot routes.

An ambiguous send is never sent again through another Worker. Routes come
from the signed-admin registry and cannot be selected by callback payloads.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from sqlalchemy import select

from models.shop_relay_pool import (
    ShopBotRelayRoute, ShopRelayCredential, ShopRelayWorker,
)
from services import shop_admin_security as security
from services.shop_relay_pool import decrypt_secret
from services.shop_telegram_transport import approved_worker_origins
from utils.telegram_worker import CloudflareWorkerSession

if TYPE_CHECKING:
    from aiogram import Bot

SAFE_RELAY_FAILOVER = frozenset({
    # getUpdates(offset) acknowledges earlier updates. It is NOT a
    # read-only call and can lose messages on ambiguous network failover.
    "getMe", "getWebhookInfo", "getFile",
})


class RelayPoolTelegramSession(BaseSession):
    """Route one bot through its prioritized, independently keyed Workers."""

    def __init__(self, delegates: tuple[CloudflareWorkerSession, ...]) -> None:
        """Reject empty route pools instead of silently using direct egress."""
        if not delegates:
            raise ValueError("No active relay route available.")
        super().__init__(api=delegates[0].api)
        self._delegates = delegates

    async def make_request(
        self, bot: Bot, method: TelegramMethod[TelegramType],
        timeout: int | None = None,
    ) -> TelegramType:
        """Fail over only on transport errors for approved read-only calls."""
        for index, delegate in enumerate(self._delegates):
            try:
                return await delegate.make_request(bot, method, timeout=timeout)
            except TelegramNetworkError:
                if (
                    method.__api_method__ not in SAFE_RELAY_FAILOVER
                    or index == len(self._delegates) - 1
                ):
                    raise
        raise RuntimeError("Unreachable relay fallback state.")

    async def stream_content(
        self, url: str, headers: dict[str, Any] | None = None,
        timeout: int = 30, chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        """Use the originating Worker for file streaming with no replay."""
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        for delegate in self._delegates:
            if (
                origin == delegate.worker_origin
                and parsed.path.startswith("/file/bot")
            ):
                async for chunk in delegate.stream_content(
                    url, headers=headers, timeout=timeout,
                    chunk_size=chunk_size,
                    raise_for_status=raise_for_status,
                ):
                    yield chunk
                return
        raise RuntimeError("Untrusted relay file origin.")

    async def close(self) -> None:
        """Close all relay clients without leaking credentials."""
        for delegate in self._delegates:
            await delegate.close()


async def build_bot_relay_session(bot_id: str) -> RelayPoolTelegramSession:
    """Resolve server-approved routes and active per-bot credential versions."""
    from db import session_maker

    async with session_maker() as db:
        records = (await db.execute(
            select(ShopBotRelayRoute, ShopRelayWorker, ShopRelayCredential)
            .join(
                ShopRelayWorker,
                ShopRelayWorker.id == ShopBotRelayRoute.worker_id,
            )
            .join(
                ShopRelayCredential,
                (ShopRelayCredential.worker_id == ShopBotRelayRoute.worker_id)
                & (ShopRelayCredential.bot_id == ShopBotRelayRoute.bot_id)
                & (ShopRelayCredential.state == "active"),
            )
            .where(
                ShopBotRelayRoute.bot_id == bot_id,
                ShopBotRelayRoute.status == "active",
                ShopRelayWorker.status == "active",
                ShopRelayWorker.archived_at.is_(None),
            )
            .order_by(
                ShopBotRelayRoute.priority, ShopRelayWorker.id,
            ).limit(20)
        )).all()
        if not records:
            raise security.SecurityRejected("relay_route_unavailable", 503)

        approved = set(approved_worker_origins())
        delegates = []
        for _, worker, credential in records:
            if worker.origin not in approved:
                raise security.SecurityRejected(
                    "transport_endpoint_not_approved", 503,
                )
            delegates.append(CloudflareWorkerSession(
                worker_url=worker.origin,
                relay_secret=decrypt_secret(credential),
                bot_id=bot_id,
                credential_version=credential.version,
            ))
        return RelayPoolTelegramSession(tuple(delegates))
