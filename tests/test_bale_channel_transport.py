"""Test Bale API payloads offline with an explicit fake HTTP client."""

import pytest

from channels.bale import BaleApiError, BaleTransport
from channels.contracts import BotReply, InlineAction


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
