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
from utils.telegram import create_bot


@asynccontextmanager
async def provider_client(platform: str, token: str):
    """Yield one authenticated provider connection and always close it."""
    if platform == "telegram":
        # Each active bot has an independent session; the P5 egress router
        # will substitute an approved Proxy/Worker session for each bot.
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
            yield BaleTransport(token, http)
        return
    raise ValueError("Unsupported bot provider")
