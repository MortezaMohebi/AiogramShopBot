"""Construct Telegram clients with an explicit caller-owned transport."""

from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode

def create_telegram_session() -> AiohttpSession:
    """Create a direct transport; registered relay routes are resolved per bot."""
    return AiohttpSession()


def create_bot(token: str, session: BaseSession | None = None) -> Bot:
    """Build an Aiogram Bot using the selected Telegram API transport."""
    session = session or create_telegram_session()
    return Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
