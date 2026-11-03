"""Create per-bot provider transports with guaranteed cleanup and no logging.

The shared Gateway owns many Bot objects, not one Docker container per bot.
The later Relay Pool phase can replace the Telegram session factory without
changing catalog/commerce ownership or incoming webhook authentication.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from aiohttp import ClientSession, ClientTimeout

import config
from aiogram.client.session.aiohttp import AiohttpSession

from channels.bale import BaleTransport
from utils.telegram import create_bot


@asynccontextmanager
async def provider_client(
    platform: str, token: str, *, bot_id: str | None = None,
):
    """Yield one authenticated provider connection and always close it."""
    if platform == "telegram":
        # An enabled pool never downgrades a registered bot to direct egress.
        # Legacy bots retain their existing deployment-managed transport.
        if bot_id is not None and config.SHOP_RELAY_POOL_ENABLED:
            from models.shop_multibot import LEGACY_BOT_IDS
            if bot_id not in LEGACY_BOT_IDS.values():
                from services.shop_relay_routing import build_bot_relay_session

                transport = await build_bot_relay_session(bot_id)
            else:
                transport = AiohttpSession()
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
