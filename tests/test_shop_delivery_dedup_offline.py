"""Offline webhook and file-cache isolation tests with disposable SQLite.

These tests do not need real Telegram/Bale callbacks or bot tokens.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import db
from channels.contracts import Platform
from models.base import Base
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot
from tests.schema_support import create_shop_schema, seed_registry, TEST_BOT_IDS
from models.shop_delivery import ShopInboundUpdate, ShopRemoteFile
from services.shop_media_delivery import bot_fingerprint, cached_file_id
from services.shop_updates import claim_update, finish_update


TELEGRAM_TOKEN = "111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
BALE_TOKEN = "222222:BBBBBBBBBBBBBBBBBBBBBBBBBBBB"
BALE_TOKEN_2 = "333333:CCCCCCCCCCCCCCCCCCCCCCCCCCCC"


class SQLiteAsyncSession:
    """Provide the minimum async SQLAlchemy transaction API used by receipts."""

    def __init__(self, session: Session) -> None:
        """Hold the in-memory test transaction."""
        self.session = session

    async def scalar(self, query):
        """Evaluate a SQLAlchemy scalar query."""
        return self.session.scalar(query)

    async def execute(self, query):
        """Evaluate a SQLAlchemy statement."""
        return self.session.execute(query)

    async def flush(self):
        """Flush staged entities."""
        self.session.flush()

    async def commit(self):
        """Commit changes to the test database."""
        self.session.commit()

    def add(self, record):
        """Stage a new receipt."""
        self.session.add(record)

    @asynccontextmanager
    async def begin_nested(self):
        """Make an SQLite SAVEPOINT work with the async receipt API."""
        with self.session.begin_nested():
            yield


@pytest.fixture
def database(monkeypatch):
    """Replace the async DB factory with a disposable SQLite session."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_shop_schema(engine)
    with Session(engine, expire_on_commit=False) as session:
        seed_registry(session)
        session.add(
            ShopBot(
                id="00000000-0000-4000-8000-000000000103",
                store_id=DEFAULT_STORE_ID,
                slug="second-bale",
                name="Second Bale",
                platform="bale",
                status="active",
                runtime_owner="registry",
                version=1,
                credential_version=1,
            )
        )
        session.commit()
        adapter = SQLiteAsyncSession(session)

        @asynccontextmanager
        async def session_maker():
            """Share a test-scoped database without opening a real connection."""
            yield adapter

        monkeypatch.setattr(db, "session_maker", session_maker)
        yield session
    engine.dispose()


@pytest.mark.asyncio
async def test_webhook_update_is_processed_once_for_same_bot(database):
    """A replayed Telegram update cannot run its mutation handler twice."""
    fresh, state = await claim_update(
        platform=Platform.TELEGRAM,
        token=TELEGRAM_TOKEN,
        update_id=200,
        bot_id=TEST_BOT_IDS[(Platform.TELEGRAM).value],
    )
    assert (fresh, state) == (True, "processing")
    again, state = await claim_update(
        platform=Platform.TELEGRAM,
        token=TELEGRAM_TOKEN,
        update_id=200,
        bot_id=TEST_BOT_IDS[(Platform.TELEGRAM).value],
    )
    assert (again, state) == (False, "processing")
    await finish_update(
        platform=Platform.TELEGRAM,
        token=TELEGRAM_TOKEN,
        update_id=200,
        success=True,
        bot_id=TEST_BOT_IDS[(Platform.TELEGRAM).value],
    )
    again, state = await claim_update(
        platform=Platform.TELEGRAM,
        token=TELEGRAM_TOKEN,
        update_id=200,
        bot_id=TEST_BOT_IDS[(Platform.TELEGRAM).value],
    )
    assert (again, state) == (False, "processed")
    assert database.query(ShopInboundUpdate).count() == 1


