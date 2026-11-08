from types import SimpleNamespace

import pytest

from utils.telegram import create_telegram_session, create_bot


def test_create_telegram_session_without_proxy(monkeypatch):
    monkeypatch.setattr("config.TELEGRAM_PROXY_URL", None)

    session = create_telegram_session()

    assert session._proxy is None


def test_environment_proxy_cannot_select_a_registry_transport(monkeypatch):
    """Global environment settings never override per-bot Registry routing."""
    monkeypatch.setenv("TELEGRAM_PROXY_URL", "socks5://192.168.1.1:10808")
    monkeypatch.setenv("TELEGRAM_API_MODE", "cloudflare_worker")
    session = create_telegram_session()
    assert session._proxy is None


def test_create_bot_uses_direct_session_by_default(monkeypatch):
    fake_session = SimpleNamespace()
    captured = {}

    class _FakeBot:
        def __init__(self, token, session, default):
            captured["token"] = token
            captured["session"] = session
            captured["default"] = default

    monkeypatch.setattr("utils.telegram.create_telegram_session", lambda: fake_session)
    monkeypatch.setattr("utils.telegram.Bot", _FakeBot)

    create_bot("123:ABC")

    assert captured["token"] == "123:ABC"
    assert captured["session"] is fake_session
