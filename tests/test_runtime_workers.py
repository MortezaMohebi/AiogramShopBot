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


@pytest.mark.asyncio
async def test_outbox_candidate_is_refreshed_after_another_worker_finishes(
    buyer, monkeypatch
):
    """A delayed candidate cannot duplicate an attempt or resend a sent message."""
    import asyncio

    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    selected, released = asyncio.Event(), asyncio.Event()
    base = factory(db)

    @asynccontextmanager
    async def delayed():
        async with base() as session:
            original = session.scalar

            async def scalar(statement):
                row = await original(statement)
                if isinstance(row, WorkflowOutbox) and not selected.is_set():
                    selected.set()
                    await released.wait()
                return row

            session.scalar = scalar
            yield session

    calls = []

    async def provider(_, __, payload):
        calls.append(payload["text"])
        return ["404"]

    waiting = asyncio.create_task(deliver_once(delayed, send=provider))
    await asyncio.wait_for(selected.wait(), 3)
    await deliver_once(base, send=provider)
    released.set()
    assert await asyncio.wait_for(waiting, 3) is False
    assert calls == ["Name?"]


async def second_customer_run(db, principal, *, other_bot=False):
    """Queue a real authenticated second customer on the shared delivery scheduler."""
    from dataclasses import replace
    from uuid import uuid4

    from models.shop_content import ShopIdentity
    from models.shop_multibot import ShopBot
    from models.shop_store_commerce import ShopStoreCustomer
    from models.shop_workflow_runtime import RuntimeBinding, RuntimeGate
    from services.shop_runtime.sessions import gate_key

    context = principal.bot
    if other_bot:
        bot_id = str(uuid4())
        db.add(
            ShopBot(
                id=bot_id,
                store_id=principal.store_id,
                slug="other-runtime",
                name="Other runtime",
                platform="telegram",
                status="active",
                runtime_owner="registry",
                credential_version=1,
            )
        )
        await db.flush()
        binding = await db.scalar(select(RuntimeBinding))
        db.add(
            RuntimeBinding(
                store_id=principal.store_id,
                bot_id=bot_id,
                publication_id=binding.publication_id,
                workflow_id=binding.workflow_id,
                kind="command",
                key="wholesale",
                node_id=binding.node_id,
            )
        )
        db.add(
            RuntimeGate(
                store_id=principal.store_id,
                bot_id=bot_id,
                scope_key=gate_key(principal.store_id, bot_id),
                enabled=True,
            )
        )
        context = replace(
            context, bot_id=bot_id, status="active", runtime_owner="registry"
        )
    customer = ShopStoreCustomer(
        store_id=principal.store_id, display_name="Second QA buyer"
    )
    db.add(customer)
    await db.flush()
    db.add(
        ShopIdentity(
            store_id=principal.store_id,
            customer_id=customer.id,
            bot_id=context.bot_id,
            platform="telegram",
            platform_user_id=202,
        )
    )
    await db.commit()
    await handle(
        db,
        context=context,
        event=inbound(2, "/wholesale", "command").model_copy(
            update={"user_id": 202, "chat_id": 202}
        ),
    )
    return context


@pytest.mark.asyncio
async def test_customer_block_after_durable_claim_prevents_provider_call(
    buyer, monkeypatch
):
    """Stop a revoked principal between the claim and send transactions."""
    from models.shop_content import ShopIdentity
    from models.shop_workflow_runtime import WorkflowRun

    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    base = factory(db)
    opened = 0

    @asynccontextmanager
    async def revoke_after_claim():
        nonlocal opened
        opened += 1
        if opened == 2:
            async with base() as admin:
                identity = await admin.get(ShopIdentity, p.identity_id)
                identity.is_blocked = True
                await admin.commit()
        async with base() as session:
            yield session

    calls = []

    async def provider(*args):
        calls.append(1)
        return ["71"]

    assert await deliver_once(revoke_after_claim, send=provider)
    db.session.expire_all()
    assert calls == []
    outbox = await db.scalar(select(WorkflowOutbox))
    attempt = await db.scalar(select(WorkflowDeliveryAttempt))
    run = await db.scalar(select(WorkflowRun))
    assert outbox.status == "cancelled" and outbox.attempts == 1
    assert attempt.outcome == "cancelled"
    assert outbox.error_code == attempt.error_code == "runtime_actor_unavailable"
    assert run.status == "suspended" and run.error_code == outbox.error_code


