"""First-owner and email setup contract without provider credentials."""

import base64

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models.shop_multibot import DEFAULT_STORE_ID, ShopStore
from models.shop_staff import ShopStaff
from models.shop_staff_store import ShopStaffStoreAccess
from scripts.codespace_bootstrap import safe_configuration
from scripts.first_owner_setup import create_first_owner
from services.shop_email_templates import render_email
from services.shop_smtp import configured_settings, send_email
from tests.schema_support import create_shop_schema


def test_browser_setup_code_expires_and_cannot_be_forged():
    """Only a code issued with the installation secret opens first-run setup."""
    from scripts.first_owner_setup import issue_browser_code, verify_browser_code

    secret = "synthetic-installation-secret-" * 2
    issued = 1_800_000_000
    code = issue_browser_code(secret, now=issued)
    assert verify_browser_code(secret, code, now=issued + 899)
    assert not verify_browser_code(secret, code, now=issued + 900)
    assert not verify_browser_code(secret, code, now=issued - 1)
    assert not verify_browser_code(secret + "other", code, now=issued)
    assert not verify_browser_code(secret, code.replace(str(issued), str(issued + 1)),
                                   now=issued + 1)
    assert not verify_browser_code("", code, now=issued)


@pytest.mark.asyncio
async def test_browser_setup_requires_signed_bridge_and_closes_after_creation(monkeypatch):
    """Exercise the real setup endpoint without a configured server."""
    import json
    import time

    import httpx
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import config
    from dashboard.admin_control_api import router
    from dashboard.admin_control_app import create_app
    from dashboard.next_api import database
    from scripts.first_owner_setup import issue_browser_code
    from tests.test_next_admin_bridge import SECRET, signed

    monkeypatch.setattr(config, "NEXT_ADMIN_BRIDGE_ENABLED", True)
    monkeypatch.setattr(config, "NEXT_ADMIN_BRIDGE_SECRET", SECRET)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(create_shop_schema)
        async with sessions.begin() as db:
            db.add(ShopStore(id=DEFAULT_STORE_ID, slug="default", name="Store", state="active"))

        async def isolated_db():
            async with sessions() as session:
                yield session

        base = FastAPI()
        base.include_router(router)
        app = create_app(base)
        app.dependency_overrides[database] = isolated_db
        target = "/internal/admin/v1/auth/owner-setup"

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://offline.test",
        ) as client:
            async def request(method, payload=None):
                body = json.dumps(payload).encode() if payload is not None else b""
                stamp = str(int(time.time()))
                headers = {
                    "content-type": "application/json", "x-shop-time": stamp,
                    "x-shop-staff": "0", "x-shop-version": "0",
                    "x-shop-signature": signed(method=method, path=target, body=body,
                                               user_id=0, version=0, stamp=stamp),
                }
                return await client.request(method, target, content=body, headers=headers)

            payload = {
                "username": "browser.owner", "password": "synthetic-password-long-enough",
                "setup_code": issue_browser_code(SECRET),
            }
            assert (await client.get(target)).status_code == 401
            assert (await client.post(target, json=payload)).status_code == 401
            assert (await request("GET")).json() == {"pending": True}
            rejected = await request("POST", payload | {"setup_code": "0" * 75})
            assert rejected.json() == {"detail": "invalid_setup_code"}
            created = await request("POST", payload)
            assert created.status_code == 201 and created.json() == {"ok": True}
            assert (await request("GET")).json() == {"pending": False}
            assert (await request("POST", payload)).status_code == 409
    finally:
        await engine.dispose()


def test_fresh_bootstrap_does_not_require_an_admin_password(monkeypatch):
    """Schema initialization cannot create a hardcoded dashboard user."""
    from scripts.codespace_bootstrap import REQUIRED

    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("LIVE_ADMIN_PASSWORD", raising=False)
    safe_configuration()


