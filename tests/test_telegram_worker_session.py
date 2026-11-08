"""Offline Aiogram 3.14 configuration and Cloudflare relay security tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiogram.methods import GetMe

import config
from utils.telegram import create_telegram_session
from utils.telegram_worker import (
    CloudflareWorkerSession,
    validate_worker_origin,
)

WORKER_ORIGIN = "https://my-relay.example.workers.dev"
SECRET = "a-fake-secret-containing-more-than-32-characters"
BOT_TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcd"
BOT_ID = "00000000-0000-4000-8000-000000000101"
VERSION = 1
RELAY_HEADERS = {
    "X-Relay-Bot-ID": BOT_ID,
    "X-Relay-Key": SECRET,
    "X-Relay-Version": str(VERSION),
}


@pytest.mark.parametrize(
    "url",
    [
        "http://relay.example.com",
        "https://relay.example.com/path",
        "https://relay.example.com?token=secret",
        "https://user:pass@relay.example.com",
        "https://relay.example.com/#fragment",
        "https://relay.example.com:8443",
        "https://",
        "",
    ],
)
def test_worker_origin_rejects_unsafe_urls(url: str) -> None:
    """Disallow HTTP URLs, credentials and embedded route/query tokens."""
    with pytest.raises(ValueError):
        validate_worker_origin(url)


def test_worker_origin_accepts_dynamic_https_hosts() -> None:
    """Choose the Worker host at runtime, not in source code."""
    assert validate_worker_origin(WORKER_ORIGIN + "/") == WORKER_ORIGIN


def test_factory_defaults_to_direct_telegram_api(monkeypatch) -> None:
    """Keep direct mode available with the original Telegram endpoints."""
    monkeypatch.setattr(config, "TELEGRAM_API_MODE", "direct", raising=False)
    monkeypatch.setattr(config, "TELEGRAM_PROXY_URL", None, raising=False)
    session = create_telegram_session()
    assert session.api.api_url(BOT_TOKEN, "getMe") == (
        f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
    )


def test_explicit_registry_route_enables_cloudflare_worker(monkeypatch) -> None:
    """Route API calls and file downloads through the dynamic Worker URL."""
    monkeypatch.setattr(config, "TELEGRAM_API_MODE", "cloudflare_worker", raising=False)
    monkeypatch.setattr(config, "TELEGRAM_WORKER_URL", WORKER_ORIGIN, raising=False)
    monkeypatch.setattr(config, "TELEGRAM_WORKER_SECRET", SECRET, raising=False)
    monkeypatch.setattr(config, "TELEGRAM_PROXY_URL", None, raising=False)
    session = CloudflareWorkerSession(
        WORKER_ORIGIN, SECRET, bot_id=BOT_ID, credential_version=VERSION,
    )
    assert isinstance(session, CloudflareWorkerSession)
    assert session.api.api_url(BOT_TOKEN, "getMe") == (
        f"{WORKER_ORIGIN}/bot{BOT_TOKEN}/getMe"
    )
    assert session.api.file_url(BOT_TOKEN, "photos/pic.jpg") == (
        f"{WORKER_ORIGIN}/file/bot{BOT_TOKEN}/photos/pic.jpg"
    )


def test_worker_mode_rejects_weak_keys_and_mixed_proxy_modes(monkeypatch) -> None:
    """Fail closed rather than silently exposing an unauthenticated relay."""
    with pytest.raises(ValueError):
        CloudflareWorkerSession(
            WORKER_ORIGIN, "short", bot_id=BOT_ID, credential_version=VERSION,
        )


class FakeBody:
    """Yield byte chunks without buffering or network I/O."""

    async def iter_chunked(self, size: int):
        """Yield one binary chunk to the caller."""
        assert size > 0
        yield b"binary-payload"


class FakeResponse:
    """A minimal aiohttp-compatible async context manager."""

    status = 200
    headers = {"content-type": "application/json"}

    def __init__(self) -> None:
        """Create a streamed response fixture."""
        self.content = FakeBody()

    async def __aenter__(self):
        """Open the response context."""
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        """Close the response context."""
        return False

    async def text(self) -> str:
        """Return a valid Bot API response."""
        return '{"ok": true, "result": {"id": 1}}'


class FakeClient:
    """Record outbound requests for authentication-leak regression tests."""

    def __init__(self) -> None:
        """Collect requests in execution order."""
        self.calls: list[tuple[str, str, dict]] = []

    def post(self, url: str, **kwargs):
        """Record a Telegram method and return a fake response."""
        self.calls.append(("POST", url, kwargs))
        return FakeResponse()

    def get(self, url: str, **kwargs):
        """Record a file download and return a fake response."""
        self.calls.append(("GET", url, kwargs))
        return FakeResponse()


@pytest.mark.asyncio
async def test_method_auth_header_is_scoped_to_worker(monkeypatch) -> None:
    """Authenticate a Telegram API POST without modifying global headers."""
    session = CloudflareWorkerSession(
        WORKER_ORIGIN, SECRET, bot_id=BOT_ID, credential_version=VERSION,
    )
    client = FakeClient()

    async def create_session():
        """Return a fake in-memory client."""
        return client

    monkeypatch.setattr(session, "create_session", create_session)
    monkeypatch.setattr(session, "build_form_data", lambda **kwargs: "form-data")
    monkeypatch.setattr(
        session,
        "check_response",
        lambda **kwargs: SimpleNamespace(result="ok"),
    )
    result = await session.make_request(
        SimpleNamespace(token=BOT_TOKEN), GetMe()
    )
    assert result == "ok"
    method, url, options = client.calls[0]
    assert method == "POST"
    assert url == f"{WORKER_ORIGIN}/bot{BOT_TOKEN}/getMe"
    assert options["headers"] == RELAY_HEADERS
    assert options["allow_redirects"] is False


@pytest.mark.asyncio
async def test_file_download_key_is_not_leaked_to_external_urls(monkeypatch) -> None:
    """Include the Worker key only for file URLs on the trusted origin."""
    session = CloudflareWorkerSession(
        WORKER_ORIGIN, SECRET, bot_id=BOT_ID, credential_version=VERSION,
    )
    client = FakeClient()

    async def create_session():
        """Return a fake in-memory client."""
        return client

    monkeypatch.setattr(session, "create_session", create_session)

    telegram_file = f"{WORKER_ORIGIN}/file/bot{BOT_TOKEN}/file.jpg"
    result = [
        part async for part in session.stream_content(telegram_file)
    ]
    assert result == [b"binary-payload"]
    worker_options = client.calls[-1][2]
    assert worker_options["headers"] == RELAY_HEADERS
    assert worker_options["allow_redirects"] is False

    result = [
        part async for part in session.stream_content(
            "https://cdn.example.org/file.jpg"
        )
    ]
    assert result == [b"binary-payload"]
    outside_options = client.calls[-1][2]
    assert not set(RELAY_HEADERS) & set(outside_options["headers"])


@pytest.mark.parametrize(
    "bot_id,version",
    [(None, None), ("not-a-uuid", 1), (BOT_ID, None), (BOT_ID, True), (BOT_ID, 0)],
)
def test_relay_requires_registered_uuid_and_explicit_key_version(bot_id, version):
    """No caller can construct the retired platform-wide relay auth scheme."""
    with pytest.raises(ValueError):
        CloudflareWorkerSession(
            WORKER_ORIGIN, SECRET, bot_id=bot_id, credential_version=version,
        )
