"""Legacy receiver maintenance gates preserve the same bounded after-sale help."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from aiogram.types import Update

from channels.contracts import Platform
from middleware.shop_bot_gate import ShopBotOperationMiddleware
from models.shop_bot_operations import ShopBotOperations
from models.shop_bot_profile import ShopBotProfile
from tests.legacy_shop_entrypoints import legacy_function
from tests.test_beta_paused_customer_support import NativeClient, account, raw
from tests.test_shared_cart import db as shared_db
from tests.test_shared_cart import event


@pytest.fixture
def db():
    """Use real identity, operation and support rows in disposable SQLite."""
    yield from shared_db.__wrapped__()


class NativeSDKBot(NativeClient):
    """Capture Aiogram bound method objects as well as transport requests."""

    async def __call__(self, method, **_kwargs):
        """Record actual middleware sends without an HTTP client or provider."""
        if method.__api_method__ == "sendMessage":
            self.messages.append({"chat_id": method.chat_id, "text": method.text})
        elif method.__api_method__ == "answerCallbackQuery":
            self.acks.append(method.callback_query_id)
        else:
            raise AssertionError("Unexpected native SDK method")
        return True


def policy(db, context, state):
    """Persist actual legacy operation/profile gates rather than mock verdicts."""
    db.add(ShopBotOperations(bot_id=context.bot_id, desired_state=state))
    db.add(ShopBotProfile(
        platform=context.platform.value, maintenance_enabled=state == "maintenance",
    ))
    db.session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("state", ["paused", "maintenance"])
@pytest.mark.parametrize("requested", ["/support", "/paysupport", "ux:support", "shop:orders"])
async def test_legacy_entry_points_keep_help_and_order_discovery(
    db, platform, state, requested,
):
    """The preserved legacy dispatchers provide help while shopping is paused."""
    context, _ = await account(db, platform)
    policy(db, context, state)

    @asynccontextmanager
    async def sessions():
        """Keep every legacy query on the real disposable database."""
        yield db

    native = NativeClient()
    if platform == Platform.TELEGRAM:
        handler = legacy_function("channels/telegram_handlers.py", "_shop_reply")
        reply = await handler(event(
            platform, text=requested if requested.startswith("/") else None,
            callback=None if requested.startswith("/") else requested,
        ), db)
        assert reply is not None
        text = reply.text
    else:
        handler = legacy_function(
            "bot.py", "_process_bale_update", get_db_session=sessions,
            BaleTransport=lambda *_args, **_kwargs: native,
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            bale_http_client=object(),
        )))
        result = await handler(request, (
            raw(message=requested) if requested.startswith("/") else raw(callback=requested)
        ))
        assert result["status"] == "ok"
        text = native.messages[-1]["text"]
    assert "نگهداری" not in text
    assert "متوقف" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", ["/support", "/paysupport", "ux:support", "shop:orders"])
@pytest.mark.parametrize("state", ["paused", "maintenance"])
async def test_legacy_telegram_global_middleware_serves_only_bounded_help(
    db, monkeypatch, requested, state,
):
    """The global gate answers after-sale routes before unrelated legacy handlers."""
    context, _ = await account(db, Platform.TELEGRAM)
    policy(db, context, state)

    @asynccontextmanager
    async def sessions():
        """Read real operation, identity and ticket scope in the global gate."""
        yield db

    monkeypatch.setattr("middleware.shop_bot_gate.session_maker", sessions)
    native = NativeSDKBot()
    payload = raw(message=requested) if requested.startswith("/") else raw(callback=requested)
    payload["update_id"] = 1
    message = payload.get("message") or payload["callback_query"]["message"]
    message.update({"message_id": 1, "date": 1})
    for sender in (message["from"], payload.get("callback_query", {}).get("from", {})):
        sender.update({"is_bot": False, "first_name": "Synthetic"})
    update = Update.model_validate(payload, context={"bot": native})

    async def unrelated_handler(*_args):
        """Paused support must not reopen the general legacy shopping chain."""
        pytest.fail("A general legacy handler ran during paused support")

    await ShopBotOperationMiddleware()(unrelated_handler, update, {})
    assert len(native.messages) == 1
    assert "نگهداری" not in native.messages[0]["text"]
    assert "متوقف" not in native.messages[0]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", ["ux:support", "shop:refundorder:1"])
async def test_disabled_legacy_telegram_middleware_keeps_chat_fail_closed(
    db, monkeypatch, requested,
):
    """Revocation does not acquire a support/refund-prefix handler bypass."""
    context, _ = await account(db, Platform.TELEGRAM)
    policy(db, context, "disabled")

    @asynccontextmanager
    async def sessions():
        """Read the disabled state without opening any provider connection."""
        yield db

    monkeypatch.setattr("middleware.shop_bot_gate.session_maker", sessions)
    native = NativeSDKBot()
    payload = raw(callback=requested)
    payload["update_id"] = 1
    payload["callback_query"]["message"].update({"message_id": 1, "date": 1})
    for sender in (
        payload["callback_query"]["from"], payload["callback_query"]["message"]["from"],
    ):
        sender.update({"is_bot": False, "first_name": "Synthetic"})
    update = Update.model_validate(payload, context={"bot": native})

    async def unrelated_handler(*_args):
        """Only verified financial receipt events may bypass disabled chat."""
        pytest.fail("Disabled chat reached a legacy handler")

    await ShopBotOperationMiddleware()(unrelated_handler, update, {})
    assert native.messages == []
    assert native.acks == ["cb"]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["paused", "maintenance", "disabled"])
async def test_legacy_telegram_payment_callback_cannot_skip_the_operation_gate(db, state):
    """A stale payment button cannot enter the invoice branch while shopping is off."""
    context, _ = await account(db, Platform.TELEGRAM)
    policy(db, context, state)

    async def forbidden_invoice(*_args, **_kwargs):
        """A denied action must never reach the provider invoice boundary."""
        pytest.fail("A paused legacy Telegram callback attempted an invoice")

    native = NativeClient()

    async def acknowledge():
        """Capture the handler's mandatory callback acknowledgement."""
        native.acks.append("cb")

    callback = SimpleNamespace(
        data="shop:pay:1", id="cb", answer=acknowledge, bot=native,
        from_user=SimpleNamespace(id=101),
        message=SimpleNamespace(chat=SimpleNamespace(id=101, type="private")),
    )
    handler = legacy_function(
        "channels/telegram_handlers.py", "shop_catalog_button",
        send_order_invoice=forbidden_invoice,
    )
    await handler(callback, db)
    assert native.acks == ["cb"]
    assert bool(native.messages) is (state != "disabled")
