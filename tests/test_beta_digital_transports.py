"""Native digital transports and worker Bot ownership without provider calls."""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendDocument, SendMessage
from aiogram.types import Message
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

import config
import db
from channels.bale import BaleTransport
from channels.contracts import MediaAttachment
from channels.telegram import TelegramTransport
from models.shop_delivery import ShopRemoteFile
from models.shop_multibot import ShopBot, ShopStore
from services.shop_digital_fulfillment import DigitalSend
from services.shop_media_delivery import bot_fingerprint
from tests.schema_support import create_shop_schema
from utils.telegram import create_bot

FAKE_TOKEN = "12345678:" + "A" * 35


class TelegramSession(BaseSession):
    """Run native Aiogram methods against deterministic, local receipts."""

    def __init__(self) -> None:
        """Keep requests and session closure available for assertions."""
        super().__init__()
        self.requests = []
        self.closed = False

    async def close(self) -> None:
        """Record the worker's ownership of the Bot session."""
        self.closed = True

    async def make_request(self, bot, method, timeout=None):
        """Validate a normal Telegram Message without opening a socket."""
        assert isinstance(method, (SendMessage, SendDocument))
        self.requests.append(method)
        return Message.model_validate({
            "message_id": 202,
            "date": datetime.now(timezone.utc),
            "chat": {"id": method.chat_id, "type": "private"},
            "document": {
                "file_id": "telegram-uploaded-document",
                "file_unique_id": "telegram-unique-document",
            },
        })

    async def stream_content(self, *args, **kwargs):
        """Forbid any file download from the fake provider."""
        raise AssertionError("These tests never download provider files.")
        yield b""  # pragma: no cover


class BaleResponse:
    """Provide the ordinary Bale JSON response envelope offline."""

    status = 200

    async def __aenter__(self):
        """Enter the fake HTTP response."""
        return self

    async def __aexit__(self, *args):
        """Close the fake response without suppressing failures."""
        return False

    async def json(self, *, content_type=None):
        """Return a provider-confirmed numeric Message ID."""
        return {"ok": True, "result": {"message_id": 303}}


class BaleSession:
    """Capture requests at the HTTP boundary instead of calling Bale."""

    def __init__(self) -> None:
        """Start with no outgoing requests."""
        self.requests = []

    def post(self, url, *, json, timeout):
        """Capture the JSON body while keeping the real transport active."""
        self.requests.append((url, json))
        return BaleResponse()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "bale"])
async def test_digital_license_uses_a_real_line_break(platform):
    """A buyer receives the caption and exact license on separate lines."""
    payload = DigitalSend(
        delivery_id="delivery-1", bot_id="bot-1", chat_id=101,
        kind="license", caption="🔐 کد خریداری‌شده:",
        license_text="LICENSE-1234",
    )
    if platform == "telegram":
        session = TelegramSession()
        transport = TelegramTransport(create_bot(FAKE_TOKEN, session))
        assert await transport.deliver_digital(payload) == "202"
        assert len(session.requests) == 1
        message = session.requests[0]
        assert message.parse_mode is None
        assert message.protect_content is True
        text = message.text
    else:
        session = BaleSession()
        transport = BaleTransport("fake-bale-token", session)
        assert await transport.deliver_digital(payload) == "303"
        assert len(session.requests) == 1
        endpoint, body = session.requests[0]
        assert endpoint.endswith("/botfake-bale-token/sendMessage")
        text = body["text"]

    assert text == "🔐 کد خریداری‌شده:\nLICENSE-1234"


