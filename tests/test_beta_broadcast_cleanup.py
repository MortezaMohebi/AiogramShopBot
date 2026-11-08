"""Broadcast QA cleanup pauses only proven synthetic rows without providers."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

import pytest
import config
from sqlalchemy import select, text
from sqlalchemy.sql.elements import TextClause

from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import ShopBot, ShopBotCredential, ShopStore
from models.shop_multibot_receiver import ShopBotReceiver
from tests.script_entrypoints import script_function
from tests.test_shared_cart import db as shared_db


@pytest.fixture
def db():
    """Use real bot, credential and receiver rows without provider connections."""
    yield from shared_db.__wrapped__()


@dataclass
class SyntheticRows:
    """Keep all independently verified ownership markers for one seeded Bot."""

    store: ShopStore
    bot: ShopBot
    credential: ShopBotCredential
    operations: ShopBotOperations
    receiver: ShopBotReceiver


def synthetic_rows(db, run_id):
    """Reproduce the production runner's exact additive fixture markers."""
    store = ShopStore(
        id=str(uuid4()), slug=f"qa-broadcast-{run_id}-0",
        name="Synthetic broadcast Store 0", state="active",
    )
    bot = ShopBot(
        id=str(uuid4()), store_id=store.id, slug=f"qa-telegram-alpha-{run_id}",
        name="Synthetic telegram-alpha", platform="telegram",
        provider_bot_id=8_000_000_000 + int(run_id, 16) % 1_000_000_000,
        runtime_owner="registry", status="active",
        credential_version=1,
    )
    credential = ShopBotCredential(
        id=str(uuid4()), bot_id=bot.id, version=1, source="encrypted",
        state="active", ciphertext="synthetic-no-provider-use",
        verified_bot_id=bot.provider_bot_id,
    )
    operations = ShopBotOperations(
        bot_id=bot.id, desired_state="active", environment="staging",
    )
    receiver = ShopBotReceiver(
        bot_id=bot.id, binding_id=str(uuid4()), mode="webhook", state="active",
        credential_version=1, webhook_secret_ciphertext="synthetic-unused",
        webhook_secret_digest="a" * 64,
    )
    for row in (store, bot, credential, operations, receiver):
        db.add(row)
    db.session.commit()
    return SyntheticRows(store, bot, credential, operations, receiver)


def cleanup_entry(db, *, database="shop_codespace", user="shop_codespace"):
    """Run only the real cleanup function with a disposable SQL session."""
    class GuardedDatabase:
        """Use real ORM statements while replacing PostgreSQL identity functions."""

        def __getattr__(self, name):
            """Delegate actual reads, locks and commits to the isolated session."""
            return getattr(db, name)

        async def scalar(self, statement):
            """Return an explicit server identity only for the two guard queries."""
            if isinstance(statement, TextClause):
                if str(statement) == "SELECT current_database()":
                    return database
                if str(statement) == "SELECT current_user":
                    return user
                raise AssertionError("Unexpected cleanup raw SQL")
            return await db.scalar(statement)

    @asynccontextmanager
    async def sessions():
        """Keep cleanup on one disposable transaction with real persistent rows."""
        yield GuardedDatabase()

    return script_function(
        "scripts/beta_broadcast_e2e.py", "pause_synthetic_bots",
        session_maker=sessions, config=config, re=re, select=select, text=text,
        ShopBot=ShopBot, ShopStore=ShopStore, ShopBotCredential=ShopBotCredential,
        ShopBotOperations=ShopBotOperations, ShopBotReceiver=ShopBotReceiver,
    )


@pytest.mark.asyncio
async def test_cleanup_pauses_only_owned_fixture_and_is_idempotent(db):
    """A finally cleanup leaves unrelated receivers and encrypted receipts intact."""
    owned = synthetic_rows(db, "a" * 12)
    unrelated = synthetic_rows(db, "b" * 12)
    cleanup = cleanup_entry(db)
    report = await cleanup(bot_ids={owned.bot.id})
    assert report["paused_synthetic_bots"] == 1
    assert owned.bot.status == owned.operations.desired_state == owned.receiver.state == "paused"
    assert unrelated.bot.status == unrelated.receiver.state == "active"
    assert owned.credential.state == "active"
    versions = owned.bot.version, owned.receiver.version
    await cleanup(bot_ids={owned.bot.id})
    assert (owned.bot.version, owned.receiver.version) == versions


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["store_name", "bot_slug", "credential", "database", "user"])
async def test_cleanup_refuses_unproven_scope_without_partial_mutation(db, tamper):
    """A similar slug or foreign database cannot authorize cleanup changes."""
    owned = synthetic_rows(db, "a" * 12)
    suspect = synthetic_rows(db, "b" * 12)
    if tamper == "store_name":
        suspect.store.name = "A real operator-owned Store"
    elif tamper == "bot_slug":
        suspect.bot.slug = "qa-telegram-alpha-cccccccccccc"
    elif tamper == "credential":
        suspect.credential.verified_bot_id += 1
    db.session.commit()
    cleanup = cleanup_entry(
        db, database="production" if tamper == "database" else "shop_codespace",
        user="postgres" if tamper == "user" else "shop_codespace",
    )
    with pytest.raises((RuntimeError, AssertionError)):
        await cleanup()
    assert owned.bot.status == owned.receiver.state == "active"
    assert suspect.bot.status == suspect.receiver.state == "active"
