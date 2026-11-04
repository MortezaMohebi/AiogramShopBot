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
    Base.metadata.create_all(
        engine,
        tables=[ShopRemoteFile.__table__, ShopInboundUpdate.__table__],
    )
    with Session(engine, expire_on_commit=False) as session:
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
    )
    assert (fresh, state) == (True, "processing")
    again, state = await claim_update(
        platform=Platform.TELEGRAM,
        token=TELEGRAM_TOKEN,
        update_id=200,
    )
    assert (again, state) == (False, "processing")
    await finish_update(
        platform=Platform.TELEGRAM,
        token=TELEGRAM_TOKEN,
        update_id=200,
        success=True,
    )
    again, state = await claim_update(
        platform=Platform.TELEGRAM,
        token=TELEGRAM_TOKEN,
        update_id=200,
    )
    assert (again, state) == (False, "processed")
    assert database.query(ShopInboundUpdate).count() == 1


@pytest.mark.asyncio
async def test_webhook_same_numeric_id_is_unique_to_bot_and_platform(database):
    """Bale and Telegram can have identical update IDs without collision."""
    for platform, token, bot_id in [
        (Platform.TELEGRAM, TELEGRAM_TOKEN, str(uuid4())),
        (Platform.BALE, BALE_TOKEN, str(uuid4())),
        (Platform.BALE, BALE_TOKEN_2, str(uuid4())),
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
        platform=Platform.BALE, token=BALE_TOKEN, update_id=303
    )
    await finish_update(
        platform=Platform.BALE,
        token=BALE_TOKEN,
        update_id=303,
        success=False,
    )
    again, state = await claim_update(
        platform=Platform.BALE, token=BALE_TOKEN, update_id=303
    )
    assert (again, state) == (False, "needs_review")


@pytest.mark.asyncio
async def test_cached_file_id_never_crosses_bot_or_platform_boundary(database):
    """A known Bale file ID remains inaccessible to other Bale bots/Telegram."""
    key = "a" * 32 + ".png"
    first_bot = bot_fingerprint(BALE_TOKEN)
    database.add(
        ShopRemoteFile(
            platform="bale", bot_fingerprint=first_bot,
            storage_key=key, delivery_kind="photo",
            remote_file_id="bale-first-bot-file",
        )
    )
    database.commit()
    assert await cached_file_id(
        platform="bale", bot_key=first_bot,
        storage_key=key, kind="photo",
    ) == "bale-first-bot-file"
    assert await cached_file_id(
        platform="bale", bot_key=bot_fingerprint(BALE_TOKEN_2),
        storage_key=key, kind="photo",
    ) is None
    assert await cached_file_id(
        platform="telegram", bot_key=bot_fingerprint(TELEGRAM_TOKEN),
        storage_key=key, kind="photo",
    ) is None
    assert await cached_file_id(
        platform="bale", bot_key=first_bot,
        storage_key=key, kind="document",
    ) is None


@pytest.mark.asyncio
async def test_token_rotation_keeps_the_original_update_receipt(database):
    """Rotating a credential cannot replay an update or hide its final state."""
    await claim_update(platform=Platform.BALE, token=BALE_TOKEN, update_id=909)
    await finish_update(
        platform=Platform.BALE, token=BALE_TOKEN_2,
        update_id=909, success=True,
    )
    assert await claim_update(
        platform=Platform.BALE, token=BALE_TOKEN_2, update_id=909,
    ) == (False, "processed")
    assert database.query(ShopInboundUpdate).count() == 1
