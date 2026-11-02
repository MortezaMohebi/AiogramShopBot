"""Offline Aiogram transport tests with a fake Bot object."""

import pytest

from channels.contracts import BotReply, InlineAction
from channels.telegram import TelegramTransport

# Native Aiogram type validation is part of the contract under CI.
pytest.importorskip("aiogram")


class RecordingBot:
    """Record outgoing Telegram calls without accessing the Bot API."""

    def __init__(self):
        """Start with an empty call history."""
        self.sent = []
        self.acknowledged = []

    async def send_message(self, **kwargs):
        """Capture a sent message and its reply markup."""
        self.sent.append(kwargs)

    async def answer_callback_query(self, **kwargs):
        """Capture a callback acknowledgement."""
        self.acknowledged.append(kwargs)


@pytest.mark.asyncio
async def test_telegram_uses_the_same_inline_buttons_as_bale():
    """Verify plain text, callbacks, and no inherited HTML formatting."""
    bot = RecordingBot()
    reply = BotReply(
        "محصولات فروشگاه",
        ((InlineAction("یک محصول", "shop:item:42"),),),
    )
    transport = TelegramTransport(bot)
    await transport.send(101, reply)
    assert len(bot.sent) == 1
    sent = bot.sent[0]
    assert sent["chat_id"] == 101
    assert sent["parse_mode"] is None
    assert sent["text"] == "محصولات فروشگاه"
    assert sent["reply_markup"].inline_keyboard[0][0].callback_data == (
        "shop:item:42"
    )
    await transport.acknowledge("cb-1")
    assert bot.acknowledged == [{"callback_query_id": "cb-1"}]