@pytest.mark.asyncio
async def test_webhook_same_numeric_id_is_unique_to_bot_and_platform(database):
    """Bale and Telegram can have identical update IDs without collision."""
    for platform, token, bot_id in [
        (Platform.TELEGRAM, TELEGRAM_TOKEN, TEST_BOT_IDS["telegram"]),
        (Platform.BALE, BALE_TOKEN, TEST_BOT_IDS["bale"]),
        (Platform.BALE, BALE_TOKEN_2, "00000000-0000-4000-8000-000000000103"),
    ]:
        fresh, _ = await claim_update(
            platform=platform, token=token, update_id=42, bot_id=bot_id
        )
        assert fresh
    assert database.query(ShopInboundUpdate).count() == 3


@pytest.mark.asyncio
async def test_failed_webhook_stays_visible_for_manual_reconciliation(database):
    """Never silently retry mutations whose outcome may be ambiguous."""
    await claim_update(
        platform=Platform.BALE,
        token=BALE_TOKEN,
        update_id=303,
        bot_id=TEST_BOT_IDS[(Platform.BALE).value],
    )
    await finish_update(
        platform=Platform.BALE,
        token=BALE_TOKEN,
        update_id=303,
        success=False,
        bot_id=TEST_BOT_IDS[(Platform.BALE).value],
    )
    again, state = await claim_update(
        platform=Platform.BALE,
        token=BALE_TOKEN,
        update_id=303,
        bot_id=TEST_BOT_IDS[(Platform.BALE).value],
    )
    assert (again, state) == (False, "needs_review")


@pytest.mark.asyncio
async def test_cached_file_id_never_crosses_bot_or_platform_boundary(database):
    """A known Bale file ID remains inaccessible to other Bale bots/Telegram."""
    key = "a" * 32 + ".png"
    first_bot = bot_fingerprint(BALE_TOKEN)
    database.add(
        ShopRemoteFile(
            platform="bale",
            bot_fingerprint=first_bot,
            storage_key=key,
            delivery_kind="photo",
            remote_file_id="bale-first-bot-file",
            bot_id=TEST_BOT_IDS["bale"],
        )
    )
    database.commit()
    assert (
        await cached_file_id(
            platform="bale",
            bot_key=first_bot,
            storage_key=key,
            kind="photo",
            bot_id=TEST_BOT_IDS["bale"],
        )
        == "bale-first-bot-file"
    )
    assert (
        await cached_file_id(
            platform="bale",
            bot_key=bot_fingerprint(BALE_TOKEN_2),
            storage_key=key,
            kind="photo",
            bot_id=TEST_BOT_IDS["bale"],
        )
        is None
    )
    assert (
        await cached_file_id(
            platform="telegram",
            bot_key=bot_fingerprint(TELEGRAM_TOKEN),
            storage_key=key,
            kind="photo",
            bot_id=TEST_BOT_IDS["telegram"],
        )
        is None
    )
    assert (
        await cached_file_id(
            platform="bale",
            bot_key=first_bot,
            storage_key=key,
            kind="document",
            bot_id=TEST_BOT_IDS["bale"],
        )
        is None
    )


@pytest.mark.asyncio
async def test_token_rotation_keeps_the_original_update_receipt(database):
    """Rotating a credential cannot replay an update or hide its final state."""
    await claim_update(
        platform=Platform.BALE,
        token=BALE_TOKEN,
        update_id=909,
        bot_id=TEST_BOT_IDS[(Platform.BALE).value],
    )
    await finish_update(
        platform=Platform.BALE,
        token=BALE_TOKEN_2,
        update_id=909,
        success=True,
        bot_id=TEST_BOT_IDS[(Platform.BALE).value],
    )
    assert await claim_update(
        platform=Platform.BALE,
        token=BALE_TOKEN_2,
        update_id=909,
        bot_id=TEST_BOT_IDS[(Platform.BALE).value],
    ) == (False, "processed")
    assert database.query(ShopInboundUpdate).count() == 1
