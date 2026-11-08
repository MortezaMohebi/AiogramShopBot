"""Offline acceptance of independent multi-bot management and secret proof.

No provider calls occur. A fake getMe callback returns deterministic identities,
and all tests use a disposable SQLAlchemy SQLite transaction.
"""

from __future__ import annotations

from tests.schema_support import create_shop_schema

import asyncio
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models.base import Base
from models.shop_admin_control import AdminEvent
from models.shop_bot_operations import ShopBotOperations, ShopBotOperationsEvent
from models.shop_multibot import (
    DEFAULT_STORE_ID, ShopBot, ShopBotCredential,
    ShopBotRegistryEvent, ShopStore,
)
from models.shop_multibot_receiver import ShopBotReceiver
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_bot_operations as operations
from services import shop_bot_registry as registry
from services import shop_bot_secrets as vault
from services import shop_bot_verification as verification

TOKEN_A = "12345678:" + "A" * 35
TOKEN_B = "87654321:" + "B" * 35


@pytest.fixture
def db(monkeypatch):
    """Set a disposable secret key and independent relational records."""
    monkeypatch.setenv(
        "SHOP_SECURITY_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.delenv("SHOP_BOT_SECRET_KEY", raising=False)
    monkeypatch.delenv("TOKEN", raising=False)
    monkeypatch.delenv("BALE_BOT_TOKEN", raising=False)
    engine = create_engine("sqlite:///:memory:")
    create_shop_schema(engine)
    with Session(engine) as session:
        session.add(ShopStaff(
            id=1, username="owner", password_hash="test-only",
            role="superadmin", is_active=True, session_version=1,
        ))
        session.add(ShopStore(
            id=DEFAULT_STORE_ID, slug="default",
            name="Main Store", state="active",
        ))
        session.commit()
        yield session
    engine.dispose()


class AsyncDb:
    """Minimal AsyncSession-compatible test adapter for actual services."""

    def __init__(self, db: Session) -> None:
        """Keep a disposable synchronous session."""
        self.db = db

    async def get(self, model, key, **kwargs):
        """Read mapped data by primary key."""
        return self.db.get(model, key, **kwargs)

    async def scalar(self, statement):
        """Execute scalar SQLAlchemy queries."""
        return self.db.scalar(statement)

    async def execute(self, statement):
        """Execute a SQLAlchemy statement."""
        return self.db.execute(statement)

    async def run_sync(self, func):
        """Run real synchronous helpers in the current transaction."""
        return func(self.db)

    async def commit(self):
        """Commit this disposable transaction."""
        self.db.commit()

    async def rollback(self):
        """Rollback a rejected mutation."""
        self.db.rollback()

    def add(self, record):
        """Stage an ORM record without committing."""
        self.db.add(record)


def _active_bot(db: Session, platform: str) -> ShopBot:
    """Register an isolated Registry bot with explicit encrypted credentials."""
    row = ShopBot(
        id=str(uuid4()), store_id=DEFAULT_STORE_ID,
        slug=f"registered-{platform}", name=f"Registered {platform}",
        platform=platform, status="active", runtime_owner="registry",
        version=1, credential_version=1,
    )
    db.add(row)
    db.add(ShopBotCredential(
        id=str(uuid4()), bot_id=row.id, version=1,
        source="encrypted", ciphertext="offline-encrypted-token", state="active",
    ))
    db.add(ShopBotReceiver(
        bot_id=row.id, binding_id=str(uuid4()), mode="webhook", state="active",
        credential_version=1, webhook_secret_ciphertext="offline-secret",
        webhook_secret_digest="f" * 64,
    ))
    db.add(ShopBotOperations(bot_id=row.id, desired_state="active"))
    return row


def _reject(action, code: str) -> None:
    """Assert expected fail-closed refusal rather than a false success."""
    with pytest.raises(security.SecurityRejected) as rejected:
        action()
    assert rejected.value.code == code


def test_registry_pause_and_enable_are_independent(db: Session) -> None:
    """Telegram pause must not affect Bale, and pending receipts stay intact."""
    telegram = _active_bot(db, "telegram")
    bale = _active_bot(db, "bale")
    db.commit()
    operations.change_state(
        db, bot_id=telegram.id, actor_id=1,
        expected_version=1, state="paused",
        reason="Planned maintenance of Telegram storefront",
    )
    db.commit()
    assert db.get(ShopBotOperations, telegram.id).desired_state == "paused"
    assert db.get(ShopBotOperations, bale.id).desired_state == "active"
    assert telegram.status == "paused"
    assert telegram.version == 2
    assert bale.version == 1
    audit = db.scalars(select(ShopBotOperationsEvent).where(
        ShopBotOperationsEvent.bot_id == telegram.id,
    )).all()
    assert len(audit) == 1
    assert audit[0].previous_state == "active"
    assert audit[0].next_state == "paused"
    operations.change_state(
        db, bot_id=telegram.id, actor_id=1,
        expected_version=2, state="maintenance", reason="Planned maintenance",
    )
    db.commit()
    operations.change_state(
        db, bot_id=telegram.id, actor_id=1,
        expected_version=3, state="active", reason="All checks passed",
    )
    db.commit()
    assert db.get(ShopBotOperations, telegram.id).desired_state == "active"


def test_draft_requires_active_receiver_before_activation(db: Session):
    """A verified draft is still offline and cannot start receiving updates."""
    bot = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="telegram",
        slug="new-telegram", name="New Telegram", actor_id=1,
    )
    db.commit()
    _reject(lambda: operations.change_state(
        db, bot_id=bot.id, actor_id=1, expected_version=1,
        state="active", reason="Test only",
    ), "bot_runtime_not_ready")
    assert bot.status == "draft"
    assert operations.operation_data(db, bot)["runtime_ready"] is False
    assert operations.operation_data(db, bot)["desired_state"] == "disabled"


