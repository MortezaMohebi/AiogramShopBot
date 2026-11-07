"""Test Bale API payloads offline with an explicit fake HTTP client."""

import pytest

from channels.bale import BaleApiError, BaleTransport
from channels.contracts import BotReply, InlineAction, MediaAttachment


class FakeResponse:
    """Simulate a single async aiohttp response."""

    def __init__(self, payload, status=200):
        """Store response envelope and HTTP status."""
        self.payload = payload
        self.status = status

    async def __aenter__(self):
        """Enter a response context."""
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        """Exit the response context."""
        return False

    async def json(self, content_type=None):
        """Return a previously prepared response envelope."""
        return self.payload


class FakeSession:
    """Record requests without issuing real network traffic."""

    def __init__(self, response):
        """Initialize a response fixture."""
        self.response = response
        self.calls = []

    def post(self, url, json, timeout):
        """Capture the outgoing request and return a fake response."""
        self.calls.append((url, json))
        return self.response


@pytest.mark.asyncio
async def test_bale_send_message_uses_inline_keyboard():
    """Verify parity with the shared inline keyboard contract."""
    session = FakeSession(FakeResponse({"ok": True, "result": {}}))
    transport = BaleTransport("test-token", session)
    reply = BotReply(
        "فهرست محصولات",
        ((InlineAction("محصول", "shop:item:10"),),),
    )
    await transport.send(101, reply)
    endpoint, body = session.calls[0]
    assert endpoint.endswith("/sendMessage")
    assert body["text"] == "فهرست محصولات"
    assert body["reply_markup"]["inline_keyboard"][0][0] == {
        "text": "محصول", "callback_data": "shop:item:10"
    }


@pytest.mark.asyncio
async def test_bale_installs_main_keyboard_and_edits_inline_navigation():
    """Keep global routes in the reply keyboard and page actions inline."""
    session = FakeSession(FakeResponse({
        "ok": True, "result": {"message_id": 12},
    }))
    transport = BaleTransport("test-token", session)
    reply = BotReply(
        "فروشگاه", ((InlineAction("بعدی", "shop:list:1"),),),
        show_main_keyboard=True,
    )
    await transport.send(101, reply)
    assert session.calls[0][0].endswith("/sendMessage")
    assert session.calls[0][1]["reply_markup"]["keyboard"][0][0]["text"] == "🛍 فروشگاه"
    assert session.calls[1][1]["reply_markup"]["inline_keyboard"][0][0]["text"] == "بعدی"

    session.calls.clear()
    result = await transport.send(101, BotReply("صفحهٔ بعد"), edit_message_id=12)
    assert result == 12
    assert len(session.calls) == 1
    assert session.calls[0][0].endswith("/editMessageText")
    assert session.calls[0][1]["message_id"] == 12


@pytest.mark.asyncio
async def test_bale_catalog_sends_four_photo_cards_before_page_controls(monkeypatch):
    """Show several products without losing their individual detail buttons."""
    session = FakeSession(FakeResponse({
        "ok": True, "result": {"message_id": 98},
    }))
    transport = BaleTransport("test-token", session)

    async def fake_send_media(chat_id, media, *, reply_markup=None):
        """Record a photo card in sequence with the fake HTTP requests."""
        session.calls.append(("photo", {
            "chat_id": chat_id, "caption": media.caption,
            "reply_markup": reply_markup,
        }))
        return 97

    monkeypatch.setattr(transport, "send_media", fake_send_media)
    cards = tuple(BotReply(
        f"محصول {index}",
        ((InlineAction("جزئیات", f"shop:item:{index}"),),),
        preview=MediaAttachment(f"cover-{index}", "photo", "image/jpeg"),
    ) for index in range(1, 5))
    reply = BotReply(
        "صفحه ۱ از ۲", ((InlineAction("۴ محصول دیگر", "shop:list:1"),),),
        cards=cards,
    )

    result = await transport.send(101, reply, edit_message_id=21)

    assert result == 98
    assert session.calls[0][0].endswith("/editMessageReplyMarkup")
    assert session.calls[0][1]["message_id"] == 21
    assert [method for method, _ in session.calls[1:5]] == ["photo"] * 4
    for index, (_, payload) in enumerate(session.calls[1:5], start=1):
        assert payload["chat_id"] == 101
        assert payload["caption"] == f"محصول {index}"
        assert payload["reply_markup"]["inline_keyboard"][0][0] == {
            "text": "جزئیات", "callback_data": f"shop:item:{index}",
        }
    assert session.calls[5][0].endswith("/sendMessage")
    assert session.calls[5][1]["reply_markup"]["inline_keyboard"][0][0] == {
        "text": "۴ محصول دیگر", "callback_data": "shop:list:1",
    }
    assert len(session.calls) == 6


@pytest.mark.asyncio
async def test_bale_catalog_keeps_product_without_cover_selectable():
    """Render a text card when a published product has no cover photo."""
    session = FakeSession(FakeResponse({
        "ok": True, "result": {"message_id": 31},
    }))
    transport = BaleTransport("test-token", session)
    card = BotReply(
        "محصول بدون عکس",
        ((InlineAction("جزئیات", "shop:item:42"),),),
    )

    result = await transport.send(101, BotReply("صفحه ۱", cards=(card,)))

    assert result == 31
    assert [url.rsplit("/", 1)[-1] for url, _ in session.calls] == [
        "sendMessage", "sendMessage",
    ]
    assert session.calls[0][1]["text"] == "محصول بدون عکس"
    assert session.calls[0][1]["reply_markup"]["inline_keyboard"][0][0] == {
        "text": "جزئیات", "callback_data": "shop:item:42",
    }
    assert session.calls[1][1]["text"] == "صفحه ۱"


@pytest.mark.asyncio
async def test_bale_catalog_does_not_confirm_partial_delivery():
    """A rejected card cannot publish a successful page footer."""
    session = FakeSession(FakeResponse({
        "ok": False, "error_code": 429,
    }, status=429))
    transport = BaleTransport("test-token", session)
    page = BotReply("صفحه ۱", cards=(BotReply("کالا ۱"),))
    with pytest.raises(BaleApiError):
        await transport.send(101, page)
    assert len(session.calls) == 1
    assert session.calls[0][1]["text"] == "کالا ۱"


@pytest.mark.asyncio
async def test_bale_legacy_callback_does_not_use_unsupported_ack():
    """Preserve compatibility with Bale clients whose IDs start with 1."""
    session = FakeSession(FakeResponse({"ok": True, "result": True}))
    transport = BaleTransport("test-token", session)
    await transport.acknowledge("123456")
    assert session.calls == []
    await transport.acknowledge("987654")
    assert session.calls[-1][0].endswith("/answerCallbackQuery")


@pytest.mark.asyncio
async def test_bale_error_does_not_leak_secret_token():
    """Ensure client-facing and loggable errors omit credential-bearing URLs."""
    session = FakeSession(
        FakeResponse({"ok": False, "error_code": 429}, status=429)
    )
    transport = BaleTransport("sensitive-token", session)
    with pytest.raises(BaleApiError) as exc:
        await transport.send(101, BotReply("سلام"))
    assert "sensitive-token" not in str(exc.value)


def test_callback_payload_size_is_bounded_in_utf8_bytes():
    """Apply the documented 64-byte callback limit to Persian labels."""
    with pytest.raises(ValueError):
        InlineAction("نمونه", "x" * 65)
