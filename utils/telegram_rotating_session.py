"""Drain-safe, hot-swappable Aiogram session for outbound Telegram traffic.

All Telegram handlers continue using the same Bot object and session
middleware. A transport change waits for in-flight API calls and file
downloads before replacing the delegate, without dropping pending updates.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType

if TYPE_CHECKING:
    from aiogram import Bot


class RotatingTelegramSession(BaseSession):
    """Keep all Bot references stable while switching the underlying session."""

    def __init__(self, initial: BaseSession) -> None:
        """Wrap a built transport without owning its Telegram API token."""
        super().__init__(api=initial.api)
        self._current = initial
        self._condition = asyncio.Condition()
        self._inflight = 0
        self._replacing = False
        self._closed = False

    async def _acquire(self) -> BaseSession:
        """Freeze new calls briefly while a verified delegate is being swapped."""
        async with self._condition:
            while self._replacing and not self._closed:
                await self._condition.wait()
            if self._closed:
                raise RuntimeError("Telegram session has been closed")
            self._inflight += 1
            return self._current

    async def _release(self) -> None:
        """Wake an awaiting controlled replacement after work completes."""
        async with self._condition:
            self._inflight -= 1
            self._condition.notify_all()

    async def replace(self, new_session: BaseSession) -> BaseSession:
        """Atomically install a pre-verified session and return the old delegate.

        The caller is responsible for closing the old delegate only after its
        database commit succeeds; on failure it may replace it back.
        """
        if new_session is self:
            raise ValueError("The delegate cannot be its own wrapper")
        async with self._condition:
            if self._closed:
                raise RuntimeError("Telegram session has been closed")
            while self._replacing:
                await self._condition.wait()
            self._replacing = True
            try:
                while self._inflight:
                    await self._condition.wait()
                old = self._current
                self._current = new_session
                # Aiogram's get_file/download paths use session.api.file_url;
                # therefore this property must track the live delegate.
                self.api = new_session.api
                return old
            finally:
                self._replacing = False
                self._condition.notify_all()

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,
    ) -> TelegramType:
        """Forward the request using a stable, request-scoped delegate."""
        session = await self._acquire()
        try:
            return await session.make_request(bot, method, timeout=timeout)
        finally:
            await self._release()

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        """Drain existing file streams before switching the transport."""
        session = await self._acquire()
        try:
            async for chunk in session.stream_content(
                url,
                headers=headers,
                timeout=timeout,
                chunk_size=chunk_size,
                raise_for_status=raise_for_status,
            ):
                yield chunk
        finally:
            await self._release()

    async def close(self) -> None:
        """Wait for in-flight requests and close only the active delegate."""
        async with self._condition:
            if self._closed:
                return
            while self._replacing:
                await self._condition.wait()
            self._replacing = True
            self._closed = True
            self._condition.notify_all()
            while self._inflight:
                await self._condition.wait()
            old = self._current
        await old.close()