def test_optimistic_state_and_reason_enforcement(db: Session) -> None:
    """A stale request or undocumented disable must not change anything."""
    bot = _active_bot(db, "telegram")
    db.commit()
    _reject(lambda: operations.change_state(
        db, bot_id=bot.id, actor_id=1, expected_version=1,
        state="disabled", reason="short",
    ), "bot_state_reason_required")
    _reject(lambda: operations.change_state(
        db, bot_id=bot.id, actor_id=1, expected_version=999,
        state="maintenance", reason="Planned",
    ), "configuration_changed")
    assert bot.version == 1
    assert db.get(ShopBotOperations, bot.id).desired_state == "active"


def test_per_bot_details_not_shared_across_platforms(db: Session) -> None:
    """Public bot copy, support and owner settings are scoped by bot UUID."""
    telegram = _active_bot(db, "telegram")
    bale = _active_bot(db, "bale")
    db.commit()
    operations.update_details(
        db, bot_id=telegram.id, actor_id=1,
        expected_version=1, name="Telegram Shop",
        owner_staff_id=1, environment="staging",
        welcome_message="Welcome Telegram", maintenance_message="Paused",
        support_url="https://example.org/support",
    )
    db.commit()
    first = db.get(ShopBotOperations, telegram.id)
    assert first.welcome_message == "Welcome Telegram"
    assert first.support_url == "https://example.org/support"
    assert db.get(ShopBotOperations, bale.id).desired_state == "active"
    _reject(lambda: operations.update_details(
        db, bot_id=bale.id, actor_id=1,
        expected_version=1, name="Bale Shop",
        owner_staff_id=1, environment="staging",
        welcome_message=None, maintenance_message=None,
        support_url="http://localhost/internal",
    ), "invalid_support_url")


def test_legacy_codespaces_environment_is_presented_as_staging(db: Session) -> None:
    bot = _active_bot(db, "telegram")
    ops = db.get(ShopBotOperations, bot.id)
    ops.environment = "codespaces"
    db.commit()

    assert operations.operation_data(db, bot)["environment"] == "staging"
    assert ops.environment == "codespaces"


def test_keyed_token_fingerprint_prevents_duplicate_drafts(db: Session) -> None:
    """One token can never silently represent two new logical bots."""
    first = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="telegram",
        slug="bot-first", name="First", actor_id=1,
    )
    second = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="telegram",
        slug="bot-second", name="Second", actor_id=1,
    )
    vault.stage_bot_token(
        db, bot_id=first.id, token=TOKEN_A, actor_id=1,
    )
    db.commit()
    _reject(lambda: vault.stage_bot_token(
        db, bot_id=second.id, token=TOKEN_A, actor_id=1,
    ), "duplicate_bot_credential")
    assert first.credential_version is None
    assert second.credential_version is None
    assert TOKEN_A not in str(registry.serialize_bot(db, first))


def test_provider_get_me_proves_identity_without_activation(db: Session):
    """A verified staged token never updates a live receiver or credential."""
    bot = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="telegram",
        slug="verified-bot", name="Verified", actor_id=1,
    )
    cred = vault.stage_bot_token(
        db, bot_id=bot.id, token=TOKEN_A, actor_id=1,
    )
    db.commit()

    async def fake_get_me(platform: str, token: str):
        """Simulate only the one provider identity call."""
        assert platform == "telegram"
        assert token == TOKEN_A
        return verification.ProviderBotIdentity(
            bot_id=47110022, username="verified_shop_bot",
        )

    result = asyncio.run(verification.verify_bot(
        AsyncDb(db), bot_id=bot.id, actor_id=1,
        version=cred.version, probe=fake_get_me,
    ))
    assert result["runtime_activated"] is False
    assert result["provider_bot_id"] == "47110022"
    assert bot.provider_bot_id == 47110022
    assert bot.status == "draft"
    assert bot.credential_version is None
    assert cred.state == "staged"
    assert cred.verified_bot_id == 47110022
    assert cred.verified_at is not None


