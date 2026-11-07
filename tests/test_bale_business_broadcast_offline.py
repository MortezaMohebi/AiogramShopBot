"""Offline checks for Bale's explicitly paid Business broadcast transport."""

from __future__ import annotations

import pytest

import config
from channels.bale import BaleApiError, BaleTransport
from channels.contracts import BotReply, MediaAttachment
from tests.schema_support import TEST_BOT_IDS


class Response:
    """Minimal fake HTTP response returning Bale's documented JSON envelope."""

    status = 200

    async def __aenter__(self):
        """Return the fake response."""
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Close without changing exception propagation."""
        return False

    async def json(self, content_type=None):
        """Return a successful Bale message without a network connection."""
        return {"ok": True, "result": {"message_id": 1}}


class RecordingSession:
    """Capture the target API origin and payload, never dispatch anything."""

    def __init__(self) -> None:
        """Start an empty request log."""
        self.calls = []

    def post(self, url, **kwargs):
        """Capture JSON API calls and return the fake response."""
        self.calls.append((url, kwargs))
        return Response()


@pytest.mark.asyncio
async def test_regular_and_paid_bale_endpoints_are_separate() -> None:
    """Do not charge Business API requests in ordinary broadcast mode."""
    token = "222222:BBBBBBBBBBBBBBBBBBBBBBBBBBB"
    session = RecordingSession()
    regular = BaleTransport(token, session, bot_id=TEST_BOT_IDS["bale"])
    paid = BaleTransport(
        token, session, business_mode=True, bot_id=TEST_BOT_IDS["bale"]
    )

    await regular.send(123, BotReply("متن معمولی"))
    await paid.send(123, BotReply("متن کمپین پولی"))

    assert session.calls[0][0] == (
        f"https://tapi.bale.ai/bot{token}/sendMessage"
    )
    assert session.calls[1][0] == (
        f"https://tapi.bale.ai/business/bot{token}/sendMessage"
    )


@pytest.mark.asyncio
async def test_paid_media_requires_existing_file_id_before_dispatch(
    monkeypatch, tmp_path
) -> None:
    """Business endpoints cannot receive multipart files or URLs."""
    monkeypatch.setattr(config, "SHOP_MEDIA_ROOT", str(tmp_path))
    key = "d" * 32 + ".png"
    (tmp_path / key).write_bytes(b"\x89PNG\r\n\x1a\n" + b"data")
    session = RecordingSession()
    paid = BaleTransport(
        "222222:BBBBBBBBBBBBBBBBBBBBBBBBBBB",
        session,
        business_mode=True,
        bot_id=TEST_BOT_IDS["bale"],
    )

    async def cache_miss(**kwargs):
        """Assert the lookup stays within this registered bot namespace."""
        assert kwargs["bot_id"] == TEST_BOT_IDS["bale"]
        assert kwargs["platform"] == "bale"
        return None

    monkeypatch.setattr(
        "services.shop_media_delivery.cached_file_id",
        cache_miss,
    )
    with pytest.raises(BaleApiError, match="requires a cached file_id"):
        await paid.send_media(
            123,
            MediaAttachment(
                storage_key=key,
                kind="photo",
                mime_type="image/png",
            ),
        )
    assert session.calls == []
