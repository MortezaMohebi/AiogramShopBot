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
    assert bot.sent[0]["text"] == "🛍 فروشگاه"
    assert bot.sent[0]["reply_markup"].keyboard[0][0].text == "🛍 فروشگاه"
    assert bot.sent[1]["reply_markup"].inline_keyboard[0][0].callback_data == "ux:search"


@pytest.mark.asyncio
async def test_catalog_page_sends_four_photo_cards_with_independent_actions(monkeypatch):
    """Show multiple cover images without requiring a next-product tap."""
    class CardBot(RecordingBot):
        """Record photo cards, footer, and superseded controls offline."""

        token = "offline-token"

        def __init__(self):
            """Track all outgoing calls in delivery order."""
            super().__init__()
            self.calls = []

        async def edit_message_reply_markup(self, **kwargs):
            """Record the previous navigation message being disabled."""
            self.calls.append(("clear", kwargs))

        async def send_photo(self, **kwargs):
            """Confirm each card as a separate photo with its own actions."""
            self.calls.append(("photo", kwargs))
            return SimpleNamespace(
                message_id=80 + len(self.calls),
                photo=[SimpleNamespace(file_id="cached-photo")],
            )

        async def send_message(self, **kwargs):
            """Confirm the footer and its next-page action."""
            self.calls.append(("text", kwargs))
            return SimpleNamespace(message_id=99)

    async def cached(**kwargs):
        """Avoid reading product media from local disk in this test."""
        return "cached-photo"

    monkeypatch.setattr("services.shop_media_delivery.cached_file_id", cached)
    cards = tuple(
        BotReply(
            f"محصول {index}\nقیمت: {index * 100:,} ریال",
            ((InlineAction("جزئیات محصول", f"shop:item:{index}"),),),
            preview=MediaAttachment(f"{index:032x}.jpg", "photo", "image/jpeg"),
        )
        for index in range(1, 5)
    )
    page = BotReply(
        "محصولات ۱ تا ۴",
        ((InlineAction("۴ محصول دیگر", "shop:list:1"),),),
        cards=cards,
    )

    bot = CardBot()
    result = await TelegramTransport(bot).send(101, page, edit_message_id=77)

    assert result == 99
    assert [kind for kind, _ in bot.calls] == [
        "clear", "photo", "photo", "photo", "photo", "text",
    ]
    assert bot.calls[0][1]["message_id"] == 77
    assert bot.calls[0][1]["reply_markup"] is None
    for index, (_, payload) in enumerate(bot.calls[1:5], 1):
        assert payload["caption"].startswith(f"محصول {index}")
        assert payload["reply_markup"].inline_keyboard[0][0].callback_data == (
            f"shop:item:{index}"
        )
    assert bot.calls[-1][1]["reply_markup"].inline_keyboard[0][0].callback_data == (
        "shop:list:1"
    )


@pytest.mark.asyncio
async def test_catalog_page_does_not_confirm_partial_delivery():
    """A failed card prevents the page footer from claiming completion."""
    class FailingBot(RecordingBot):
        """Fail the second product send after one card succeeded."""

        def __init__(self):
            """Track whether page navigation was published."""
            super().__init__()
            self.attempts = 0

        async def send_message(self, **kwargs):
            """Reject the second card before a footer can be sent."""
            self.attempts += 1
            if self.attempts == 2:
                raise RuntimeError("provider unavailable")
            self.sent.append(kwargs)
            return SimpleNamespace(message_id=10)

    bot = FailingBot()
    reply = BotReply(
        "صفحه ۱", cards=(BotReply("کالا ۱"), BotReply("کالا ۲")),
    )
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await TelegramTransport(bot).send(101, reply)
    assert bot.attempts == 2
    assert all(item["text"] != "صفحه ۱" for item in bot.sent)