@pytest.mark.asyncio
async def test_blocked_customer_does_not_starve_other_customers(buyer, monkeypatch):
    """Cancel unavailable actors explicitly and let the scheduler progress."""
    from models.shop_content import ShopIdentity
    from models.shop_workflow_runtime import WorkflowRun

    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    await second_customer_run(db, p)
    identity = await db.get(ShopIdentity, p.identity_id)
    identity.is_blocked = True
    await db.commit()
    calls = []

    async def provider(context, chat_id, payload):
        calls.append(chat_id)
        return ["72"]

    assert await deliver_once(factory(db), send=provider)
    assert await deliver_once(factory(db), send=provider)
    assert calls == [202]
    db.session.expire_all()
    assert set((await db.scalars(select(WorkflowOutbox.status))).all()) == {
        "sent",
        "cancelled",
    }
    rejected = await db.scalar(
        select(WorkflowOutbox)
        .join(WorkflowRun, WorkflowRun.id == WorkflowOutbox.run_id)
        .where(WorkflowRun.user_id == 101)
    )
    assert rejected.error_code == "runtime_actor_unavailable"
    assert rejected.attempts == 0
    assert (
        await db.scalar(
            select(WorkflowDeliveryAttempt).where(
                WorkflowDeliveryAttempt.outbox_id == rejected.id
            )
        )
        is None
    )
    run = await db.get(WorkflowRun, rejected.run_id)
    assert run.status == "suspended" and run.error_code == rejected.error_code


@pytest.mark.asyncio
async def test_operationally_paused_bot_does_not_starve_active_bot(buyer, monkeypatch):
    """A Bot's operations pause preserves its own queue while another Bot progresses."""
    from models.shop_bot_operations import ShopBotOperations

    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    other = await second_customer_run(db, p, other_bot=True)
    db.add(ShopBotOperations(bot_id=p.bot_id, desired_state="paused"))
    await db.commit()
    calls = []

    async def provider(context, chat_id, payload):
        calls.append(context.bot_id)
        return ["73"]

    assert await deliver_once(factory(db), send=provider)
    assert calls == [other.bot_id]
    db.session.expire_all()
    pending = await db.scalar(
        select(WorkflowOutbox).where(WorkflowOutbox.bot_id == p.bot_id)
    )
    assert pending.status == "pending" and pending.attempts == 0


@pytest.mark.asyncio
async def test_action_candidate_refresh_preserves_competing_completed_job(
    buyer, monkeypatch
):
    """A delayed candidate cannot cancel a job another worker has completed."""
    import asyncio

    from models.shop_workflow_runtime import WorkflowActionJob, WorkflowRun
    from services.shop_runtime.workers import action_once

    db, principal = buyer
    await setup_runtime(db, principal, monkeypatch)
    await handle(db, context=principal.bot, event=inbound(1, "/wholesale", "command"))
    run = await db.scalar(select(WorkflowRun))
    run.status = "waiting_action"
    job = WorkflowActionJob(
        store_id=principal.store_id,
        run_id=run.id,
        node_id=run.node_id,
        epoch=run.state["epoch"],
        action_key="wholesale.create_application",
        action_version="1.0.0",
        input={},
    )
    db.add(job)
    await db.commit()
    selected, released = asyncio.Event(), asyncio.Event()
    base = factory(db)

    @asynccontextmanager
    async def delayed():
        async with base() as session:
            original = session.scalar

            async def scalar(statement):
                row = await original(statement)
                if isinstance(row, WorkflowActionJob) and not selected.is_set():
                    selected.set()
                    await released.wait()
                return row

            session.scalar = scalar
            yield session

    waiting = asyncio.create_task(action_once(delayed))
    await asyncio.wait_for(selected.wait(), 3)
    async with base() as competitor:
        completed_job = await competitor.get(WorkflowActionJob, job.id)
        completed_run = await competitor.get(WorkflowRun, run.id)
        completed_job.status = "succeeded"
        completed_job.receipt_id = "completed-receipt"
        completed_run.status = "completed"
        await competitor.commit()
    released.set()
    assert await asyncio.wait_for(waiting, 3) is False
    db.session.expire_all()
    refreshed = await db.get(WorkflowActionJob, job.id)
    assert refreshed.status == "succeeded"
    assert refreshed.receipt_id == "completed-receipt"


