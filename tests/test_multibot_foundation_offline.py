"""Offline acceptance tests for multi-bot Foundation without provider traffic.

Tests use real SQLAlchemy constraints, encrypted token handling, and trusted
BotContext resolution. No Telegram/Bale API calls or business-data migrations
are executed.
"""

from __future__ import annotations

import asyncio
from uuid import NAMESPACE_URL, uuid5

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from channels.contracts import Platform
from models.base import Base
from models.shop_admin_control import AdminEvent
from models.shop_multibot import (
    DEFAULT_STORE_ID,
    LEGACY_BOT_IDS,
    ShopBot,
    ShopBotCredential,
    ShopBotRegistryEvent,
    ShopStore,
)
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_bot_registry as registry
from services import shop_bot_secrets as vault
from services.shop_bot_context import (
    BotContext,
    resolve_bot_context,
    resolve_legacy_bot_context,
)

FAKE_TELEGRAM_TOKEN = "12345678:" + "A" * 35
FAKE_TELEGRAM_TOKEN_2 = "12345678:" + "B" * 35


@pytest.fixture
def db(monkeypatch):
    """Initialize a disposable SQL database and a non-production crypto key."""
    monkeypatch.setenv(
        "SHOP_SECURITY_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.delenv("SHOP_BOT_SECRET_KEY", raising=False)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        ShopStaff.__table__,
        AdminEvent.__table__,
        ShopStore.__table__,
        ShopBot.__table__,
        ShopBotCredential.__table__,
        ShopBotRegistryEvent.__table__,
    ])
    with Session(engine) as session:
        session.add(ShopStaff(
            id=1, username="securityadmin", password_hash="test-only",
            role="superadmin", is_active=True, session_version=1,
        ))
        session.add(ShopStore(
            id=DEFAULT_STORE_ID, slug="default",
            name="فروشگاه اصلی", state="active",
        ))
        session.commit()
        yield session
    engine.dispose()


class AsyncDbAdapter:
    """Expose only the read methods needed by the production BotContext."""

    def __init__(self, db: Session) -> None:
        """Hold the disposable synchronous SQLAlchemy session."""
        self.db = db

    async def scalar(self, query):
        """Run a scalar read without a provider or external database."""
        return self.db.scalar(query)

    async def get(self, model, identifier):
        """Load one mapped object."""
        return self.db.get(model, identifier)


def expect_code(action, code: str) -> None:
    """Assert a specific safe rejection without exposing secret contents."""
    with pytest.raises(security.SecurityRejected) as failure:
        action()
    assert failure.value.code == code


def test_legacy_ids_are_stable_across_migrations() -> None:
    """Use fixed UUIDs so old bots have immutable noncolliding identities."""
    assert DEFAULT_STORE_ID == str(uuid5(
        NAMESPACE_URL, "aiogramshopbot:store:default:v1",
    ))
    for platform in ("telegram", "bale"):
        assert LEGACY_BOT_IDS[platform] == str(uuid5(
            NAMESPACE_URL, f"aiogramshopbot:bot:legacy:{platform}:v1",
        ))
    assert LEGACY_BOT_IDS["telegram"] != LEGACY_BOT_IDS["bale"]


def test_new_store_and_bot_are_not_live(db: Session) -> None:
    """Create only a paused store and draft bot, not a running receiver."""
    second = registry.create_store(
        db, slug="second-store", name="Second Shop", actor_id=1,
    )
    assert second.state == "paused"
    bot = registry.register_bot(
        db, store_id=second.id, platform="telegram",
        slug="second-telegram", name="Second Bot", actor_id=1,
    )
    db.commit()
    assert bot.status == "draft"
    assert bot.runtime_owner == "registry"
    assert bot.credential_version is None
    assert bot.provider_bot_id is None
    assert db.scalars(select(ShopBotCredential)).all() == []
    snapshot = registry.registry_snapshot(db, store_id=second.id)
    assert snapshot["bots"][0]["id"] == bot.id
    assert snapshot["runtime_migration_complete"] is False
    expect_code(
        lambda: registry.register_bot(
            db, store_id=second.id, platform="bale",
            slug="second-telegram", name="Clash", actor_id=1,
        ),
        "bot_slug_exists",
    )


def test_staging_keeps_active_routes_unchanged(db: Session) -> None:
    """Create and supersede a credential without activating either version."""
    bot = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="telegram",
        slug="telegram-two", name="Second Telegram", actor_id=1,
    )
    first = vault.stage_bot_token(
        db, bot_id=bot.id, token=FAKE_TELEGRAM_TOKEN, actor_id=1,
    )
    db.commit()
    assert first.version == 1
    assert first.source == "encrypted"
    assert first.state == "staged"
    assert FAKE_TELEGRAM_TOKEN not in first.ciphertext
    assert FAKE_TELEGRAM_TOKEN not in str(registry.serialize_bot(db, bot))
    assert bot.credential_version is None
    second = vault.stage_bot_token(
        db, bot_id=bot.id, token=FAKE_TELEGRAM_TOKEN_2, actor_id=1,
    )
    db.commit()
    assert first.state == "revoked"
    assert second.state == "staged"
    assert second.version == 2
    expect_code(
        lambda: vault.resolve_active_token(db, bot_id=bot.id),
        "bot_not_active",
    )
    vault.revoke_staged_token(
        db, bot_id=bot.id, version=2, actor_id=1,
    )
    db.commit()
    assert second.state == "revoked"
    expect_code(
        lambda: vault.revoke_staged_token(
            db, bot_id=bot.id, version=2, actor_id=1,
        ),
        "invalid_credential_state",
    )
    audit = db.scalars(select(ShopBotRegistryEvent)).all()
    assert len(audit) == 4
    assert all(FAKE_TELEGRAM_TOKEN not in str(event.__dict__) for event in audit)


