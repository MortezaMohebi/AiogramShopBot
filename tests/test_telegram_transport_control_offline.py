"""Offline tests for safe Telegram Direct/Proxy/Worker transport management.

No real bot token, provider calls, server sockets, or Telegram message sends
are involved. Encrypted settings and session replacement are exercised using
the production classes and disposable in-memory SQLAlchemy objects.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest
from aiogram.client.session.base import BaseSession
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import config
from models.base import Base
from models.shop_admin_control import AdminEvent
from models.shop_staff import ShopStaff
from models.shop_telegram_transport import (
    ShopTelegramTransport,
    ShopTelegramTransportChange,
)
from services import shop_admin_security as security
from services import shop_telegram_transport as transport
from services import shop_telegram_transport_control as control
from utils.telegram_rotating_session import RotatingTelegramSession


@pytest.fixture
def policy(monkeypatch):
    """Provide stable approved destinations and an isolated encryption key."""
    monkeypatch.setenv(
        "SHOP_SECURITY_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.setenv(
        "TELEGRAM_PROXY_ALLOWED_ENDPOINTS",
        "socks5://proxy.example.net:1080,http://proxy.example.net:3128",
    )
    monkeypatch.setenv(
        "TELEGRAM_WORKER_ALLOWED_ORIGINS",
        "https://my-relay.example.net",
    )
    monkeypatch.setattr(config, "TELEGRAM_PROXY_URL", "")
    monkeypatch.setattr(config, "TELEGRAM_WORKER_URL", "")
    monkeypatch.setattr(config, "TELEGRAM_API_MODE", "direct")
    return transport.TelegramTransportSpec(mode="direct")


def test_encrypted_worker_secret_and_redacted_status(policy) -> None:
    """No Worker relay credential appears in the saved or returned metadata."""
    secret = "sample-relay-key-not-a-real-secret-123456789"
    worker = transport.TelegramTransportSpec(
        mode="cloudflare_worker",
        worker_url="https://my-relay.example.net",
        worker_secret=secret,
    )
    encrypted = transport.encrypted(worker)
    assert secret not in encrypted
    assert "my-relay.example.net" not in encrypted
    restored = transport.decrypted(encrypted)
    assert restored == worker
    exposed = transport.public_data(
        restored, version=2, source="database",
    )
    assert exposed["has_worker_secret"] is True
    assert secret not in repr(exposed)
    assert exposed["worker_url"] == worker.worker_url


def test_proxy_password_kept_only_at_same_endpoint(policy) -> None:
    """A masked password is reused only when the approved endpoint is unchanged."""
    old = transport.TelegramTransportSpec(
        mode="http_proxy",
        proxy_url="socks5://proxy.example.net:1080",
        proxy_username="operator",
        proxy_password="secret-proxy-password",
    )
    same = transport.from_submission({
        "mode": "http_proxy",
        "proxy_url": old.proxy_url,
        "proxy_username": "operator",
        "proxy_password": "",
    }, old)
    assert same.proxy_password == old.proxy_password
    with pytest.raises(security.SecurityRejected) as refused:
        transport.from_submission({
            "mode": "http_proxy",
            "proxy_url": "http://proxy.example.net:3128",
            "proxy_username": "operator",
            "proxy_password": "",
        }, old)
    assert refused.value.code == "invalid_proxy_credentials"


def test_arbitrary_relay_and_local_proxy_are_rejected(policy) -> None:
    """Dashboard-admin input cannot redirect bot tokens to unknown relay URLs."""
    for url in (
        "https://unknown-relay.example.net",
        "http://my-relay.example.net",
        "https://my-relay.example.net:8443",
        "https://my-relay.example.net/path",
    ):
        with pytest.raises(security.SecurityRejected):
            transport.from_submission({
                "mode": "cloudflare_worker",
                "worker_url": url,
                "worker_secret": "A" * 40,
            }, policy)
    with pytest.raises(security.SecurityRejected):
        transport.from_submission({
            "mode": "http_proxy",
            "proxy_url": "http://127.0.0.1:8080",
        }, policy)


def test_credential_reuse_and_missing_secret(policy) -> None:
    """A Worker secret cannot be silently copied to a different origin."""
    previous = transport.TelegramTransportSpec(
        mode="cloudflare_worker",
        worker_url="https://my-relay.example.net",
        worker_secret="S" * 44,
    )
    same = transport.from_submission({
        "mode": "cloudflare_worker",
        "worker_url": previous.worker_url,
        "worker_secret": "",
    }, previous)
    assert same.worker_secret == previous.worker_secret
    with pytest.raises(security.SecurityRejected) as denied:
        transport.from_submission({
            "mode": "cloudflare_worker",
            "worker_url": previous.worker_url,
            "worker_secret": "",
        }, policy)
    assert denied.value.code == "invalid_worker_secret"


def test_invalid_key_cannot_silently_fallback(policy, monkeypatch) -> None:
    """Bad ciphertext fails closed rather than switching back to Deployment."""
    saved = transport.encrypted(transport.TelegramTransportSpec(mode="direct"))
    monkeypatch.setenv(
        "SHOP_SECURITY_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    with pytest.raises(security.SecurityRejected) as denied:
        transport.decrypted(saved)
    assert denied.value.code == "transport_config_unreadable"


class FakeSession(BaseSession):
    """Test delegate with no HTTP traffic and controlled in-flight requests."""

    def __init__(self, identity: str, release: asyncio.Event | None = None):
        """Build an in-memory BaseSession with standard API path metadata."""
        super().__init__()
        self.identity = identity
        self.release = release
        self.started = asyncio.Event()
        self.is_closed = False

    async def make_request(self, bot, method, timeout=None):
        """Wait for an explicit test release before returning."""
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        return self.identity

    async def stream_content(
        self,
        url: str,
        headers: dict | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        """Provide a single in-memory byte chunk."""
        yield self.identity.encode("ascii")

    async def close(self) -> None:
        """Mark the underlying test delegate closed."""
        self.is_closed = True


@pytest.mark.asyncio
async def test_session_swap_drains_in_flight_requests() -> None:
    """The old transport cannot close while a live request is using it."""
    release = asyncio.Event()
    old = FakeSession("direct", release)
    new = FakeSession("worker")
    managed = RotatingTelegramSession(old)

    request = asyncio.create_task(managed.make_request(None, None))
    await asyncio.wait_for(old.started.wait(), timeout=1)
    switch = asyncio.create_task(
        managed.replace(new, fingerprint="verified-worker"),
    )
    await asyncio.sleep(0)
    assert not switch.done()
    release.set()

    assert await asyncio.wait_for(request, timeout=1) == "direct"
    retired = await asyncio.wait_for(switch, timeout=1)
    assert retired is old
    assert old.is_closed is False
    assert managed.fingerprint == "verified-worker"
    assert await managed.make_request(None, None) == "worker"
    await retired.close()
    await managed.close()
    assert new.is_closed is True


def test_staging_keeps_verification_state_only_in_db(policy, monkeypatch) -> None:
    """Only opaque receipts and Fernet ciphertext are persisted on stage."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        ShopStaff.__table__,
        AdminEvent.__table__,
        ShopTelegramTransport.__table__,
        ShopTelegramTransportChange.__table__,
    ])

    class Db:
        """Provide the AsyncSession methods used by the staging state machine."""

        def __init__(self, sync: Session):
            """Reuse an isolated SQLite transaction."""
            self.sync = sync

        async def scalar(self, statement):
            """Return SQLAlchemy scalars without an external database."""
            return self.sync.scalar(statement)

        async def get(self, model, key, **options):
            """Return a mapped object."""
            return self.sync.get(model, key, **options)

        async def run_sync(self, function):
            """Invoke production synchronous audit logic."""
            return function(self.sync)

        async def commit(self):
            """Persist only disposable test metadata."""
            self.sync.commit()

        def add(self, row):
            """Attach the given ORM record."""
            self.sync.add(row)

    async def no_advisory_lock(_db):
        """SQLite has no PostgreSQL advisory lock in this isolated test."""

    monkeypatch.setattr(control, "_lease", no_advisory_lock)
    with Session(engine) as session:
        session.add(ShopStaff(
            id=1, username="owner", password_hash="unused",
            role="superadmin", session_version=1, is_active=True,
        ))
        session.commit()

        async def exercise():
            """Stage and cancel an encrypted candidate without applying it."""
            db = Db(session)
            row = await control.stage(
                db, actor_id=1, version=1,
                values={"mode": "cloudflare_worker", "worker_url":
                        "https://my-relay.example.net", "worker_secret": "Q" * 40},
            )
            assert row.status == "pending"
            assert "Q" * 40 not in row.proposed_ciphertext
            assert session.get(ShopTelegramTransport, 1) is None
            await control.cancel(
                db, actor_id=1, change_id=row.id,
            )
            assert row.status == "cancelled"

        asyncio.run(exercise())
    engine.dispose()
