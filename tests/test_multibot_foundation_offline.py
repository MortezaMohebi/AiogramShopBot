"""Offline acceptance tests for multi-bot Foundation without provider traffic.

Tests use real SQLAlchemy constraints, encrypted token handling, and trusted
BotContext resolution. No Telegram/Bale API calls or business-data migrations
are executed.
"""

from __future__ import annotations

from tests.schema_support import TEST_BOT_IDS, create_shop_schema

import asyncio
from uuid import NAMESPACE_URL, uuid5

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from channels.contracts import Platform
from models.base import Base
from models.shop_admin_control import AdminEvent
from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import (
    DEFAULT_STORE_ID,
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
    create_shop_schema(engine)
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


def test_default_store_identity_is_stable_without_implicit_bots(db: Session) -> None:
    """Store initialization never synthesizes provider-owned bot records."""
    assert DEFAULT_STORE_ID == str(uuid5(
        NAMESPACE_URL, "aiogramshopbot:store:default:v1",
    ))
    assert db.scalars(select(ShopBot)).all() == []
    assert db.scalars(select(ShopBotCredential)).all() == []


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


def test_environment_credentials_cannot_supply_registry_tokens(
    db: Session, monkeypatch,
) -> None:
    """Historical environment receipts cannot bypass encrypted bot storage."""
    monkeypatch.setenv("TOKEN", FAKE_TELEGRAM_TOKEN)
    bot = ShopBot(
        id=TEST_BOT_IDS["telegram"], store_id=DEFAULT_STORE_ID,
        slug="registry-telegram", name="Registered Bot",
        platform="telegram", status="active", runtime_owner="registry",
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
    expect_code(
        lambda: vault.resolve_active_token(db, bot_id=bot.id),
        "bot_secret_unavailable",
    )
    assert all(
        row.ciphertext is None for row in db.scalars(
            select(ShopBotCredential)
        ).all()
    )


def test_historical_bot_owner_cannot_resolve_or_stage_credentials(db: Session) -> None:
    """Preserved FK owners remain unreachable from Registry runtime services."""
    bot = ShopBot(
        id=TEST_BOT_IDS["telegram"], store_id=DEFAULT_STORE_ID,
        slug="historical-telegram", name="Historical Owner",
        platform="telegram", status="legacy", runtime_owner="legacy",
        version=1, credential_version=1,
    )
    db.add(bot)
    db.commit()
    expect_code(
        lambda: vault.resolve_active_token(db, bot_id=bot.id),
        "bot_not_active",
    )
    expect_code(
        lambda: vault.stage_bot_token(
            db, bot_id=bot.id, token=FAKE_TELEGRAM_TOKEN_2, actor_id=1,
        ),
        "invalid_bot_runtime",
    )
    with pytest.raises(security.SecurityRejected) as failure:
        asyncio.run(resolve_bot_context(
            AsyncDbAdapter(db), authenticated_bot_id=bot.id,
            authenticated_platform=Platform.TELEGRAM,
        ))
    assert failure.value.code == "bot_not_active"


def test_bot_context_is_scoped_and_does_not_carry_token(db: Session) -> None:
    """Two registry bots never share an implicit owner key or credential."""
    first = ShopBot(
        id=TEST_BOT_IDS["telegram"], store_id=DEFAULT_STORE_ID,
        slug="registry-telegram", name="Registered Telegram",
        platform="telegram", status="active", runtime_owner="registry",
        version=1, credential_version=1,
    )
    second = registry.register_bot(
        db, store_id=DEFAULT_STORE_ID, platform="bale",
        slug="new-bale-bot", name="New Bale", actor_id=1,
    )
    db.add(first)
    db.commit()
    adapter = AsyncDbAdapter(db)
    context = asyncio.run(resolve_bot_context(
        adapter, authenticated_bot_id=first.id,
        authenticated_platform=Platform.TELEGRAM,
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
    """Disabling a Store prevents otherwise valid Registry bot dispatch."""
    bot = ShopBot(
        id=TEST_BOT_IDS["bale"], store_id=DEFAULT_STORE_ID,
        slug="registered-bale", name="Registered Bale",
        platform="bale", status="active", runtime_owner="registry",
        version=1, credential_version=1,
    )
    db.add(bot)
    db.get(ShopStore, DEFAULT_STORE_ID).state = "paused"
    db.commit()
    with pytest.raises(security.SecurityRejected) as failure:
        asyncio.run(resolve_bot_context(
            AsyncDbAdapter(db), authenticated_bot_id=bot.id,
            authenticated_platform=Platform.BALE,
        ))
    assert failure.value.code == "store_not_active"


def test_registry_creation_defaults_to_current_store_instead_of_global_default(db):
    """A Store switch must not submit new bots to an inactive default Store."""
    from services.shop_store_context import AuthorizedStore, StoreContext, bind_context

    selected = registry.create_store(db, slug="selected-store", name="Selected", actor_id=1)
    db.commit()
    stores = tuple(AuthorizedStore(id=row.id, slug=row.slug, name=row.name,
                                   state=row.state, access_level="manager")
                   for row in db.scalars(select(ShopStore)).all())
    context = StoreContext(staff_id=1, session_id="qa-selection", allowed_stores=stores,
                           active_store_ids=(selected.id,), current_store_id=selected.id,
                           default_store_id=DEFAULT_STORE_ID, version=1)
    with bind_context(context):
        result = registry.registry_snapshot(db)
    assert result["default_store_id"] == selected.id
