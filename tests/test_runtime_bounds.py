"""Real database regression coverage for finite Runtime authority and work budgets."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from models.shop_action import ShopActionExecution
from models.shop_wholesale import ShopWholesaleApplication
from models.shop_workflow_runtime import (
    WorkflowActionJob,
    WorkflowEvent,
    WorkflowInbox,
    WorkflowOutbox,
    WorkflowRun,
)
from services import shop_admin_security as security
from services.shop_runtime.contracts import RuntimeInput
from services.shop_runtime.sessions import handle
from services.shop_runtime.workers import action_once
from services.shop_workflow_schema import Definition
from tests.test_action_security import buyer as buyer  # noqa: PLC0414 - pytest fixture
from tests.test_action_security import db as db  # noqa: PLC0414 - pytest fixture
from tests.test_runtime_interpreter import form
from tests.test_runtime_sessions import inbound, setup_runtime
from tests.test_runtime_workers import factory


async def confirmed_job(connection, principal, monkeypatch):
    """Accept an actual confirmation before a real registered business Action."""
    data = form().model_dump(mode="json")
    data["nodes"].append(
        {
            "id": "apply",
            "type": "action",
            "config": {
                "action_key": "wholesale.create_application",
                "action_version": "1.0.0",
                "input_mapping": {"company": {"kind": "constant", "value": "QA"}},
                "output_mapping": {},
            },
        }
    )
    next(
        edge
        for edge in data["edges"]
        if edge["source"] == "review" and edge["port"] == "confirm"
    )["target"] = "apply"
    data["edges"].append(
        {"id": "success", "source": "apply", "port": "success", "target": "done"}
    )
    await setup_runtime(
        connection, principal, monkeypatch, Definition.model_validate(data)
    )
    for number, text in [(1, "/wholesale"), (2, "Alice"), (3, "12")]:
        await handle(
            connection,
            context=principal.bot,
            event=inbound(number, text, "command" if number == 1 else "text"),
        )
    output = (
        await connection.scalars(
            select(WorkflowOutbox).order_by(WorkflowOutbox.sequence.desc())
        )
    ).first()
    await handle(
        connection,
        context=principal.bot,
        event=RuntimeInput(
            platform="telegram",
            update_id="4",
            user_id=101,
            chat_id=101,
            kind="callback",
            callback=output.payload["buttons"][0]["callback_data"],
        ),
    )
    return await connection.scalar(select(WorkflowRun)), await connection.scalar(
        select(WorkflowActionJob)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("pending,count", [(False, 60), (True, 20)])
async def test_inbound_capacity_has_no_side_effect_and_duplicates_bypass_it(
    buyer, monkeypatch, pending, count
):
    """Only accepted unique input consumes rolling capacity or pending backlog."""
    connection, principal = buyer
    await setup_runtime(connection, principal, monkeypatch)
    await handle(
        connection, context=principal.bot, event=inbound(1, "/wholesale", "command")
    )
    run = await connection.scalar(select(WorkflowRun))
    original = await connection.scalar(select(WorkflowInbox))
    for number in range(count - (0 if pending else 1)):
        connection.add(
            WorkflowInbox(
                store_id=principal.store_id,
                bot_id=principal.bot_id,
                user_id=101,
                input_id=f"seed:{number}",
                sequence=100 + number,
                run_id=run.id,
                payload={},
                status="pending" if pending else "processed",
                created_at=security.clock(),
            )
        )
    await connection.commit()
    before = await connection.scalar(select(func.count()).select_from(WorkflowInbox))
    response = await handle(
        connection, context=principal.bot, event=inbound(2, "Alice")
    )
    assert response == {"handled": True, "status": "rate_limited"}
    assert (
        await connection.scalar(select(func.count()).select_from(WorkflowInbox))
        == before
    )
    assert (await connection.scalar(select(WorkflowRun))).node_id == "name"
    replay = await handle(
        connection, context=principal.bot, event=inbound(1, "/wholesale", "command")
    )
    assert replay["duplicate"]
    connection.session.refresh(original)
    assert original.duplicate_count == 1
    cancel = await handle(
        connection, context=principal.bot, event=inbound(3, "/cancel", "command")
    )
    assert cancel["status"] == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["events", "outbox"])
async def test_persisted_run_budgets_stop_before_another_intent(
    buyer, monkeypatch, resource
):
    """Actual stored rows impose a hard ceiling even for invalid-answer notices."""
    connection, principal = buyer
    await setup_runtime(connection, principal, monkeypatch)
    await handle(
        connection, context=principal.bot, event=inbound(1, "/wholesale", "command")
    )
    run = await connection.scalar(select(WorkflowRun))
    for number in range(999):
        if resource == "events":
            connection.add(
                WorkflowEvent(
                    store_id=run.store_id,
                    run_id=run.id,
                    bot_id=run.bot_id,
                    input_id=f"seed:{number}",
                    kind="text",
                    node_id=run.node_id,
                    status="waiting_input",
                    summary={},
                    correlation_id=run.correlation_id,
                )
            )
        else:
            connection.add(
                WorkflowOutbox(
                    store_id=run.store_id,
                    run_id=run.id,
                    bot_id=run.bot_id,
                    node_id=run.node_id,
                    epoch=1,
                    sequence=number + 2,
                    payload={"kind": "text"},
                )
            )
    await connection.commit()
    await handle(connection, context=principal.bot, event=inbound(2, ""))
    run = await connection.scalar(select(WorkflowRun))
    assert run.status == "failed"
    assert run.error_code == (
        "runtime_event_budget" if resource == "events" else "runtime_outbound_budget"
    )
    table = WorkflowEvent if resource == "events" else WorkflowOutbox
    assert await connection.scalar(select(func.count()).select_from(table)) == 1000
    assert (
        await connection.scalar(select(func.count()).select_from(WorkflowActionJob))
        == 0
    )


@pytest.mark.asyncio
async def test_old_confirmation_cannot_authorize_first_physical_execution(
    buyer, monkeypatch
):
    """A delayed worker cannot remint five-minute consent into fresh authority."""
    connection, principal = buyer
    run, _ = await confirmed_job(connection, principal, monkeypatch)
    now = security.clock()
    monkeypatch.setattr(
        security, "clock", lambda: now + timedelta(minutes=5, seconds=1)
    )
    assert await action_once(factory(connection))
    connection.session.expire_all()
    run = await connection.scalar(select(WorkflowRun))
    assert run.status == "failed" and run.error_code == "runtime_confirmation_expired"
    assert (
        await connection.scalar(
            select(func.count()).select_from(ShopWholesaleApplication)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_committed_action_receipt_recovers_after_confirmation_expires(
    buyer, monkeypatch
):
    """A crash after the domain commit recovers its existing result without reexecution."""
    from services.shop_runtime import workers

    connection, principal = buyer
    await confirmed_job(connection, principal, monkeypatch)
    real_persist = workers.persist

    async def crash(*args):
        """Simulate a coordinator crash after the separate executor commit."""
        raise RuntimeError("synthetic coordinator crash")

    monkeypatch.setattr(workers, "persist", crash)
    with pytest.raises(RuntimeError, match="synthetic coordinator crash"):
        await action_once(factory(connection))
    assert (
        await connection.scalar(
            select(func.count()).select_from(ShopWholesaleApplication)
        )
        == 1
    )
    now = security.clock()
    monkeypatch.setattr(security, "clock", lambda: now + timedelta(minutes=6))
    monkeypatch.setattr(workers, "persist", real_persist)
    await action_once(factory(connection))
    connection.session.expire_all()
    assert (await connection.scalar(select(WorkflowRun))).status == "completed"
    assert (
        await connection.scalar(
            select(func.count()).select_from(ShopWholesaleApplication)
        )
        == 1
    )
    assert (
        await connection.scalar(select(func.count()).select_from(ShopActionExecution))
        == 1
    )


def test_database_engine_hides_private_parameters(monkeypatch):
    """SQL failures must omit private bound values from engine diagnostics."""
    import runpy
    from pathlib import Path

    import config

    monkeypatch.setattr(config, "DB_SQL_ECHO", False, raising=False)
    actual = runpy.run_path(str(Path(__file__).resolve().parents[1] / "db.py"))
    assert actual["engine"].sync_engine.hide_parameters is True


@pytest.mark.asyncio
async def test_retryable_action_keeps_job_invocation_and_bounded_backoff(
    buyer, monkeypatch
):
    """The real executor retries one declared safe operation under its original receipt."""
    from dataclasses import replace

    from services.shop_actions import catalog
    from services.shop_actions.catalog import actions
    from services.shop_actions.contracts import ActionRejected
    from services.shop_actions.registry import Registry
    from services.shop_runtime import workers

    connection, principal = buyer
    original = actions().resolve("wholesale.create_application", "1.0.0")
    calls = []

    async def transient_then_apply(database, actor, inputs):
        """Fail once before mutation, then execute the actual domain adapter."""
        calls.append(1)
        if len(calls) == 1:
            raise ActionRejected("action_busy")
        return await original.adapter(database, actor, inputs)

    registry = Registry()
    registry.register(
        replace(
            original,
            descriptor=original.descriptor.model_copy(
                update={
                    "max_retries": 2,
                    "retryable_codes": ["action_busy"],
                }
            ),
            adapter=transient_then_apply,
        )
    )
    monkeypatch.setattr(catalog, "actions", lambda: registry)
    monkeypatch.setattr(workers, "actions", lambda: registry)
    _run, job = await confirmed_job(connection, principal, monkeypatch)
    identifiers = job.id, job.invocation_id
    await action_once(factory(connection))
    connection.session.expire_all()
    job = await connection.scalar(select(WorkflowActionJob))
    assert job.status == "pending" and job.attempts == 1
    assert (job.id, job.invocation_id) == identifiers
    assert (await connection.scalar(select(WorkflowRun))).status == "waiting_action"
    assert not await action_once(factory(connection))
    now = security.clock()
    monkeypatch.setattr(security, "clock", lambda: now + timedelta(seconds=4))
    assert await action_once(factory(connection))
    connection.session.expire_all()
    job = await connection.scalar(select(WorkflowActionJob))
    assert job.status == "succeeded" and job.attempts == 2
    assert (job.id, job.invocation_id) == identifiers
    assert (
        await connection.scalar(select(func.count()).select_from(WorkflowActionJob))
        == 1
    )
    receipt = await connection.scalar(select(ShopActionExecution))
    assert receipt.retry_count == 1 and receipt.status == "succeeded"
    assert (
        await connection.scalar(
            select(func.count()).select_from(ShopWholesaleApplication)
        )
        == 1
    )
    assert calls == [1, 1]


@pytest.mark.asyncio
async def test_duplicate_replays_original_completed_input_outcome(buyer, monkeypatch):
    """A delivery retry reports the accepted result even after the Run moves on."""
    connection, principal = buyer
    await setup_runtime(connection, principal, monkeypatch)
    event = inbound(1, "/wholesale", "command")
    original = await handle(connection, context=principal.bot, event=event)
    await handle(connection, context=principal.bot, event=inbound(2, "Alice"))
    replay = await handle(connection, context=principal.bot, event=event)
    assert replay == original | {"duplicate": True}


@pytest.mark.asyncio
async def test_timeout_records_safe_correlated_system_event(buyer, monkeypatch):
    """Elapsed waits remain observable without storing the customer input."""
    from models.shop_workflow_runtime import WorkflowWait
    from services.shop_runtime.workers import timeout_once

    connection, principal = buyer
    await setup_runtime(connection, principal, monkeypatch)
    await handle(
        connection, context=principal.bot, event=inbound(1, "/wholesale", "command")
    )
    wait = await connection.scalar(select(WorkflowWait))
    wait.deadline = security.clock() - timedelta(seconds=1)
    await connection.commit()
    await timeout_once(factory(connection))
    connection.session.expire_all()
    event = await connection.scalar(
        select(WorkflowEvent).where(WorkflowEvent.kind == "timeout")
    )
    assert event is not None
    run = await connection.scalar(select(WorkflowRun))
    assert event.correlation_id == run.correlation_id
    assert event.error_code == "runtime_input_timeout" and event.summary == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["events", "outbox"])
async def test_pending_physical_action_respects_exhausted_run_budget(
    buyer, monkeypatch, resource
):
    """A queued business effect cannot execute after its Run exhausts stored work."""
    connection, principal = buyer
    run, _ = await confirmed_job(connection, principal, monkeypatch)
    model = WorkflowEvent if resource == "events" else WorkflowOutbox
    count = await connection.scalar(select(func.count()).select_from(model))
    for number in range(count, 1000):
        if resource == "events":
            connection.add(
                WorkflowEvent(
                    store_id=run.store_id,
                    run_id=run.id,
                    bot_id=run.bot_id,
                    input_id=f"action-seed:{number}",
                    kind="text",
                    node_id=run.node_id,
                    status="waiting_action",
                    summary={},
                    correlation_id=run.correlation_id,
                )
            )
        else:
            connection.add(
                WorkflowOutbox(
                    store_id=run.store_id,
                    run_id=run.id,
                    bot_id=run.bot_id,
                    node_id=run.node_id,
                    epoch=1,
                    sequence=number + 1,
                    payload={},
                )
            )
    await connection.commit()
    assert await action_once(factory(connection))
    connection.session.expire_all()
    assert (
        await connection.scalar(
            select(func.count()).select_from(ShopWholesaleApplication)
        )
        == 0
    )
    run = await connection.scalar(select(WorkflowRun))
    assert run.status == "failed"
    assert run.error_code == (
        "runtime_event_budget" if resource == "events" else "runtime_outbound_budget"
    )