def test_ciphertext_is_bound_to_one_bot_and_platform(db: Session) -> None:
    """Encrypted secrets cannot be transplanted to a different bot."""
    first = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="telegram",
        slug="my-first-bot", name="Bot 1", actor_id=1,
    )
    second = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="telegram",
        slug="my-second-bot", name="Bot 2", actor_id=1,
    )
    ciphertext = vault.encrypt_for_bot(
        first.id, "telegram", FAKE_TELEGRAM_TOKEN,
    )
    assert vault.decrypt_for_bot(
        first.id, "telegram", ciphertext,
    ) == FAKE_TELEGRAM_TOKEN
    expect_code(
        lambda: vault.decrypt_for_bot(
            second.id, "telegram", ciphertext,
        ),
        "bot_secret_binding_mismatch",
    )
    expect_code(
        lambda: vault.decrypt_for_bot(
            first.id, "bale", ciphertext,
        ),
        "bot_secret_binding_mismatch",
    )


def test_invalid_token_and_missing_key_fail_closed(db: Session, monkeypatch) -> None:
    """Reject malformed tokens and an unavailable persistent encryption key."""
    bot = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="telegram",
        slug="secure-test-bot", name="Secure", actor_id=1,
    )
    expect_code(
        lambda: vault.stage_bot_token(
            db, bot_id=bot.id, token="INVALID", actor_id=1,
        ),
        "invalid_bot_token_format",
    )
    monkeypatch.delenv("SHOP_SECURITY_ENCRYPTION_KEY", raising=False)
    expect_code(
        lambda: vault.encrypt_for_bot(
            bot.id, "telegram", FAKE_TELEGRAM_TOKEN,
        ),
        "bot_secret_key_unavailable",
    )


def test_legacy_environment_tokens_are_not_copied(db: Session, monkeypatch) -> None:
    """Read original credentials only through the fixed legacy key binding."""
    monkeypatch.setenv("TOKEN", FAKE_TELEGRAM_TOKEN)
    bot = ShopBot(
        id=LEGACY_BOT_IDS["telegram"], store_id=DEFAULT_STORE_ID,
        slug="legacy-telegram", name="Existing Bot",
        platform="telegram", status="legacy", runtime_owner="legacy",
        version=1, credential_version=1,
    )
    db.add(bot)
    db.add(ShopBotCredential(
        id="b9999999-0000-4000-8000-000000000001",
        bot_id=bot.id, version=1,
        source="environment", state="active",
        environment_key="TOKEN",
    ))
    db.commit()
    assert vault.resolve_active_token(db, bot_id=bot.id) == FAKE_TELEGRAM_TOKEN
    assert all(
        row.ciphertext is None for row in db.scalars(
            select(ShopBotCredential)
        ).all()
    )
    expect_code(
        lambda: vault.stage_bot_token(
            db, bot_id=bot.id, token=FAKE_TELEGRAM_TOKEN_2, actor_id=1,
        ),
        "legacy_bot_credential_locked",
    )


def test_bot_context_is_scoped_and_does_not_carry_token(db: Session) -> None:
    """Two bots and their users never share an implicit owner key."""
    first = ShopBot(
        id=LEGACY_BOT_IDS["telegram"], store_id=DEFAULT_STORE_ID,
        slug="legacy-telegram", name="Legacy Telegram",
        platform="telegram", status="legacy", runtime_owner="legacy",
        version=1, credential_version=1,
    )
    second = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="bale",
        slug="new-bale-bot", name="New Bale", actor_id=1,
    )
    db.add(first)
    db.commit()
    adapter = AsyncDbAdapter(db)
    context = asyncio.run(resolve_legacy_bot_context(
        adapter, authenticated_platform=Platform.TELEGRAM,
    ))
    assert isinstance(context, BotContext)
    assert context.bot_id == first.id
    assert context.owner_key(12345) == (first.id, 12345)
    assert second.id != context.bot_id
    assert "TOKEN" not in repr(context)
    assert "secret" not in repr(context).casefold()
    with pytest.raises(security.SecurityRejected):
        asyncio.run(resolve_bot_context(
            adapter,
            authenticated_bot_id=first.id,
            authenticated_platform=Platform.BALE,
        ))
    with pytest.raises(security.SecurityRejected):
        asyncio.run(resolve_bot_context(
            adapter,
            authenticated_bot_id=second.id,
            authenticated_platform=Platform.BALE,
        ))


def test_paused_store_never_exposes_live_bot(db: Session) -> None:
    """Disabling a store prevents otherwise valid bot dispatch context."""
    bot = ShopBot(
        id=LEGACY_BOT_IDS["bale"], store_id=DEFAULT_STORE_ID,
        slug="legacy-bale", name="Existing Bale",
        platform="bale", status="legacy", runtime_owner="legacy",
        version=1, credential_version=1,
    )
    db.add(bot)
    db.get(ShopStore, DEFAULT_STORE_ID).state = "paused"
    db.commit()
    with pytest.raises(security.SecurityRejected) as failure:
        asyncio.run(resolve_legacy_bot_context(
            AsyncDbAdapter(db), authenticated_platform=Platform.BALE,
        ))
    assert failure.value.code == "store_not_active"