class OfflineSession:
    """Adapt the real local ORM for worker resolution and file cache writes."""

    def __init__(self, session: Session) -> None:
        """Keep one test-scoped SQLite transaction."""
        self.session = session

    async def get(self, model, key):
        """Load the server-selected Bot from the actual ORM."""
        return self.session.get(model, key)

    async def run_sync(self, operation):
        """Let the worker resolve its test-only credential."""
        return operation(self.session)

    async def scalar(self, query):
        """Execute real Bot-scoped cache reads."""
        return self.session.scalar(query)

    async def execute(self, statement):
        """Execute the production cache upsert against the local database."""
        # SQLite has no ON CONFLICT ON CONSTRAINT syntax. Preserve the real
        # statement's bound values and equivalent unique-key upsert locally.
        parameters = statement.compile().params
        values = {
            column.name: parameters[column.name]
            for column in statement.table.c if column.name in parameters
        }
        local = insert(ShopRemoteFile).values(**values)
        local = local.on_conflict_do_update(
            index_elements=[
                "platform", "bot_fingerprint", "storage_key", "delivery_kind",
            ],
            set_={"remote_file_id": values["remote_file_id"]},
        )
        return self.session.execute(local)

    async def commit(self) -> None:
        """Persist the local file-ID receipt."""
        self.session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_exists", [False, True])
async def test_worker_telegram_media_cache_uses_registered_bot_id(
    monkeypatch, tmp_path, cache_exists,
):
    """Registered Bot sends reuse and persist only their canonical cache row."""
    # The offline test config intentionally has no database engine. Import the
    # opt-in worker with an inert placeholder; this test never starts main().
    monkeypatch.setattr(db, "engine", SimpleNamespace(), raising=False)
    worker = importlib.import_module("workers.shop_customer_notifications")
    monkeypatch.setattr(config, "SHOP_RELAY_POOL_ENABLED", False)
    monkeypatch.setattr(config, "SHOP_MEDIA_ROOT", str(tmp_path))
    provider = TelegramSession()
    monkeypatch.setattr(
        worker, "resolve_active_token", lambda session, *, bot_id: FAKE_TOKEN,
    )

    @asynccontextmanager
    async def provider_client(platform, token, *, bot_id):
        """Exercise real Telegram media logic through the exact registered bot."""
        assert platform == "telegram" and token == FAKE_TOKEN
        assert bot_id == expected_bot_id
        client = create_bot(token, provider)
        try:
            yield client
        finally:
            await client.session.close()

    monkeypatch.setattr("services.shop_multibot_client.provider_client", provider_client)

    key = "a" * 32 + ".pdf"
    (tmp_path / key).write_bytes(b"%PDF-1.4 test media")
    store_id, bot_id = str(uuid4()), str(uuid4())
    expected_bot_id = bot_id
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_shop_schema(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(ShopStore(
            id=store_id, slug="registry-store", name="Store", state="active",
        ))
        session.add(ShopBot(
            id=bot_id, store_id=store_id, slug="registered-telegram",
            name="Telegram", platform="telegram", status="active",
            runtime_owner="registry", version=1, credential_version=1,
        ))
        if cache_exists:
            session.add(ShopRemoteFile(
                bot_id=bot_id, platform="telegram",
                bot_fingerprint=bot_fingerprint(FAKE_TOKEN),
                storage_key=key, delivery_kind="document",
                remote_file_id="registered-bot-cached-document",
            ))
        session.commit()
        adapter = OfflineSession(session)

        @asynccontextmanager
        async def session_maker():
            """Keep both resolution and cache writes inside the disposable DB."""
            yield adapter

        monkeypatch.setattr(worker, "session_maker", session_maker)
        monkeypatch.setattr(db, "session_maker", session_maker)
        async with worker._transport_for_bot(bot_id) as transport:
            await transport.send_media(101, MediaAttachment(
                storage_key=key, kind="document", mime_type="application/pdf",
            ))

        assert provider.closed is True
        assert len(provider.requests) == 1
        cache = session.scalar(select(ShopRemoteFile))
        assert cache.bot_id == bot_id
        if cache_exists:
            assert provider.requests[0].document == (
                "registered-bot-cached-document"
            )
        else:
            assert cache.remote_file_id == "telegram-uploaded-document"
    engine.dispose()
