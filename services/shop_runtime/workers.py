"""Recoverable workers for Action jobs, sequenced delivery, timeouts and inboxes."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, or_, and_, literal
from sqlalchemy.orm import aliased

import config
from models.shop_multibot import ShopBot, ShopStore
from models.shop_workflow_runtime import RuntimeGate

from models.shop_workflow_runtime import (
    WorkflowRun,
    WorkflowActionJob,
    PublishedWorkflow,
    WorkflowOutbox,
    WorkflowDeliveryAttempt,
    WorkflowWait,
    WorkflowInbox,
    WorkflowEvent,
)
from services import shop_admin_security as security
from services.shop_actions.context import customer_principal
from services.shop_actions.contracts import Invocation, ActionRejected
from services.shop_actions.execution import invoke
from services.shop_actions.approvals import issue_authorization
from services.shop_actions.catalog import actions
from services.shop_action_bindings import write_outputs
from services.shop_bot_context import resolve_bot_context
from channels.contracts import Platform
from services.shop_runtime.contracts import DeliveryRejected, TERMINAL, RuntimeInput
from services.shop_runtime.publication import digest
from services.shop_runtime.sessions import (
    enabled,
    machine_for,
    persist,
    handle,
    gate_key,
)


def eligible_bots():
    """Exclude paused tenants before scheduling so one Bot cannot starve others."""
    store_gate, bot_gate = aliased(RuntimeGate), aliased(RuntimeGate)
    query = (
        select(ShopBot.id)
        .join(ShopStore, ShopStore.id == ShopBot.store_id)
        .where(
            ShopBot.status.in_(("active", "legacy")),
            ShopStore.state == "active",
            select(store_gate.id)
            .where(
                store_gate.scope_key == literal("store:") + ShopBot.store_id,
                store_gate.store_id == ShopBot.store_id,
                store_gate.enabled.is_(True),
                store_gate.killed.is_(False),
            )
            .exists(),
            select(bot_gate.id)
            .where(
                bot_gate.scope_key == literal("bot:") + ShopBot.id,
                bot_gate.store_id == ShopBot.store_id,
                bot_gate.enabled.is_(True),
                bot_gate.killed.is_(False),
            )
            .exists(),
        )
    )
    if (
        not config.SHOP_WORKFLOW_RUNTIME_ENABLED
        or config.SHOP_WORKFLOW_RUNTIME_KILL_SWITCH
    ):
        query = query.where(False)
    return query


def eligible_runs():
    """Project scheduling gates without using customer data as metric dimensions."""
    return select(WorkflowRun.id).where(WorkflowRun.bot_id.in_(eligible_bots()))


async def context_for(db, run):
    """Re-resolve a currently authenticated Bot identity without provider secrets."""
    return await resolve_bot_context(
        db,
        authenticated_bot_id=run.bot_id,
        authenticated_platform=Platform(run.platform),
    )


async def _lock_gates(db, context):
    """A kill switch waits for an already starting effect; new work stops immediately."""
    from models.shop_workflow_runtime import RuntimeGate

    await db.execute(
        select(RuntimeGate.id)
        .where(
            RuntimeGate.scope_key.in_(
                (gate_key(context.store_id), gate_key(context.store_id, context.bot_id))
            )
        )
        .order_by(RuntimeGate.scope_key)
        .with_for_update(read=True)
    )
    return await enabled(db, context)


async def action_once(session_factory):
    """Invoke one stable Action and reconcile its separate receipt while holding Run lock."""
    async with session_factory() as db:
        candidate = await db.scalar(
            select(WorkflowActionJob)
            .where(
                WorkflowActionJob.run_id.in_(
                    eligible_runs().where(
                        WorkflowRun.status.in_(("waiting_action", "waiting_approval"))
                    )
                ),
                or_(
                    WorkflowActionJob.status == "pending",
                    and_(
                        WorkflowActionJob.status == "waiting_approval",
                        WorkflowActionJob.approval_id.is_not(None),
                    ),
                ),
            )
            .order_by(WorkflowActionJob.created_at, WorkflowActionJob.id)
            .limit(1)
        )
        if candidate is None:
            return False
        run = await db.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.id == candidate.run_id)
            .with_for_update(skip_locked=True)
        )
        if run is None:
            return False
        job = await db.scalar(
            select(WorkflowActionJob)
            .where(WorkflowActionJob.id == candidate.id)
            .with_for_update()
        )
        if job.status not in {"pending", "waiting_approval"}:
            return False
        if security.utc(run.expires_at) <= security.clock():
            run.status = "expired"
            job.status = "cancelled"
            await db.commit()
            return True
        if (
            run.status not in {"waiting_action", "waiting_approval"}
            or run.node_id != job.node_id
            or run.state.get("epoch") != job.epoch
        ):
            job.status = "cancelled"
            await db.commit()
            return True
        try:
            context = await context_for(db, run)
            if not await _lock_gates(db, context):
                return False
            await customer_principal(
                db, verified_bot=context, platform_user_id=run.user_id
            )
        except (security.SecurityRejected, ActionRejected):
            run.status = "suspended"
            run.error_code = "runtime_actor_unavailable"
            await db.commit()
            return True
        published = await db.get(PublishedWorkflow, run.publication_id)
        machine = await machine_for(db, run)
        spec = actions().resolve(job.action_key, job.action_version)
        policy = spec.descriptor.confirmation
        if policy in {"operator_approval", "both"} and not job.approval_id:
            run.status = "waiting_approval"
            job.status = "waiting_approval"
            await db.commit()
            return True
        invocation = Invocation(
            invocation_id=job.invocation_id,
            action_key=job.action_key,
            action_version=job.action_version,
            input=job.input,
            idempotency_key="runtime-" + job.id,
            workflow_id=run.workflow_id,
            workflow_revision=published.revision,
            workflow_run_id=run.id,
            node_id=job.node_id,
            correlation_id=run.correlation_id,
            request_id=job.id,
        )
        try:
            # This session owns proof and executor commits. Never give it the Run-lock session.
            async with session_factory() as execution_db:
                execution_principal = await customer_principal(
                    execution_db, verified_bot=context, platform_user_id=run.user_id
                )
                if policy in {"customer_confirmation", "both"}:
                    if machine.state.get("confirmed_values") != digest(machine.values):
                        raise ActionRejected("runtime_confirmation_missing")
                    proof = await issue_authorization(
                        execution_db,
                        subject=execution_principal,
                        approver=execution_principal,
                        invocation=invocation,
                        purpose="customer_confirmation",
                        registry=actions(),
                    )
                    invocation = invocation.model_copy(
                        update={"confirmation_receipt": proof}
                    )
                if job.approval_id:
                    proof = security.cipher().decrypt(job.approval_id.encode()).decode()
                    invocation = invocation.model_copy(
                        update={"approval_receipt": proof}
                    )
                result = await invoke(execution_db, execution_principal, invocation)
        except ActionRejected as error:
            run.status = "failed"
            run.error_code = error.code
            job.status = "failed"
            job.error_code = error.code
            await db.commit()
            return True
        job.attempts += 1
        job.receipt_id = result.execution_receipt
        config = machine.config(machine.nodes[job.node_id])
        if result.status == "succeeded":
            try:
                write_outputs(
                    config, result.output or {}, machine.values, machine.declarations
                )
                if spec.descriptor.side_effect not in {"none", "read_only"}:
                    machine.state["past"] = []
                machine.state.pop("confirmed_values", None)
                machine.move("success")
                machine.status = "active"
                machine.advance()
                job.status = "succeeded"
                job.approval_id = None
            except ActionRejected as error:
                job.status = "succeeded"
                machine.fail(error.code)
        elif result.status == "pending_approval":
            run.status = "waiting_approval"
            job.status = "waiting_approval"
            await db.commit()
            return True
        elif result.status == "pending_external":
            # Unknown external outcomes are quarantined under the same invocation ID.
            run.status = "suspended"
            run.error_code = "runtime_action_outcome_unknown"
            job.status = "uncertain"
            job.error_code = run.error_code
            await db.commit()
            return True
        else:
            job.status = "failed"
            job.error_code = (
                result.error.code if result.error else "runtime_action_failed"
            )
            try:
                machine.move("retry" if result.status == "retryable" else "error")
                machine.status = "active"
                machine.advance()
            except ValueError:
                machine.fail(job.error_code)
        await persist(db, run, machine)
        await db.commit()
        return True


def stale(run, outbox):
    """Discard obsolete interaction prompts while retaining ordered informational output."""
    if outbox.payload.get("notice"):
        return False
    return run.status in {"cancelled", "failed", "expired", "suspended"} or (
        outbox.payload.get("interactive")
        and (
            run.status in TERMINAL
            or outbox.epoch != run.state.get("epoch", 0)
            or outbox.node_id != run.node_id
        )
    )


async def deliver_once(session_factory, *, send=None):
    """Claim one ordered intent before sending; ambiguous outcomes never auto-retry."""
    if send is None:
        from services.shop_runtime.adapters import deliver

        send = deliver
    async with session_factory() as db:
        preceding = aliased(WorkflowOutbox)
        candidate = await db.scalar(
            select(WorkflowOutbox)
            .where(
                WorkflowOutbox.status.in_(("pending", "retryable")),
                WorkflowOutbox.run_id.in_(eligible_runs()),
                WorkflowOutbox.available_at <= security.clock(),
                ~select(preceding.id)
                .where(
                    preceding.run_id == WorkflowOutbox.run_id,
                    preceding.sequence < WorkflowOutbox.sequence,
                    preceding.status.not_in(("sent", "cancelled")),
                )
                .exists(),
            )
            .order_by(WorkflowOutbox.created_at, WorkflowOutbox.sequence)
            .limit(1)
        )
        if candidate is None:
            return False
        run = await db.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.id == candidate.run_id)
            .with_for_update(skip_locked=True)
        )
        if run is None:
            return False
        row = await db.scalar(
            select(WorkflowOutbox)
            .where(WorkflowOutbox.id == candidate.id)
            .with_for_update()
        )
        if row.status not in {"pending", "retryable"}:
            return False
        earlier = await db.scalar(
            select(WorkflowOutbox.id).where(
                WorkflowOutbox.run_id == run.id,
                WorkflowOutbox.sequence < row.sequence,
                WorkflowOutbox.status.not_in(("sent", "cancelled")),
            )
        )
        if earlier:
            return False
        if stale(run, row):
            row.status = "cancelled"
            row.error_code = "runtime_prompt_obsolete"
            await db.commit()
            return True
        try:
            context = await context_for(db, run)
            if not await _lock_gates(db, context):
                return False
            await customer_principal(
                db, verified_bot=context, platform_user_id=run.user_id
            )
        except (security.SecurityRejected, ActionRejected):
            return False
        row.status = "sending"
        row.claimed_at = security.clock()
        row.attempts += 1
        attempt = WorkflowDeliveryAttempt(
            id=str(uuid4()),
            store_id=row.store_id,
            outbox_id=row.id,
            number=row.attempts,
            outcome="sending",
        )
        db.add(attempt)
        outbox_id, run_id, attempt_id = row.id, run.id, attempt.id
        await db.commit()
    # The durable sending state prevents another worker from making this call.
    async with session_factory() as db:
        run = await db.scalar(
            select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
        )
        row = await db.scalar(
            select(WorkflowOutbox)
            .where(WorkflowOutbox.id == outbox_id)
            .with_for_update()
        )
        attempt = await db.get(WorkflowDeliveryAttempt, attempt_id)
        if row.status != "sending":
            return False
        try:
            context = await context_for(db, run)
            if stale(run, row) or not await _lock_gates(db, context):
                row.status = "cancelled"
                row.error_code = "runtime_delivery_stopped"
                attempt.outcome = "cancelled"
                await db.commit()
                return True
            ids = await send(context, run.chat_id, row.payload)
            if (
                not isinstance(ids, list)
                or not ids
                or any(
                    not isinstance(x, str) or not x.isdigit() or int(x) <= 0
                    for x in ids
                )
            ):
                raise ValueError("runtime_delivery_receipt_invalid")
            row.status = "sent"
            row.message_ids = ids
            attempt.outcome = "sent"
            attempt.message_ids = ids
        except DeliveryRejected as error:
            row.error_code = error.code
            attempt.error_code = error.code
            row.status = (
                "retryable" if error.retryable and row.attempts < 3 else "dead_letter"
            )
            row.available_at = security.clock() + timedelta(
                seconds=min(300, 2**row.attempts)
            )
            attempt.outcome = "rejected"
        except Exception:
            row.status = "dead_letter"
            row.error_code = "runtime_delivery_unknown"
            attempt.outcome = "uncertain"
            attempt.error_code = row.error_code
        await db.commit()
        return True


async def recover_sending(session_factory):
    """Quarantine crashed provider attempts; absence of an ACK never proves no send."""
    async with session_factory() as db:
        rows = (
            await db.scalars(
                select(WorkflowOutbox)
                .where(
                    WorkflowOutbox.status == "sending",
                    WorkflowOutbox.claimed_at < security.clock() - timedelta(minutes=5),
                )
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        ).all()
        for row in rows:
            row.status = "dead_letter"
            row.error_code = "runtime_delivery_unknown"
            attempt = await db.scalar(
                select(WorkflowDeliveryAttempt).where(
                    WorkflowDeliveryAttempt.outbox_id == row.id,
                    WorkflowDeliveryAttempt.number == row.attempts,
                )
            )
            if attempt:
                attempt.outcome = "uncertain"
                attempt.error_code = row.error_code
        await db.commit()
        return len(rows)


async def timeout_once(session_factory):
    """Serialize elapsed waits against customer input, worker actions and cancellation."""
    async with session_factory() as db:
        wait = await db.scalar(
            select(WorkflowWait)
            .where(
                WorkflowWait.deadline <= security.clock(),
                WorkflowWait.run_id.in_(eligible_runs()),
                ~select(WorkflowInbox.id)
                .where(
                    WorkflowInbox.run_id == WorkflowWait.run_id,
                    WorkflowInbox.epoch == WorkflowWait.epoch,
                    WorkflowInbox.status == "pending",
                    WorkflowInbox.created_at < WorkflowWait.deadline,
                )
                .exists(),
            )
            .order_by(WorkflowWait.deadline)
            .limit(1)
        )
        if wait is None:
            return False
        run = await db.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.id == wait.run_id)
            .with_for_update(skip_locked=True)
        )
        if run is None or run.status not in {"waiting_input", "waiting_timeout"}:
            return False
        wait = await db.scalar(
            select(WorkflowWait)
            .where(WorkflowWait.run_id == run.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            wait is None
            or wait.epoch != run.state.get("epoch")
            or security.utc(wait.deadline) > security.clock()
        ):
            return False
        try:
            context = await context_for(db, run)
            if not await _lock_gates(db, context):
                return False
        except security.SecurityRejected:
            return False
        machine = await machine_for(db, run)
        if machine.status == "waiting_timeout":
            machine.move()
            machine.status = "active"
            machine.advance()
        elif wait.timeout_node:
            machine.move(direct=wait.timeout_node)
            machine.status = "active"
            machine.advance()
        else:
            machine.status = "expired"
            machine.error = "runtime_input_timeout"
        await persist(db, run, machine)
        await db.commit()
        return True


async def inbox_once(session_factory):
    """Resume one accepted input after process restart; keep private payload only while pending."""
    async with session_factory() as db:
        inbox = await db.scalar(
            select(WorkflowInbox)
            .outerjoin(WorkflowRun, WorkflowRun.id == WorkflowInbox.run_id)
            .where(
                WorkflowInbox.status == "pending",
                WorkflowInbox.bot_id.in_(eligible_bots()),
                or_(
                    WorkflowInbox.run_id.is_(None),
                    WorkflowRun.status.not_in(
                        ("waiting_action", "waiting_approval", "waiting_timeout")
                    ),
                    and_(
                        WorkflowInbox.payload["kind"].as_string() == "command",
                        WorkflowInbox.payload["text"]
                        .as_string()
                        .in_(("/cancel", "/menu", "/restart")),
                    ),
                ),
            )
            .order_by(WorkflowInbox.created_at, WorkflowInbox.sequence)
            .limit(1)
        )
        if inbox is None:
            return False
        event = RuntimeInput.model_validate(inbox.payload)
        try:
            context = await resolve_bot_context(
                db,
                authenticated_bot_id=inbox.bot_id,
                authenticated_platform=Platform(event.platform),
            )
            if not await enabled(db, context):
                return False
            result = await handle(db, context=context, event=event)
            return result.get("status") != "queued"
        except (security.SecurityRejected, ActionRejected):
            # Revoked identities remain inspectable, but cannot hold worker scheduling forever.
            inbox.status = "rejected"
            inbox.payload = {}
            inbox.error_code = "runtime_actor_unavailable"
            await db.commit()
            return True


async def expire_once(session_factory):
    """Expire every nonterminal Run, including approval/action waits without input timers."""
    async with session_factory() as db:
        run = await db.scalar(
            select(WorkflowRun)
            .where(
                WorkflowRun.id.in_(eligible_runs()),
                WorkflowRun.status.not_in(tuple(TERMINAL)),
                WorkflowRun.expires_at <= security.clock(),
            )
            .order_by(WorkflowRun.expires_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if run is None:
            return False
        context = await context_for(db, run)
        if not await _lock_gates(db, context):
            return False
        machine = await machine_for(db, run)
        machine.status, machine.error = "expired", "runtime_run_expired"
        machine.emit(
            "مهلت اجرای فرایند تمام شده است؛ می‌توانید دوباره شروع کنید.",
            kind="text",
            buttons=[],
            notice=True,
        )
        jobs = (
            await db.scalars(
                select(WorkflowActionJob)
                .where(
                    WorkflowActionJob.run_id == run.id,
                    WorkflowActionJob.status.in_(("pending", "waiting_approval")),
                )
                .with_for_update()
            )
        ).all()
        for job in jobs:
            job.status = "cancelled"
        db.add(
            WorkflowEvent(
                store_id=run.store_id,
                run_id=run.id,
                bot_id=run.bot_id,
                input_id="expiry:" + run.id,
                kind="timeout",
                node_id=run.node_id,
                status="expired",
                error_code="runtime_run_expired",
                summary={},
                correlation_id=run.correlation_id,
            )
        )
        await persist(db, run, machine)
        await db.commit()
        return True


async def run_workers(session_factory, *, stop=None):
    """Run bounded cooperative batches; operational entry point never enables Runtime."""
    stop = stop or asyncio.Event()
    while not stop.is_set():
        await recover_sending(session_factory)
        progressed = False
        for work in (expire_once, action_once, inbox_once, timeout_once, deliver_once):
            for _ in range(20):
                if not await work(session_factory):
                    break
                progressed = True
        if not progressed:
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass
