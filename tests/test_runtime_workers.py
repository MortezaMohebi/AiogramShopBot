"""Delivery boundaries distinguish confirmed receipts from unknown outcomes."""

from contextlib import asynccontextmanager
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.test_shared_cart import AsyncDatabase
from tests.test_action_security import buyer, db
from tests.test_runtime_sessions import setup_runtime, inbound
from services.shop_runtime.sessions import handle
from services.shop_runtime.workers import deliver_once
from services.shop_runtime.contracts import DeliveryRejected
from models.shop_workflow_runtime import WorkflowOutbox, WorkflowDeliveryAttempt


def factory(db):
    """Use fresh actual ORM sessions; PostgreSQL acceptance proves competing locks."""

    @asynccontextmanager
    async def create():
        with Session(db.session.get_bind(), expire_on_commit=False) as connection:
            yield AsyncDatabase(connection)

    return create


@pytest.mark.asyncio
async def test_confirmed_provider_message_has_durable_receipt(buyer, monkeypatch):
    """A delivery is sent only after its provider returns a real positive message ID."""
    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    calls = []

    async def provider(context, chat_id, payload):
        calls.append((context.bot_id, chat_id, payload["text"]))
        return ["71"]

    await deliver_once(factory(db), send=provider)
    await deliver_once(factory(db), send=provider)
    db.session.expire_all()
    row = await db.scalar(select(WorkflowOutbox))
    assert row.status == "sent" and row.message_ids == ["71"]
    assert calls == [(p.bot_id, 101, "Name?")]


@pytest.mark.asyncio
async def test_timeout_is_uncertain_and_never_automatically_resent(buyer, monkeypatch):
    """An accepted-but-timed-out send cannot become an automatic duplicate message."""
    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    calls = []

    async def provider(*args):
        calls.append(1)
        raise TimeoutError("private token-bearing transport detail")

    await deliver_once(factory(db), send=provider)
    await deliver_once(factory(db), send=provider)
    db.session.expire_all()
    row = await db.scalar(select(WorkflowOutbox))
    assert row.status == "dead_letter" and row.error_code == "runtime_delivery_unknown"
    assert calls == [1]
    attempt = await db.scalar(select(WorkflowDeliveryAttempt))
    assert attempt.outcome == "uncertain" and "private" not in str(attempt.error_code)


@pytest.mark.asyncio
async def test_cancelled_question_is_not_sent_late(buyer, monkeypatch):
    """A queued prompt cannot appear after the customer has cancelled its Run."""
    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    await handle(db, context=p.bot, event=inbound(2, "/cancel", "command"))
    calls = []

    async def provider(*args):
        calls.append(1)
        return ["71"]

    await deliver_once(factory(db), send=provider)
    db.session.expire_all()
    assert (
        calls == [] and (await db.scalar(select(WorkflowOutbox))).status == "cancelled"
    )


@pytest.mark.asyncio
async def test_dead_letter_in_one_run_does_not_starve_other_customers(
    buyer, monkeypatch
):
    """An unresolved send blocks only its own Run's sequence, not the shared worker."""
    from models.shop_workflow_runtime import WorkflowRun
    from uuid import uuid4

    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    original = await db.scalar(select(WorkflowRun))
    first = await db.scalar(select(WorkflowOutbox))
    first.status = "dead_letter"
    first.error_code = "runtime_delivery_unknown"
    db.add(
        WorkflowOutbox(
            store_id=p.store_id,
            bot_id=p.bot_id,
            run_id=original.id,
            node_id="name",
            epoch=1,
            sequence=2,
            payload={"kind": "text", "text": "blocked", "buttons": []},
            available_at=first.available_at,
        )
    )
    other = WorkflowRun(
        id=str(uuid4()),
        store_id=p.store_id,
        bot_id=p.bot_id,
        customer_id=p.customer_id,
        identity_id=p.identity_id,
        user_id=101,
        chat_id=101,
        platform="telegram",
        workflow_id=original.workflow_id,
        publication_id=original.publication_id,
        binding_id=original.binding_id,
        node_id="name",
        status="waiting_input",
        values={},
        state={"epoch": 1},
        expires_at=original.expires_at,
    )
    db.add(other)
    await db.flush()
    db.add(
        WorkflowOutbox(
            store_id=p.store_id,
            bot_id=p.bot_id,
            run_id=other.id,
            node_id="name",
            epoch=1,
            sequence=1,
            payload={"kind": "text", "text": "other customer", "buttons": []},
            available_at=first.available_at,
        )
    )
    await db.commit()
    calls = []

    async def provider(_, __, payload):
        calls.append(payload["text"])
        return ["88"]

    await deliver_once(factory(db), send=provider)
    assert calls == ["other customer"]


@pytest.mark.asyncio
async def test_expiry_covers_waiting_approval_without_a_wait_row(buyer, monkeypatch):
    """An abandoned approval cannot remain active forever because no input timer exists."""
    from services.shop_runtime.workers import expire_once
    from models.shop_workflow_runtime import WorkflowRun, WorkflowWait
    from services import shop_admin_security as security
    from datetime import timedelta

    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    run = await db.scalar(select(WorkflowRun))
    run.status = "waiting_approval"
    run.expires_at = security.clock() - timedelta(seconds=1)
    await db.delete(await db.scalar(select(WorkflowWait)))
    await db.commit()
    assert await expire_once(factory(db))
    db.session.expire_all()
    run = await db.scalar(select(WorkflowRun))
    assert run.status == "expired" and run.error_code == "runtime_run_expired"
