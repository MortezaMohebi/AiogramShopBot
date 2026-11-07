"""Offline P5 acceptance for multiple bots, Worker routes and safe failover.

All tests use disposable SQLite data and fake network transports. No live
Cloudflare, Telegram, PostgreSQL service, Redis or payment is contacted.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramNetworkError
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models.base import Base
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot, ShopStore
from models.shop_relay_pool import (
    ShopBotRelayRoute, ShopRelayCredential, ShopRelayEvent, ShopRelayWorker,
)
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_relay_pool as pool
from services.shop_relay_routing import RelayPoolTelegramSession

BOT_A = str(uuid4())
BOT_B = str(uuid4())
ORIGIN_A = "https://relay-a.example.workers.dev"
ORIGIN_B = "https://relay-b.example.workers.dev"
SECRET_A = "A" * 48
SECRET_B = "B" * 48


class AsyncDb:
    """Provide local asynchronous API shapes around disposable ORM sessions."""

    def __init__(self, session: Session) -> None:
        """Hold the synchronous in-memory database."""
        self.session = session

    def add(self, record) -> None:
        """Stage an isolated ORM record."""
        self.session.add(record)

    async def get(self, model, key, **kwargs):
        """Read a local row."""
        return self.session.get(model, key, **kwargs)

    async def scalar(self, statement):
        """Evaluate a local scalar query."""
        return self.session.scalar(statement)

    async def scalars(self, statement):
        """Return a local scalar result."""
        return self.session.scalars(statement)

    async def execute(self, statement):
        """Execute a local SQLAlchemy statement."""
        return self.session.execute(statement)

    async def flush(self) -> None:
        """Flush staged rows in the current transaction."""
        self.session.flush()

    async def commit(self) -> None:
        """Commit the disposable transaction."""
        self.session.commit()

    async def rollback(self) -> None:
        """Rollback the disposable transaction."""
        self.session.rollback()


@pytest.fixture
def db(monkeypatch):
    """Make two isolated Telegram bots with a nonproduction crypto key."""
    monkeypatch.setenv(
        "SHOP_SECURITY_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.delenv("SHOP_BOT_SECRET_KEY", raising=False)
    monkeypatch.setenv(
        "TELEGRAM_WORKER_ALLOWED_ORIGINS",
        f"{ORIGIN_A},{ORIGIN_B}",
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        ShopStaff.__table__,
        ShopStore.__table__,
        ShopBot.__table__,
        ShopRelayWorker.__table__,
        ShopBotRelayRoute.__table__,
        ShopRelayCredential.__table__,
        ShopRelayEvent.__table__,
    ])
    with Session(engine) as session:
        session.add(ShopStaff(
            id=1, username="owner", password_hash="fixture-only",
            role="superadmin", is_active=True, session_version=1,
        ))
        session.add(ShopStore(
            id=DEFAULT_STORE_ID, slug="default",
            name="Offline shop", state="active",
        ))
        for bot_id, slug, provider_id in (
            (BOT_A, "telegram-a", 201),
            (BOT_B, "telegram-b", 202),
        ):
            session.add(ShopBot(
                id=bot_id, store_id=DEFAULT_STORE_ID, slug=slug,
                name=slug, platform="telegram",
                provider_bot_id=provider_id,
                verified_at=datetime.now(timezone.utc),
                runtime_owner="registry", status="active",
                credential_version=1,
            ))
        session.commit()
        yield AsyncDb(session)
    engine.dispose()


async def _worker(db: AsyncDb, slug: str, origin: str) -> str:
    """Create only an inert Worker and return its UUID."""
    result = await pool.create_worker(
        db, slug=slug, name=slug, origin=origin,
        max_rps=5, max_inflight=8, actor_id=1,
    )
    assert result["status"] == "draft"
    return result["id"]


def test_two_bots_share_worker_with_separate_credentials(db: AsyncDb) -> None:
    """One Worker must never imply one shared bot credential."""
    async def scenario() -> None:
        worker_id = await _worker(db, "one-worker", ORIGIN_A)
        await pool.assign_route(
            db, bot_id=BOT_A, worker_id=worker_id,
            priority=10, actor_id=1,
        )
        await pool.assign_route(
            db, bot_id=BOT_B, worker_id=worker_id,
            priority=10, actor_id=1,
        )
        a = await pool.stage_credential(
            db, bot_id=BOT_A, worker_id=worker_id,
            secret=SECRET_A, actor_id=1,
        )
        b = await pool.stage_credential(
            db, bot_id=BOT_B, worker_id=worker_id,
            secret=SECRET_B, actor_id=1,
        )
        assert a["version"] == b["version"] == 1
        records = (await db.scalars(
            select(ShopRelayCredential).order_by(ShopRelayCredential.bot_id)
        )).all()
        assert len(records) == 2
        assert records[0].ciphertext != records[1].ciphertext
        assert records[0].key_fingerprint != records[1].key_fingerprint
        assert {pool.decrypt_secret(row) for row in records} == {
            SECRET_A, SECRET_B,
        }
        public = await pool.list_bot_routes(db, BOT_A)
        assert len(public["items"]) == 1
        assert SECRET_A not in repr(public)
        assert records[0].ciphertext not in repr(public)

    asyncio.run(scenario())


def test_one_bot_can_stage_two_prioritized_workers(db: AsyncDb) -> None:
    """Priorities distinguish independent routes without activating them."""
    async def scenario() -> None:
        a = await _worker(db, "worker-first", ORIGIN_A)
        b = await _worker(db, "worker-second", ORIGIN_B)
        await pool.assign_route(
            db, bot_id=BOT_A, worker_id=a, priority=10, actor_id=1,
        )
        await pool.assign_route(
            db, bot_id=BOT_A, worker_id=b, priority=20, actor_id=1,
        )
        result = await pool.list_bot_routes(db, BOT_A)
        assert [row["priority"] for row in result["items"]] == [10, 20]
        assert all(row["status"] == "staged" for row in result["items"])

    asyncio.run(scenario())


def test_duplicate_key_across_bots_is_rejected(db: AsyncDb) -> None:
    """A key used by one bot may not be staged by another bot."""
    async def scenario() -> None:
        worker_id = await _worker(db, "isolated", ORIGIN_A)
        for bot_id in (BOT_A, BOT_B):
            await pool.assign_route(
                db, bot_id=bot_id, worker_id=worker_id,
                priority=10, actor_id=1,
            )
        await pool.stage_credential(
            db, bot_id=BOT_A, worker_id=worker_id,
            secret=SECRET_A, actor_id=1,
        )
        with pytest.raises(security.SecurityRejected) as error:
            await pool.stage_credential(
                db, bot_id=BOT_B, worker_id=worker_id,
                secret=SECRET_A, actor_id=1,
            )
        assert error.value.code == "duplicate_relay_credential"

    asyncio.run(scenario())


def test_ciphertext_cannot_be_copied_between_bot_worker_pairs(
    db: AsyncDb,
) -> None:
    """Purpose-bound ciphertext blocks another route from borrowing secrets."""
    async def scenario() -> None:
        worker_id = await _worker(db, "bound", ORIGIN_A)
        for bot_id, secret in ((BOT_A, SECRET_A), (BOT_B, SECRET_B)):
            await pool.assign_route(
                db, bot_id=bot_id, worker_id=worker_id,
                priority=10, actor_id=1,
            )
            await pool.stage_credential(
                db, bot_id=bot_id, worker_id=worker_id,
                secret=secret, actor_id=1,
            )
        entries = (await db.scalars(select(ShopRelayCredential))).all()
        entries[1].ciphertext = entries[0].ciphertext
        with pytest.raises(security.SecurityRejected) as error:
            pool.decrypt_secret(entries[1])
        assert error.value.code == "relay_secret_binding_mismatch"
        await db.rollback()

    asyncio.run(scenario())


class FakeMethod:
    """Expose the Aiogram method name needed by the routing policy."""

    def __init__(self, name: str) -> None:
        """Create a fake Bot API request shape."""
        self.__api_method__ = name


class FakeDelegate:
    """Record attempts without performing any external request."""

    def __init__(self, *, fail: bool, origin: str) -> None:
        """Provide a harmless Worker API descriptor and canned outcome."""
        self.api = TelegramAPIServer.from_base(origin)
        self.worker_origin = origin
        self.fail = fail
        self.calls = 0

    async def make_request(self, bot, method, timeout=None):
        """Raise a sanitized transport exception or return a synthetic result."""
        self.calls += 1
        if self.fail:
            raise TelegramNetworkError(method=method, message="network timeout")
        return {"ok": True}

    async def close(self) -> None:
        """No physical sessions exist in the offline fixture."""


def test_read_only_failure_can_use_second_worker() -> None:
    """getMe may fail over to a second Worker after a network outage."""
    async def scenario() -> None:
        first = FakeDelegate(fail=True, origin=ORIGIN_A)
        second = FakeDelegate(fail=False, origin=ORIGIN_B)
        pool_session = RelayPoolTelegramSession((first, second))
        result = await pool_session.make_request(None, FakeMethod("getMe"))
        assert result == {"ok": True}
        assert first.calls == 1
        assert second.calls == 1
        await pool_session.close()

    asyncio.run(scenario())


def test_failed_send_is_never_replayed_on_another_worker() -> None:
    """A sendMessage timeout has an unknown outcome; stop after one attempt."""
    async def scenario() -> None:
        first = FakeDelegate(fail=True, origin=ORIGIN_A)
        second = FakeDelegate(fail=False, origin=ORIGIN_B)
        pool_session = RelayPoolTelegramSession((first, second))
        with pytest.raises(TelegramNetworkError):
            await pool_session.make_request(
                None, FakeMethod("sendMessage"),
            )
        assert first.calls == 1
        assert second.calls == 0
        await pool_session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["identity", "network", "version"])
def test_relay_activation_requires_proof_and_unchanged_configuration(
    db, monkeypatch, failure,
):
    """Failed identity, network or revision proof cannot promote a staged key."""
    from types import SimpleNamespace
    import config

    monkeypatch.setattr(config, "SHOP_RELAY_POOL_ENABLED", True)
    closed = []

    async def token_for_bot(_db, bot):
        """Replace token retrieval while retaining production relay proof checks."""
        assert bot.id == BOT_A
        return "123456:" + "A" * 32

    def client_for_bot(_token, session):
        """Supply a fake getMe operation without any network connection."""
        async def get_me():
            """Return mismatched identity or race the exact reviewed revision."""
            if failure == "network":
                raise TimeoutError("Synthetic unavailable provider")
            if failure == "version":
                route = db.session.get(ShopBotRelayRoute, (BOT_A, worker_id))
                route.version += 1
                db.session.commit()
            return SimpleNamespace(id=202 if failure == "identity" else 201)

        async def close():
            """Record cleanup for success and every failed proof."""
            closed.append(True)

        return SimpleNamespace(get_me=get_me, session=SimpleNamespace(close=close))

    monkeypatch.setattr(pool, "_verified_bot_token", token_for_bot)
    monkeypatch.setattr(pool, "create_bot", client_for_bot)

    async def scenario():
        """Keep route and credential transitions in the real disposable database."""
        nonlocal worker_id
        worker_id = await _worker(db, "proof-route", ORIGIN_A)
        route = await pool.assign_route(
            db, bot_id=BOT_A, worker_id=worker_id, priority=10, actor_id=1,
        )
        credential = await pool.stage_credential(
            db, bot_id=BOT_A, worker_id=worker_id, secret=SECRET_A, actor_id=1,
        )
        expected = {
            "identity": "bot_identity_mismatch", "network": "relay_probe_failed",
            "version": "configuration_changed",
        }[failure]
        with pytest.raises(security.SecurityRejected, match=expected):
            await pool.activate_route(
                db, bot_id=BOT_A, worker_id=worker_id, expected_version=route["version"],
                credential_version=credential["version"], actor_id=1,
            )
        assert db.session.get(ShopBotRelayRoute, (BOT_A, worker_id)).status == "staged"
        assert db.session.scalar(select(ShopRelayCredential)).state == "staged"

    worker_id = None
    asyncio.run(scenario())
    assert closed == [True]