def test_provider_id_cannot_be_assigned_to_two_bots(db: Session):
    """Repeated successful getMe for the same provider identity is refused."""
    first = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="telegram",
        slug="some-telegram", name="One", actor_id=1,
    )
    second = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="telegram",
        slug="other-telegram", name="Two", actor_id=1,
    )
    first_token = vault.stage_bot_token(
        db, bot_id=first.id, token=TOKEN_A, actor_id=1,
    )
    second_token = vault.stage_bot_token(
        db, bot_id=second.id, token=TOKEN_B, actor_id=1,
    )
    db.commit()

    async def same_identity(platform: str, token: str):
        """Prove that credential uniqueness is different from bot-ID uniqueness."""
        return verification.ProviderBotIdentity(47110022, "same_bot")

    asyncio.run(verification.verify_bot(
        AsyncDb(db), bot_id=first.id, actor_id=1,
        version=first_token.version, probe=same_identity,
    ))
    with pytest.raises(security.SecurityRejected) as refused:
        asyncio.run(verification.verify_bot(
            AsyncDb(db), bot_id=second.id, actor_id=1,
            version=second_token.version, probe=same_identity,
        ))
    assert refused.value.code == "duplicate_provider_bot"
    assert second.provider_bot_id is None


def test_active_credential_cannot_be_reverified_as_staged(db: Session):
    """An active encrypted version cannot bypass staged credential review."""
    bot = _active_bot(db, "telegram")
    db.commit()

    async def must_not_probe(platform: str, token: str):
        """Refuse any network request for a non-staged credential."""
        raise AssertionError("Active credential must not reach getMe")

    with pytest.raises(security.SecurityRejected) as refused:
        asyncio.run(verification.verify_bot(
            AsyncDb(db), bot_id=bot.id, actor_id=1, version=1,
            probe=must_not_probe,
        ))
    assert refused.value.code == "invalid_credential_state"
    assert bot.status == "active"
    assert bot.credential_version == 1
    assert bot.version == 1


def test_revoked_token_can_be_staged_again_without_active_duplication(
    db: Session,
) -> None:
    """A revoked proposal does not permanently forbid a later safe restage."""
    bot = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="telegram",
        slug="restage-telegram", name="Restage", actor_id=1,
    )
    previous = vault.stage_bot_token(
        db, bot_id=bot.id, token=TOKEN_A, actor_id=1,
    )
    db.commit()
    vault.revoke_staged_token(
        db, bot_id=bot.id, version=previous.version, actor_id=1,
    )
    db.commit()
    fresh = vault.stage_bot_token(
        db, bot_id=bot.id, token=TOKEN_A, actor_id=1,
    )
    db.commit()
    assert previous.state == "revoked"
    assert fresh.state == "staged"
    assert fresh.version == previous.version + 1
    assert bot.credential_version is None


def test_superseded_token_cannot_be_verified(
    db: Session,
) -> None:
    """A previous credential loses authority immediately after replacement."""
    bot = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="telegram",
        slug="superseded-bot", name="Superseded", actor_id=1,
    )
    old = vault.stage_bot_token(
        db, bot_id=bot.id, token=TOKEN_A, actor_id=1,
    )
    newer = vault.stage_bot_token(
        db, bot_id=bot.id, token=TOKEN_B, actor_id=1,
    )
    db.commit()
    assert old.state == "revoked"
    assert newer.state == "staged"

    async def must_not_probe(platform: str, token: str):
        """A stale credential must not reach the Telegram provider."""
        raise AssertionError("getMe must not be called with revoked Token")

    with pytest.raises(security.SecurityRejected) as refused:
        asyncio.run(verification.verify_bot(
            AsyncDb(db), bot_id=bot.id, actor_id=1,
            version=old.version, probe=must_not_probe,
        ))
    assert refused.value.code == "invalid_credential_state"
    assert bot.provider_bot_id is None


def test_provider_failure_cannot_leak_secret_or_activate(
    db: Session,
) -> None:
    """Provider errors are redacted and leave all bot state unchanged."""
    bot = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="telegram",
        slug="broken-provider", name="Broken", actor_id=1,
    )
    cred = vault.stage_bot_token(
        db, bot_id=bot.id, token=TOKEN_A, actor_id=1,
    )
    db.commit()

    async def failing_get_me(platform: str, token: str):
        """Simulate an exception containing sensitive upstream URL material."""
        raise RuntimeError(f"https://api.telegram.org/bot{token}/getMe")

    with pytest.raises(security.SecurityRejected) as refused:
        asyncio.run(verification.verify_bot(
            AsyncDb(db), bot_id=bot.id, actor_id=1,
            version=cred.version, probe=failing_get_me,
        ))
    assert refused.value.code == "provider_state_unavailable"
    assert TOKEN_A not in str(refused.value)
    assert bot.status == "draft"
    assert bot.verified_at is None
    assert cred.state == "staged"
