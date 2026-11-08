"""Create per-bot provider transports with guaranteed cleanup and no logging.

The shared Gateway owns many Bot objects, not one Docker container per bot.
The later Relay Pool phase can replace the Telegram session factory without
changing catalog/commerce ownership or incoming webhook authentication.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from aiohttp import ClientSession, ClientTimeout

from aiogram.client.session.aiohttp import AiohttpSession

from channels.bale import BaleTransport
from services.shop_service_controls import service_enabled
from utils.telegram import create_bot


@asynccontextmanager
async def provider_client(
    platform: str, token: str, *, bot_id: str | None = None,
):
    """Yield one authenticated provider connection and always close it."""
    if not isinstance(bot_id, str) or not bot_id:
        raise ValueError("A registered bot ID is required for provider connections.")
    if platform == "telegram":
        if service_enabled("relay-pool"):
            from services.shop_relay_routing import build_bot_relay_session

            transport = await build_bot_relay_session(bot_id)
        else:
            transport = AiohttpSession()
        bot = create_bot(token, transport)
        try:
            yield bot
        finally:
            await bot.session.close()
        return
    if platform == "bale":
        async with ClientSession(
            timeout=ClientTimeout(total=20), trust_env=False,
        ) as http:
            yield BaleTransport(token, http, bot_id=bot_id)
        return
    raise ValueError("Unsupported bot provider")
