"""Paid-customer help and complete support replies remain usable while paused."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from channels.contracts import Platform
from models.shop_content import ShopOrder
from models.shop_customer_crm import ShopCustomerProfile
from models.shop_customer_navigation import ShopCustomerChatState
from models.shop_customer_support import ShopSupportMessage, ShopSupportTicket
from models.shop_multibot import ShopStore
from models.shop_staff import ShopStaff
from services.shop_bot_context import resolve_legacy_bot_context
from services.shop_customer_support import CustomerSupportFlow
from services.shop_identity import register_customer
from services.shop_multibot_dispatch import dispatch
from tests.test_shared_cart import db as shared_db
from tests.test_shared_cart import event


@pytest.fixture
def db():
    """Use the complete disposable shared-shop schema for real ownership checks."""
    yield from shared_db.__wrapped__()


class NativeClient:
    """Capture actual normalized Telegram/Bale sends without network access."""

    def __init__(self):
        """Start an independent provider message and callback log."""
        self.messages = []
        self.acks = []

    async def send_message(self, **kwargs):
        """Record TelegramTransport's native payload."""
        self.messages.append(kwargs)

    async def send(self, chat_id, reply):
        """Record the equivalent Bale transport payload."""
        self.messages.append({"chat_id": chat_id, "text": reply.text, "rows": reply.rows})

    async def answer_callback_query(self, **kwargs):
        """Acknowledge a native Telegram callback."""
        self.acks.append(kwargs["callback_query_id"])

    async def acknowledge(self, query_id):
        """Acknowledge a native Bale callback."""
        self.acks.append(query_id)


async def account(db, platform):
    """Resolve an actual registered customer and trusted provider context."""
    context = await resolve_legacy_bot_context(db, authenticated_platform=platform)
    identity = await register_customer(
        db, bot_id=context.bot_id, platform=platform, platform_user_id=101,
    )
    return context, identity