def test_owner_chooses_username_once_and_receives_store_grant():
    """An occupied staff table cannot be taken over by another setup call."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_shop_schema(engine)
    with Session(engine) as db:
        db.add(ShopStore(id=DEFAULT_STORE_ID, slug="default", name="Store", state="active"))
        db.flush()
        owner = create_first_owner(db, "my.owner", "A-long-private-password-123!")
        db.commit()
        assert owner.username == "my.owner" and owner.role == "superadmin"
        assert db.scalar(select(ShopStaffStoreAccess).where(
            ShopStaffStoreAccess.staff_id == owner.id,
            ShopStaffStoreAccess.store_id == DEFAULT_STORE_ID,
        )).access_level == "manager"
        with pytest.raises(ValueError, match="already initialized"):
            create_first_owner(db, "second.owner", "Another-private-password-123!")
        assert db.scalar(select(ShopStaff).where(ShopStaff.username == "second.owner")) is None
    engine.dispose()


def test_email_templates_escape_user_content_and_reject_unknown_names():
    """Email links and names cannot inject HTML or additional headers."""
    message = render_email("invite", recipient="<Admin>", link="https://example.test/activate?t=a&b=1")
    assert "&lt;Admin&gt;" in message.html
    assert "&amp;b=1" in message.html
    assert "<Admin>" not in message.html
    with pytest.raises(ValueError):
        render_email("unknown", recipient="Admin", link="https://example.test")
    for kind in ("reset", "mfa_notice", "smtp_test"):
        rendered = render_email(
            kind, recipient="مدیر",
            link="https://example.test/activate" if kind == "reset" else "",
        )
        assert rendered.subject and rendered.plain and 'dir="rtl"' in rendered.html


def test_smtp_remains_off_until_complete_tls_configuration(monkeypatch):
    """SMTP secrets are decoded only from a protected private environment."""
    for name in ("HOST", "PORT", "USERNAME", "PASSWORD_B64", "SENDER", "SECURITY"):
        monkeypatch.delenv("SHOP_SMTP_" + name, raising=False)
    assert configured_settings() is None
    values = {
        "HOST": "smtp.example.test", "PORT": "587", "SECURITY": "starttls",
        "USERNAME": "owner@example.test", "SENDER": "owner@example.test",
        "PASSWORD_B64": base64.b64encode(b"secret-with-$-character").decode(),
    }
    for name, value in values.items():
        monkeypatch.setenv("SHOP_SMTP_" + name, value)
    settings = configured_settings()
    assert settings.password == "secret-with-$-character"
    monkeypatch.setenv("SHOP_SMTP_SECURITY", "plain")
    with pytest.raises(ValueError):
        configured_settings()


def test_smtp_uses_starttls_before_authentication(monkeypatch):
    """A transactional message authenticates only after TLS is established."""
    from services import shop_smtp

    events = []

    class FakeSmtp:
        """Record SMTP calls without opening a network connection."""

        def __init__(self, *args, **kwargs):
            events.append("connect")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            events.append("ehlo")

        def starttls(self, **kwargs):
            assert kwargs["context"] is not None
            events.append("starttls")

        def login(self, username, password):
            events.append("login")

        def send_message(self, message):
            assert message["To"] == "admin@example.test"
            assert message.is_multipart()
            events.append("send")

    monkeypatch.setattr(shop_smtp.smtplib, "SMTP", FakeSmtp)
    settings = shop_smtp.SmtpSettings(
        host="smtp.example.test", port=587, security="starttls",
        username="account", password="secret", sender="sender@example.test",
    )
    send_email(
        settings, "admin@example.test",
        render_email("smtp_test", recipient="admin@example.test"),
    )
    assert events == ["connect", "ehlo", "starttls", "ehlo", "login", "send"]
    with pytest.raises(ValueError):
        send_email(settings, "admin@example.test\r\nBcc: attacker@example.test",
                   render_email("smtp_test", recipient="admin"))


def test_fresh_codespace_secret_file_has_no_administrator(monkeypatch, tmp_path):
    """Creating service secrets never seeds a staff identity or password."""
    from scripts import codespace_setup

    monkeypatch.setattr(codespace_setup, "PRIVATE_DIR", tmp_path / "private")
    monkeypatch.setattr(codespace_setup, "ENV_FILE", tmp_path / "private" / "live.env")
    monkeypatch.setenv("CODESPACE_NAME", "owner-test-codespace")
    codespace_setup.init()
    saved = codespace_setup.read_env()
    assert not any("ADMIN_PASSWORD" in key or "ADMIN_USERNAME" in key for key in saved)
    assert codespace_setup.ENV_FILE.stat().st_mode & 0o077 == 0


def test_codespace_smtp_setup_keeps_password_private(monkeypatch, tmp_path):
    """The interactive SMTP setup writes a restricted file, not a plaintext password."""
    from scripts import codespace_setup

    monkeypatch.setattr(codespace_setup, "PRIVATE_DIR", tmp_path / "private")
    monkeypatch.setattr(codespace_setup, "ENV_FILE", tmp_path / "private" / "live.env")
    monkeypatch.setenv("CODESPACE_NAME", "smtp-test-codespace")
    codespace_setup.init()
    answers = iter(("smtp.example.test", "587", "starttls",
                    "owner@example.test", "sender@example.test"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(codespace_setup.getpass, "getpass", lambda _prompt: "secret-$value")
    codespace_setup.configure_smtp()
    content = codespace_setup.ENV_FILE.read_text()
    assert "secret-$value" not in content
    assert "LIVE_SMTP_PASSWORD_B64=" in content
    assert codespace_setup.ENV_FILE.stat().st_mode & 0o077 == 0
