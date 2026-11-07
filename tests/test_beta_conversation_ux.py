"""Shared provider-level customer navigation and identity regression tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from channels.contracts import BotReply, InboundEvent, MediaAttachment, Platform
from models.shop_customer_account_data import ShopCustomerAddress
from models.shop_content import ShopIdentity
from models.shop_customer_navigation import ShopCustomerChatState
from models.shop_customer_navigation import ShopCustomerMediaReceipt
from models.shop_store_commerce import ShopStoreCustomer
from services.shop_multibot_dispatch import _send, dispatch
from tests.test_beta_cart_form_navigation import setup_dispatch
from tests.test_beta_paused_customer_support import NativeClient, raw
from tests.test_shared_cart import db, seed


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_address_draft_survives_menu_and_saves_only_on_confirmation(
    db, monkeypatch, platform,
):
    """Menu labels cannot enter the address field and a draft can resume."""
    scope, native = await setup_dispatch(db, monkeypatch, platform)
    await dispatch(scope, native, raw(callback="ux:address:new"))
    state = db.session.get(ShopCustomerChatState, (scope.bot_id, 101))
    assert state.context_ref == "recipient"
    await dispatch(scope, native, raw(message="مشتری نمونه"))
    assert state.context_ref == "phone"
    await dispatch(scope, native, raw(message="09123456789"))
    assert state.context_ref == "province"
    await dispatch(scope, native, raw(callback="ux:address:province:7"))
    await dispatch(scope, native, raw(callback="ux:address:city:0"))
    await dispatch(scope, native, raw(message="خیابان آزمایش، پلاک ۱۲"))
    assert state.context_ref == "postal_code"
    await dispatch(scope, native, raw(message="🛍 فروشگاه"))
    assert state.action == "idle"
    assert state.address_draft and not db.session.query(ShopCustomerAddress).count()
    await dispatch(scope, native, raw(callback="ux:address:resume"))
    assert state.context_ref == "postal_code"
    await dispatch(scope, native, raw(callback="ux:address:next"))
    await dispatch(scope, native, raw(callback="ux:address:confirm"))
    address = db.session.scalars(select(ShopCustomerAddress)).one()
    assert address.city == "تهران" and address.phone == "09123456789"
    assert address.postal_code == ""


@pytest.mark.asyncio
async def test_new_address_avoids_existing_auto_generated_label(db, monkeypatch):
    """Deleting an earlier address cannot make the next label collide."""
    scope, native = await setup_dispatch(db, monkeypatch, Platform.TELEGRAM)
    await dispatch(scope, native, raw(callback="ux:address:new"))
    state = db.session.get(ShopCustomerChatState, (scope.bot_id, 101))
    customer = db.session.get(ShopStoreCustomer, db.session.scalar(
        select(ShopIdentity.customer_id).where(
            ShopIdentity.bot_id == scope.bot_id,
            ShopIdentity.platform_user_id == 101,
        ),
    ))
    db.session.add_all([
        ShopCustomerAddress(
            store_id=scope.store_id, customer_id=customer.id,
            label=label, recipient="آزمایش", phone="09123456789",
            province="تهران", city="تهران",
            full_address="خیابان آزمایش، پلاک ۱۲",
            is_default=index == 0,
        )
        for index, label in enumerate(("خانه", "نشانی 2"))
    ])
    db.session.commit()
    await dispatch(scope, native, raw(callback="ux:address:new"))
    assert json.loads(state.address_draft)["label"] == "نشانی 3"


def contact_payload(user_id: int | None, phone: str) -> dict:
    """Create one private Bot API contact update with a provider sender."""
    return {"message": {
        "chat": {"id": 101, "type": "private"}, "from": {"id": 101},
        "contact": {"user_id": user_id, "phone_number": phone},
    }}


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_other_contact_and_manual_phone_do_not_verify_account(
    db, monkeypatch, platform,
):
    """Only the sender's native contact changes verified account identity."""
    scope, native = await setup_dispatch(db, monkeypatch, platform)
    await dispatch(scope, native, raw(callback="ux:phone"))
    await dispatch(scope, native, contact_payload(999, "09123456789"))
    identity = db.session.scalar(select(ShopIdentity).where(
        ShopIdentity.bot_id == scope.bot_id,
        ShopIdentity.platform_user_id == 101,
    ))
    customer = db.session.get(ShopStoreCustomer, identity.customer_id)
    assert customer.contact_phone == "09123456789"
    assert customer.phone is None and customer.phone_verified_at is None
    await dispatch(scope, native, raw(callback="ux:phone"))
    await dispatch(scope, native, raw(message="09121111111"))
    assert customer.contact_phone == "09121111111"
    assert customer.phone_verified_at is None
    await dispatch(scope, native, raw(callback="ux:phone"))
    await dispatch(scope, native, contact_payload(101, "09122222222"))
    assert customer.phone == "09122222222"
    assert customer.phone_verified_at.replace(tzinfo=timezone.utc)
    await dispatch(scope, native, raw(callback="ux:phone"))
    await dispatch(scope, native, contact_payload(999, "09123333333"))
    assert customer.phone == "09122222222"
    assert customer.contact_phone == "09123333333"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_requested_media_is_resent_on_every_click(db, monkeypatch, platform):
    """Repeat requests deliver a new file while retaining older messages."""
    scope, _ = await setup_dispatch(db, monkeypatch, platform)

    class MediaClient:
        """Simulate confirmed delivery receipts from Bale."""

        def __init__(self):
            """Track each media send and the navigational text."""
            self.media = []
            self.messages = []

        async def send_media(self, chat_id, attachment):
            """Record a persistent on-demand file."""
            self.media.append(attachment.storage_key)
            return 87 + len(self.media)

        async def send(self, chat_id, reply, *, edit_message_id=None):
            """Record the mutable UI separately from the file."""
            self.messages.append(reply.text)
            return edit_message_id or 89

    client = MediaClient()
    if platform == Platform.TELEGRAM:
        monkeypatch.setattr(
            "services.shop_multibot_dispatch.TelegramTransport",
            lambda *args, **kwargs: client,
        )
    event = InboundEvent(
        platform=platform, chat_id=101, user_id=101,
        callback_data="shop:file:1",
    )
    key = "a" * 32 + ".pdf"
    reply = BotReply(
        "فایل محصول", attachments=(MediaAttachment(
            key, "document", "application/pdf",
        ),),
    )
    await _send(scope, client, 101, reply, event=event)
    await _send(scope, client, 101, reply, event=event)
    assert client.media == [key, key]
    assert "قبلاً" not in client.messages[-1]
    assert db.session.get(ShopCustomerMediaReceipt, (scope.bot_id, 101, key)).message_id == 89


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_stale_inline_button_cannot_mutate_active_cart(
    db, monkeypatch, platform,
):
    """A superseded product keyboard is acknowledged but never executed."""
    scope, _ = await setup_dispatch(db, monkeypatch, platform)
    state = ShopCustomerChatState(
        bot_id=scope.bot_id, platform_user_id=101,
        store_id=scope.store_id, ui_message_id=100,
        expires_at=datetime.now(timezone.utc),
    )
    db.session.add(state)
    db.session.commit()
    payload = raw(callback="shop:add:1")
    payload["callback_query"]["message"]["message_id"] = 99
    class StaleClient(NativeClient):
        """Record removal of a superseded Telegram inline keyboard."""

        async def edit_message_reply_markup(self, **kwargs):
            """Simulate the Bot API acknowledgement of markup removal."""
            self.messages.append(kwargs)

    result = await dispatch(scope, StaleClient(), payload)
    assert result["status"] == "stale_callback"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("action", ["g", "d"])
