"""Keep native Telegram sender fields usable by the shared polling dispatcher."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

from aiogram.types import Update
import pytest

import db as database
from channels.contracts import BotReply, InlineAction
from models.shop_content import ShopIdentity
from models.shop_customer_navigation import ShopCustomerChatState
from models.shop_delivery import ShopInboundUpdate
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot, ShopBotCredential
from models.shop_multibot_receiver import ShopBotReceiver
from services.shop_bot_secrets import encrypt_for_bot
from services.shop_customer_views import prepare_reply
from tests import test_shared_payment_settlement as payments


class ReceiverDb(payments.OfflineDB):
    """Retain real SQLite rows for receiver, identity and receipt transitions."""

    async def get(self, model, key, **kwargs):
        """Forward the supervisor's row-lock options to the local ORM."""
        return self.session.get(model, key, **kwargs)

    async def run_sync(self, operation):
        """Resolve encrypted fake credentials through the actual vault service."""
        return operation(self.session)

    async def rollback(self):
        """Discard uncommitted handler work before publishing its reply."""
        self.session.rollback()


class NativePollingClient:
    """Supply real aiogram updates and capture native outgoing API requests."""

    def __init__(self, update: Update, supervisor, token: str) -> None:
        """Bind only synthetic data; no HTTP session or provider SDK is created."""
        self.update = update
        self.supervisor = supervisor
        self.token = token
        self.messages = []
        self.edits = []

    async def get_webhook_info(self):
        """Report no webhook without network access."""
        return SimpleNamespace(url="")

    async def get_updates(self, *, offset: int, **_kwargs):
        """Stop when the real poller has committed this update's next offset."""
        if offset == 302:
            self.supervisor.stop_event.set()
        return [self.update]

    async def send_message(self, **payload):
        """Capture messages emitted by the real dispatcher and native adapter."""
        self.messages.append(payload)
        return SimpleNamespace(message_id=101)

    async def answer_callback_query(self, **_payload):
        """Acknowledge a synthetic callback without contacting Telegram."""
        return True

    async def edit_message_text(self, **payload):
        """Capture navigation updates on the callback's existing message."""
        self.edits.append(payload)
        return SimpleNamespace(message_id=payload["message_id"])


@pytest.fixture
def receiver_db(monkeypatch):
    """Reuse the complete isolated schema while adapting receiver row locks."""
    fixtures = payments.db.__wrapped__(monkeypatch)
    source = next(fixtures)
    try:
        yield ReceiverDb(source.session)
    finally:
        fixtures.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("message", "callback_query"))
async def test_native_polling_preserves_sender_for_actual_dispatch(
    receiver_db, monkeypatch, kind,
):
    """A polled message/callback must send once and retain its Bot-scoped actor."""
    # PostgreSQL lease election is covered by the Beta integration runner.
    # This regression keeps serialization, dispatcher, vault and ORM real.
    monkeypatch.setattr(database, "engine", object(), raising=False)
    runtime = import_module("services.shop_multibot_supervisor")
    bot_id = str(uuid4())
    token = "900001:" + "A" * 35
    receiver_db.add(ShopBot(
        id=bot_id, store_id=DEFAULT_STORE_ID, slug="polling-alias-test",
        name="Synthetic polling bot", platform="telegram", provider_bot_id=900001,
        status="active", runtime_owner="registry", credential_version=1,
    ))
    await receiver_db.flush()
    receiver_db.add(ShopBotCredential(
        id=str(uuid4()), bot_id=bot_id, version=1, source="encrypted",
        state="active", ciphertext=encrypt_for_bot(bot_id, "telegram", token),
    ))
    row = ShopBotReceiver(
        bot_id=bot_id, binding_id=str(uuid4()), mode="polling", state="active",
        webhook_secret_ciphertext="unused", webhook_secret_digest="a" * 64,
        credential_version=1,
    )
    receiver_db.add(row)
    await receiver_db.commit()

    actor = {"id": 101, "is_bot": False, "first_name": "Synthetic customer"}
    message = {
        "message_id": 1, "date": 1793836800, "from": actor,
        "chat": {"id": 101, "type": "private"}, "text": "/start",
    }
    if kind == "message":
        body = message
    else:
        reply, view = prepare_reply(BotReply(
            "محصولات", ((InlineAction("دسته‌ها", "shop:categories"),),),
        ))
        receiver_db.add(ShopCustomerChatState(
            bot_id=bot_id, store_id=DEFAULT_STORE_ID, platform_user_id=101,
            ui_message_id=message["message_id"], expires_at=datetime.now(UTC),
            view_state={"version": 1, "active": view},
        ))
        await receiver_db.commit()
        body = {
            "id": "synthetic-callback", "from": actor, "chat_instance": "qa",
            "message": message, "data": reply.rows[0][0].callback_data,
        }
    update = Update.model_validate({"update_id": 301, kind: body})
    supervisor = runtime.MultiBotSupervisor(SimpleNamespace())
    native = NativePollingClient(update, supervisor, token)

    @asynccontextmanager
    async def sessions():
        """Keep the actual receipt/identity writes inside the disposable ORM."""
        yield receiver_db

    @asynccontextmanager
    async def provider(platform, secret, *, bot_id: str):
        """Fail closed outside the exact synthetic credential and bot binding."""
        assert platform == "telegram" and secret == token
        assert bot_id == row.bot_id
        yield native

    async def owned_lease():
        """Replace only the external PostgreSQL lease health check."""
        return None

    monkeypatch.setattr(database, "session_maker", sessions)
    monkeypatch.setattr(runtime, "session_maker", sessions)
    monkeypatch.setattr("services.shop_multibot_dispatch.session_maker", sessions)
    # Runtime owns duplicate Inbox IDs even while disabled. Its new read-only
    # boundary must use this same actual SQLite database as the receiver.
    monkeypatch.setattr("services.shop_runtime.ingress.session_maker", sessions)
    monkeypatch.setattr(runtime, "provider_client", provider)
    monkeypatch.setattr(supervisor, "check_lease", owned_lease)
    await asyncio.wait_for(supervisor._poll(bot_id), timeout=3)

    if kind == "message":
        # /start installs the persistent main keyboard and then shows UI.
        assert len(native.messages) == 2, "Polling discarded the sender"
        assert all(message["chat_id"] == 101 for message in native.messages)
    else:
        # Inline navigation edits its origin rather than posting another UI.
        assert native.messages == []
        assert len(native.edits) == 1, "Polling discarded the callback"
        assert native.edits[0]["chat_id"] == 101
    assert row.next_update_id == 302
    receipt = receiver_db.session.query(ShopInboundUpdate).one()
    assert receipt.bot_id == bot_id and receipt.status == "processed"
    identity = receiver_db.session.query(ShopIdentity).one()
    assert identity.bot_id == bot_id and identity.platform_user_id == 101