@pytest.mark.asyncio
@pytest.mark.parametrize("older_status", ["cancelled", "suspended"])
async def test_older_ineligible_wait_does_not_starve_live_timeout(
    buyer, monkeypatch, older_status
):
    """An older stopped Run cannot hide another customer's eligible due wait."""
    from datetime import timedelta

    from models.shop_workflow_runtime import WorkflowEvent, WorkflowRun, WorkflowWait
    from services import shop_admin_security as security
    from services.shop_runtime.workers import timeout_once

    database, principal = buyer
    await setup_runtime(database, principal, monkeypatch)
    await handle(
        database,
        context=principal.bot,
        event=inbound(1, "/wholesale", "command"),
    )
    older = await database.scalar(select(WorkflowRun))
    older.status = older_status
    older_wait = await database.scalar(select(WorkflowWait))
    older_wait.deadline = security.clock() - timedelta(minutes=2)
    older_wait_id = older_wait.id
    preserved = older.node_id, dict(older.state), older_wait.epoch
    await database.commit()

    # Starting again follows the real coordinator path and pins a separate Run;
    # the old Wait intentionally remains available if its Run is resumed.
    await handle(
        database,
        context=principal.bot,
        event=inbound(2, "/wholesale", "command"),
    )
    live = await database.scalar(select(WorkflowRun).where(WorkflowRun.id != older.id))
    live_wait = await database.scalar(
        select(WorkflowWait).where(WorkflowWait.run_id == live.id)
    )
    live_wait.deadline = security.clock() - timedelta(minutes=1)
    older_id, live_id = older.id, live.id
    await database.commit()

    assert await timeout_once(factory(database)) is True
    database.session.expire_all()
    live = await database.get(WorkflowRun, live_id)
    assert live.status == "cancelled" and live.error_code == "runtime_input_timeout"
    older = await database.get(WorkflowRun, older_id)
    older_wait = await database.get(WorkflowWait, older_wait_id)
    assert older.status == older_status
    assert older_wait is not None
    assert (older.node_id, older.state, older_wait.epoch) == preserved
    assert (
        await database.scalar(
            select(WorkflowWait).where(WorkflowWait.run_id == live_id)
        )
        is None
    )
    event = await database.scalar(
        select(WorkflowEvent).where(WorkflowEvent.kind == "timeout")
    )
    assert event.run_id == live_id and event.correlation_id == live.correlation_id
    assert await timeout_once(factory(database)) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("retirement", ["kind", "fallback"])
@pytest.mark.parametrize("work", ["delivery", "action"])
async def test_workers_cannot_consume_runs_with_retired_persisted_bindings(
    buyer, monkeypatch, retirement, work,
):
    """Queued prompts and actions retain no authority through an unclean old binding."""
    from unittest.mock import AsyncMock
    from models.shop_workflow_runtime import RuntimeBinding, WorkflowActionJob, WorkflowRun
    from services.shop_runtime import workers

    db, principal = buyer
    await setup_runtime(db, principal, monkeypatch)
    await handle(db, context=principal.bot, event=inbound(1, "/wholesale", "command"))
    run = await db.scalar(select(WorkflowRun))
    binding = await db.scalar(select(RuntimeBinding))
    if work == "action":
        run.status = "waiting_action"
        db.add(WorkflowActionJob(
            store_id=principal.store_id, run_id=run.id, node_id=run.node_id,
            epoch=run.state["epoch"], action_key="cart.get", action_version="1.0.0",
            input={},
        ))
    if retirement == "kind":
        binding.kind = "legacy_bridge"
    else:
        binding.fallback = "legacy"
    await db.commit()
    provider = AsyncMock(side_effect=AssertionError("Retired binding sent a prompt"))
    invoke = AsyncMock(side_effect=AssertionError("Retired binding executed an action"))
    monkeypatch.setattr(workers, "invoke", invoke)
    if work == "action":
        assert not await workers.action_once(factory(db))
    else:
        assert not await workers.deliver_once(factory(db), send=provider)
    provider.assert_not_awaited()
    invoke.assert_not_awaited()
    db.session.expire_all()
    assert (await db.scalar(select(WorkflowOutbox))).status == "pending"
    if work == "action":
        assert (await db.scalar(select(WorkflowActionJob))).status == "pending"
