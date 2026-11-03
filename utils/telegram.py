"""Configure direct, standard proxy or Cloudflare Worker Telegram access."""

from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode

import config
from utils.telegram_worker import CloudflareWorkerSession


def create_telegram_session() -> AiohttpSession:
    """Build the configured Telegram transport without changing Bale traffic.

    The old TELEGRAM_PROXY_URL remains backward compatible when no explicit
    TELEGRAM_API_MODE has been selected.
    """
    legacy_proxy = getattr(config, "TELEGRAM_PROXY_URL", None)
    mode = getattr(config, "TELEGRAM_API_MODE", None) or (
        "http_proxy" if legacy_proxy else "direct"
    )
    if mode == "direct":
        return AiohttpSession()
    if mode == "http_proxy":
        if not legacy_proxy:
            raise ValueError(
                "TELEGRAM_PROXY_URL is required for http_proxy mode."
            )
        return AiohttpSession(proxy=legacy_proxy)
    if mode == "cloudflare_worker":
        if legacy_proxy:
            raise ValueError(
                "TELEGRAM_PROXY_URL must be unset in cloudflare_worker mode."
            )
        return CloudflareWorkerSession(
            worker_url=getattr(config, "TELEGRAM_WORKER_URL", ""),
            relay_secret=getattr(config, "TELEGRAM_WORKER_SECRET", ""),
        )
    raise ValueError(
        "TELEGRAM_API_MODE must be direct, http_proxy, or cloudflare_worker."
    )


def create_bot(token: str, session: BaseSession | None = None) -> Bot:
    """Build an Aiogram Bot using the selected Telegram API transport."""
    session = session or create_telegram_session()
    return Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