def raw(*, callback=None, message=None):
    """Build the authenticated private-chat structure accepted by both providers."""
    sender = {"id": 101}
    body = {"chat": {"id": 101, "type": "private"}, "from": sender}
    if callback:
        return {"callback_query": {
            "id": "cb", "from": sender, "message": body, "data": callback,
            "chat_instance": "qa-private-chat",
        }}
    return {"message": {**body, "text": message or "/support"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("state", ["paused", "maintenance"])
@pytest.mark.parametrize("requested", ["/support", "/paysupport", "ux:support", "shop:orders"])
async def test_paused_customers_can_discover_support_and_order_history(
    db, monkeypatch, platform, state, requested,
):
    """The shopping gate cannot strand existing customers outside help/history."""
    context, _ = await account(db, platform)

    @asynccontextmanager
    async def sessions():
        """Use the real relational fixture throughout dispatch."""
        yield db

    monkeypatch.setattr("services.shop_multibot_dispatch.session_maker", sessions)
    native = NativeClient()
    result = await dispatch(
        replace(context, status=state), native,
        raw(message=requested) if requested.startswith("/") else raw(callback=requested),
    )
    assert result["status"] == "processed"
    assert native.messages
    assert "نگهداری" not in native.messages[-1]["text"]
    assert db.session.scalars(select(ShopOrder)).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_paused_support_can_accept_only_explicit_timed_ticket_input(
    db, monkeypatch, platform,
):
    """A support form may continue during a pause without enabling shopping input."""
    context, identity = await account(db, platform)

    @asynccontextmanager
    async def sessions():
        """Use the durable local FSM and ticket messages."""
        yield db

    monkeypatch.setattr("services.shop_multibot_dispatch.session_maker", sessions)
    context = replace(context, status="paused")
    native = NativeClient()
    result = await dispatch(context, native, raw(callback="ux:ticket:topic:payment"))
    assert result["status"] == "processed"
    result = await dispatch(context, native, raw(message="برای پرداخت ثبت‌شده کمک می‌خواهم."))
    assert result["status"] == "processed"
    ticket = db.session.scalars(select(ShopSupportTicket)).one()
    assert ticket.origin_identity_id == identity.id
    assert ticket.topic == "payment"
    assert db.session.scalars(select(ShopSupportMessage.body)).one() == "برای پرداخت ثبت‌شده کمک می‌خواهم."
    assert db.session.scalars(select(ShopOrder)).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("callback", [
    "shop:add:1", "shop:checkout", "shop:pay:1", "ux:ticket:topic:payment:shop:pay:1",
])
async def test_paused_support_allowlist_cannot_enable_new_commerce(
    db, monkeypatch, platform, callback,
):
    """Only exact support actions pass; prefixes and payment actions remain gated."""
    context, _ = await account(db, platform)

    @asynccontextmanager
    async def sessions():
        """Keep all possible writes on the disposable database."""
        yield db

    monkeypatch.setattr("services.shop_multibot_dispatch.session_maker", sessions)
    result = await dispatch(
        replace(context, status="paused"), NativeClient(), raw(callback=callback),
    )
    assert result["status"] == "maintenance"
    assert db.session.scalars(select(ShopOrder)).all() == []
    assert db.session.scalars(select(ShopSupportTicket)).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_disabled_bot_does_not_gain_a_general_support_or_refund_bypass(
    db, monkeypatch, platform,
):
    """Disabled receivers fail closed for ordinary chat, including stale buttons."""
    context, _ = await account(db, platform)

    @asynccontextmanager
    async def sessions():
        """Use the same existing customer without provider activity."""
        yield db

    monkeypatch.setattr("services.shop_multibot_dispatch.session_maker", sessions)
    native = NativeClient()
    for request in ("ux:support", "shop:refundorder:1"):
        result = await dispatch(
            replace(context, status="disabled"), native, raw(callback=request),
        )
        assert result["status"] == "disabled"
    assert native.messages == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_support_thread_keeps_all_messages_and_full_unicode_bodies(db, platform):
    """Every character in a long conversation must be reachable through bounded pages."""
    context, identity = await account(db, platform)
    staff = ShopStaff(username="support", password_hash="unused", role="sales")
    db.add(staff)
    ticket = ShopSupportTicket(
        store_id=context.store_id, customer_id=identity.customer_id,
        bot_id=context.bot_id, origin_identity_id=identity.id, topic="payment",
    )
    db.add(ticket)
    await db.flush()
    bodies = [f"پیام {index}: بدون حذف متن" for index in range(13)]
    bodies[5] = "📦" * 4000
    for body in bodies:
        db.add(ShopSupportMessage(
            ticket_id=ticket.id, store_id=context.store_id,
            sender_kind="staff", staff_id=staff.id, body=body,
        ))
    await db.commit()
    flow = CustomerSupportFlow(bot_context=context)
    reply = await flow.reply(event(platform, callback=f"ux:ticket:view:{ticket.id}"), db)
    reconstructed = []
    current = (0, 0)
    for _ in range(40):
        assert len(reply.text.encode("utf-16-le")) // 2 <= 4096
        reconstructed.append(reply.text.split("\n\n", 1)[1])
        following = []
        for row in reply.rows:
            for action in row:
                assert len(action.callback_data.encode("utf-8")) <= 64
                if action.callback_data.startswith("ux:ticket:page:"):
                    parts = action.callback_data.split(":")
                    key = int(parts[-2]), int(parts[-1])
                    if key > current:
                        following.append((key, action.callback_data))
        if not following:
            break
        current, callback = min(following)
        reply = await flow.reply(event(platform, callback=callback), db)
    else:
        pytest.fail("Support conversation pagination did not terminate")
    assert "".join(reconstructed) == "".join(bodies)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("state_kind", ["expired", "wrong_store", "cart_input"])
async def test_paused_free_text_requires_live_store_owned_ticket_state(
    db, monkeypatch, platform, state_kind,
):
    """Stale, foreign or shopping state cannot admit chat into paused support."""
    context, _ = await account(db, platform)
    foreign = ShopStore(id=str(uuid4()), slug="foreign-state", name="Foreign")
    db.add(foreign)
    await db.flush()
    db.add(ShopCustomerChatState(
        bot_id=context.bot_id, platform_user_id=101,
        store_id=foreign.id if state_kind == "wrong_store" else context.store_id,
        action="product_search" if state_kind == "cart_input" else "ticket_input",
        context_ref="topic:general",
        expires_at=datetime.now(UTC) + timedelta(
            minutes=-1 if state_kind == "expired" else 15,
        ),
    ))
    await db.commit()

    @asynccontextmanager
    async def sessions():
        """Read the persisted form at the actual dispatcher gate."""
        yield db

    monkeypatch.setattr("services.shop_multibot_dispatch.session_maker", sessions)
    result = await dispatch(
        replace(context, status="paused"), NativeClient(), raw(message="متن آزاد"),
    )
    assert result["status"] == "maintenance"
    assert db.session.scalars(select(ShopSupportTicket)).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_ticket_pages_recheck_ticket_message_and_store_ownership(db, platform):
    """Tampered page keys and corrupt foreign-Store rows cannot expose replies."""
    context, identity = await account(db, platform)
    outsider = await register_customer(
        db, bot_id=context.bot_id, platform=platform, platform_user_id=202,
    )
    foreign = ShopStore(id=str(uuid4()), slug="foreign-message", name="Foreign")
    staff = ShopStaff(username="paging", password_hash="unused", role="sales")
    db.add(foreign)
    db.add(staff)
    await db.flush()
    own_ticket = ShopSupportTicket(
        store_id=context.store_id, customer_id=identity.customer_id,
        bot_id=context.bot_id, origin_identity_id=identity.id, topic="payment",
    )
    other_ticket = ShopSupportTicket(
        store_id=context.store_id, customer_id=outsider.customer_id,
        bot_id=context.bot_id, origin_identity_id=outsider.id, topic="order",
    )
    db.add(own_ticket)
    db.add(other_ticket)
    await db.flush()
    visible = ShopSupportMessage(
        ticket_id=own_ticket.id, store_id=context.store_id,
        sender_kind="staff", staff_id=staff.id, body="پاسخ متعلق به شما",
    )
    hidden = ShopSupportMessage(
        ticket_id=own_ticket.id, store_id=context.store_id,
        sender_kind="system", body="SYSTEM-SECRET",
    )
    foreign_message = ShopSupportMessage(
        ticket_id=own_ticket.id, store_id=foreign.id,
        sender_kind="staff", staff_id=staff.id, body="STORE-SECRET",
    )
    other_message = ShopSupportMessage(
        ticket_id=other_ticket.id, store_id=context.store_id,
        sender_kind="staff", staff_id=staff.id, body="CUSTOMER-SECRET",
    )
    for message in (visible, hidden, foreign_message, other_message):
        db.add(message)
    await db.commit()
    flow = CustomerSupportFlow(bot_context=context)
    reply = await flow.reply(event(platform, callback=f"ux:ticket:view:{own_ticket.id}"), db)
    assert visible.body in reply.text
    callbacks = [
        f"ux:ticket:view:{other_ticket.id}",
        f"ux:ticket:page:{other_ticket.id}:{other_message.id}:0",
        f"ux:ticket:page:{own_ticket.id}:{other_message.id}:0",
        f"ux:ticket:page:{own_ticket.id}:{foreign_message.id}:0",
        f"ux:ticket:page:{own_ticket.id}:{hidden.id}:0",
        f"ux:ticket:page:{own_ticket.id}:{visible.id}:9",
    ]
    for callback in callbacks:
        reply = await flow.reply(event(platform, callback=callback), db)
        assert not any(secret in reply.text for secret in (
            "SYSTEM-SECRET", "STORE-SECRET", "CUSTOMER-SECRET",
        ))


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("action", [
    "ux:ticket:view:9999999999999999999",
    "ux:ticket:reply:9999999999999999999",
    "ux:ticket:page:9999999999999999999:9999999999999999999:0",
])
async def test_ticket_callbacks_never_overflow_database_ids(db, platform, action):
    """A short forged callback cannot turn into an out-of-range SQL parameter."""
    context, _ = await account(db, platform)
    reply = await CustomerSupportFlow(bot_context=context).reply(
        event(platform, callback=action), db,
    )
    assert reply is None or "معتبر نیست" in reply.text


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("restriction", ["expired", "future", "permanent"])
async def test_support_ticket_access_uses_effective_crm_restriction(
    db, platform, restriction,
):
    """Expired temporary restrictions regain scoped help without removing audit data."""
    context, identity = await account(db, platform)
    ticket = ShopSupportTicket(
        store_id=context.store_id, customer_id=identity.customer_id,
        bot_id=context.bot_id, origin_identity_id=identity.id, topic="payment",
    )
    db.add(ticket)
    await db.flush()
    db.add(ShopSupportMessage(
        ticket_id=ticket.id, store_id=context.store_id,
        sender_kind="customer", identity_id=identity.id, body="OWN-TICKET-CONTENT",
    ))
    identity.is_blocked = True
    db.add(ShopCustomerProfile(
        identity_id=identity.id,
        restriction_until=(
            None if restriction == "permanent" else
            datetime.now(UTC) + timedelta(minutes=-1 if restriction == "expired" else 5)
        ),
    ))
    await db.commit()
    reply = await CustomerSupportFlow(bot_context=context).reply(
        event(platform, callback=f"ux:ticket:view:{ticket.id}"), db,
    )
    assert ("OWN-TICKET-CONTENT" in reply.text) is (restriction == "expired")
    assert identity.is_blocked is True
