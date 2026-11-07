"""Offline Aiogram transport tests with a fake Bot object."""

import pytest
from types import SimpleNamespace

from channels.contracts import BotReply, InlineAction, MediaAttachment
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


@pytest.mark.asyncio
async def test_product_preview_edits_existing_card_with_cached_file_id(monkeypatch):
    """Changing products replaces the card instead of posting another photo."""
    class CardBot(RecordingBot):
        """Provide the image edit API without a live provider."""

        token = "offline-token"

        async def edit_message_media(self, **kwargs):
            """Record one in-place image replacement."""
            self.sent.append(kwargs)
            return SimpleNamespace(
                message_id=77,
                photo=[SimpleNamespace(file_id="cached-photo")],
            )

    async def cached(**kwargs):
        """Use the current bot's already uploaded media."""
        return "cached-photo"

    monkeypatch.setattr("services.shop_media_delivery.cached_file_id", cached)
    bot = CardBot()
    reply = BotReply(
        "کرم\nقیمت: ۲۵۰ ریال\nموجودی: ۲",
        ((InlineAction("➕ افزودن", "shop:add:1"),),),
        preview=MediaAttachment("0" * 32 + ".jpg", "photo", "image/jpeg"),
    )
    assert await TelegramTransport(bot).send(101, reply, edit_message_id=77) == 77
    assert len(bot.sent) == 1
    assert bot.sent[0]["message_id"] == 77
    assert bot.sent[0]["media"].media == "cached-photo"


@pytest.mark.asyncio
async def test_main_keyboard_is_persistent_and_inline_actions_stay_on_screen():
    """The initial fixed keyboard coexists with contextual inline actions."""
    bot = RecordingBot()
    await TelegramTransport(bot).send(
        101,
        BotReply(
            "خوش آمدید",
            ((InlineAction("جستجو", "ux:search"),),),
            show_main_keyboard=True,
        ),
    )
    assert len(bot.sent) == 2
    assert bot.sent[0]["reply_markup"].keyboard[0][0].text == "🛍 فروشگاه"
    assert bot.sent[1]["reply_markup"].inline_keyboard[0][0].callback_data == "ux:search"