async def test_product_card_callback_works_when_gallery_footer_is_active(
    db, monkeypatch, platform, action,
):
    """A gallery card may open its product despite a newer footer message."""
    product, _ = seed(db)
    scope, _ = await setup_dispatch(db, monkeypatch, platform)

    class CardClient(NativeClient):
        """Represent provider markup editing when a callback is rejected."""

        async def edit_message_reply_markup(self, **kwargs):
            """Accept Telegram's request to remove obsolete buttons."""
            self.messages.append(kwargs)

    native = CardClient()
    db.session.add(ShopCustomerChatState(
        bot_id=scope.bot_id, platform_user_id=101,
        store_id=scope.store_id, ui_message_id=100,
        expires_at=datetime.now(timezone.utc),
    ))
    db.session.commit()
    delivered = []

    async def capture_send(context, client, chat_id, reply, *, event=None):
        """Capture the result after real dispatch and catalog authorization."""
        delivered.append(reply)

    monkeypatch.setattr("services.shop_multibot_dispatch._send", capture_send)
    payload = raw(callback=f"{action}:{product.id}:0:0")
    payload["callback_query"]["message"]["message_id"] = 99
    result = await dispatch(scope, native, payload)

    assert result["status"] == "processed"
    assert native.acks == ["cb"]
    assert product.name in delivered[0].text
