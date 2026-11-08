"""Recoverable workers for Action jobs, sequenced delivery, timeouts and inboxes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import and_, literal, or_, select
from sqlalchemy.orm import aliased

import config
from channels.contracts import Platform
from models.shop_action import ShopActionExecution
from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import ShopBot, ShopStore
from models.shop_workflow_runtime import (
    PublishedWorkflow,
    RuntimeBinding,
    RuntimeGate,
    RuntimeSlot,
    WorkflowActionJob,
    WorkflowDeliveryAttempt,
    WorkflowInbox,
    WorkflowOutbox,
    WorkflowRun,
    WorkflowWait,
)
from services.shop_service_controls import service_enabled
from services import shop_admin_security as security
from services.shop_action_bindings import write_outputs
from services.shop_actions.approvals import issue_authorization
from services.shop_actions.catalog import actions
from services.shop_actions.context import customer_principal
from services.shop_actions.contracts import (
    ActionRejected,
    Invocation,
)
from services.shop_actions.execution import invoke, unavailable_result
from services.shop_bot_context import resolve_bot_context
from services.shop_runtime.contracts import TERMINAL, DeliveryRejected, RuntimeInput
from services.shop_runtime.publication import digest
from services.shop_runtime.sessions import (
    InvalidStoredRun,
    _SUPPORTED_ENTRY_KINDS,
    _supported_binding,
    quarantine_run,
    action_budget,
    enabled,
    event_capacity,
    gate_key,
    handle,
    machine_for,
    persist,
    system_event,
)


def eligible_bots():
    """Exclude paused tenants before scheduling so one Bot cannot starve others."""
    store_gate, bot_gate = aliased(RuntimeGate), aliased(RuntimeGate)
    query = (
        select(ShopBot.id)
        .join(ShopStore, ShopStore.id == ShopBot.store_id)
        .where(
            ShopBot.status == "active",
            ShopBot.runtime_owner == "registry",
            ShopStore.state == "active",
            ~select(ShopBotOperations.bot_id)
            .where(
                ShopBotOperations.bot_id == ShopBot.id,
                ShopBotOperations.desired_state != "active",
            )
            .exists(),
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
        not service_enabled("workflow-runtime")
        or config.SHOP_WORKFLOW_RUNTIME_KILL_SWITCH
    ):
        query = query.where(False)
    return query


def eligible_runs():
    """Project scheduling gates without using customer data as metric dimensions."""
    return select(WorkflowRun.id).where(
        WorkflowRun.bot_id.in_(eligible_bots()),
        select(RuntimeBinding.id).where(
            RuntimeBinding.id == WorkflowRun.binding_id,
            RuntimeBinding.store_id == WorkflowRun.store_id,
            RuntimeBinding.bot_id == WorkflowRun.bot_id,
            RuntimeBinding.kind.in_(_SUPPORTED_ENTRY_KINDS),
            RuntimeBinding.fallback == "ignore",
        ).exists(),
    )


async def context_for(db, run):
    """Recheck persisted entry authority and the current registered bot identity."""
    binding = await db.scalar(select(RuntimeBinding).where(
        RuntimeBinding.id == run.binding_id,
    ).execution_options(populate_existing=True))
    if not _supported_binding(binding, store_id=run.store_id, bot_id=run.bot_id):
        raise security.SecurityRejected("runtime_entry_unavailable", 409)
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


async def _worker_machine(db, run, *, job=None):
    """Quarantine an invalid pinned snapshot before scheduling physical work."""
    try:
        return await machine_for(db, run)
    except InvalidStoredRun as invalid:
        await quarantine_run(db, run, invalid.code)
        if job is not None:
            job.status, job.error_code = "failed", invalid.code
        await db.commit()
        return None


async def action_once(session_factory):
    """Invoke one stable Action and reconcile its separate receipt while holding Run lock."""
    async with session_factory() as db:
        candidate = await db.scalar(
            select(WorkflowActionJob)
            .join(WorkflowRun, WorkflowRun.id == WorkflowActionJob.run_id)
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
                WorkflowActionJob.available_at <= security.clock(),
            )
            .order_by(WorkflowActionJob.created_at, WorkflowActionJob.id)
            .with_for_update(of=WorkflowRun, skip_locked=True)
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
            .execution_options(populate_existing=True)
        )
        if job is None or job.status not in {"pending", "waiting_approval"}:
            return False
        if job.status == "waiting_approval" and job.approval_id is None:
            return False
        if security.utc(job.available_at) > security.clock():
            return False
        if security.utc(run.expires_at) <= security.clock():
            run.status, run.error_code = "expired", "runtime_run_expired"
            job.status = "cancelled"
            await system_event(
                db,
                run,
                kind="timeout",
                status="expired",
                error_code="runtime_run_expired",
            )
            await db.commit()
            return True
        if (
            run.status not in {"waiting_action", "waiting_approval"}
            or run.node_id != job.node_id
            or (isinstance(run.state, dict) and run.state.get("epoch") != job.epoch)
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
        machine = await _worker_machine(db, run, job=job)
        if machine is None:
            return True
        missing_code = None
        try:
            spec = actions().resolve(job.action_key, job.action_version)
        except ActionRejected as error:
            if error.code not in {"action_unknown", "action_version_unavailable"}:
                raise
            # A registry miss is a no-effect outcome, never a Layer 2 receipt.
            missing_code = error.code
            spec = None
        policy = spec.descriptor.confirmation if spec is not None else None
        committed = await db.get(ShopActionExecution, job.invocation_id)
        succeeded = committed is not None and committed.status == "succeeded"
        budget_error = await action_budget(db, run) if not succeeded else None
        if budget_error:
            machine.status, machine.error = "failed", budget_error
            machine.action, machine.outbound = None, []
            job.status, job.error_code = "failed", machine.error
            await persist(db, run, machine)
            await db.commit()
            return True
        if (
            not succeeded
            and policy in {"operator_approval", "both"}
            and not job.approval_id
        ):
            run.status = "waiting_approval"
            job.status = "waiting_approval"
            await db.commit()
            return True
        attempt = job.attempts
        if committed is not None and committed.status == "retryable":
            # A crash may lose the coordinator update after Layer 2 committed
            # its retryable receipt. Reconcile the persisted retry number and
            # backoff instead of allocating another invocation.
            attempt = max(attempt, committed.retry_count + 1)
            retry_at = security.utc(committed.finished_at) + timedelta(
                seconds=min(300, 2**attempt)
            )
            if security.clock() < retry_at:
                job.available_at = retry_at
                await db.commit()
                return True
        try:
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
                attempt=attempt,
            )
        except ValidationError:
            job.status, job.error_code = "failed", "runtime_stored_job_invalid"
            await quarantine_run(db, run, job.error_code)
            await db.commit()
            return True
        try:
            result = unavailable_result(invocation, missing_code)
            if result is None:
                # This session owns proof and executor commits. Never give it the Run-lock session.
                async with session_factory() as execution_db:
                    execution_principal = await customer_principal(
                        execution_db, verified_bot=context, platform_user_id=run.user_id
                    )
                    if not succeeded and policy in {"customer_confirmation", "both"}:
                        if machine.state.get("confirmed_values") != digest(
                            machine.values
                        ):
                            raise ActionRejected("runtime_confirmation_missing")
                        try:
                            confirmed_at = security.utc(
                                datetime.fromisoformat(
                                    machine.state.get("confirmed_at") or ""
                                )
                            )
                        except (ValueError, TypeError):
                            raise ActionRejected(
                                "runtime_confirmation_missing"
                            ) from None
                        elapsed = (security.clock() - confirmed_at).total_seconds()
                        if not 0 <= elapsed <= 300:
                            raise ActionRejected("runtime_confirmation_expired")
                        try:
                            proof = await issue_authorization(
                                execution_db,
                                subject=execution_principal,
                                approver=execution_principal,
                                invocation=invocation,
                                purpose="customer_confirmation",
                                registry=actions(),
                            )
                        except ActionRejected as error:
                            # Proof issuance independently checks live dependencies.
                            # Only allowlisted availability errors take this port.
                            result = unavailable_result(invocation, error.code)
                            if result is None:
                                raise
                        else:
                            invocation = invocation.model_copy(
                                update={"confirmation_receipt": proof}
                            )
                    if result is None:
                        if job.approval_id:
                            proof = (
                                security.cipher()
                                .decrypt(job.approval_id.encode())
                                .decode()
                            )
                            invocation = invocation.model_copy(
                                update={"approval_receipt": proof}
                            )
                        result = await invoke(
                            execution_db, execution_principal, invocation
                        )
        except ActionRejected as error:
            machine.fail(error.code)
            if error.code == "runtime_confirmation_expired":
                machine.outbound[-1]["text"] = (
                    "مهلت تأیید تمام شده است؛ فرایند را دوباره شروع و اطلاعات را بازبینی کنید."
                )
            job.status = "failed"
            job.error_code = error.code
            await system_event(
                db,
                run,
                kind="action",
                status="failed",
                error_code=error.code,
                summary={"job_id": job.id, "attempt": attempt},
            )
            await persist(db, run, machine)
            await db.commit()
            return True
        if succeeded and result.status != "succeeded":
            # A removed version or newly disabled dependency cannot undo an
            # already committed effect. Retain Layer 2 evidence but do not
            # adopt any receipt until its request binding can be verified.
            run.status, run.error_code = (
                "suspended",
                "runtime_action_reconciliation_required",
            )
            job.status, job.error_code = "uncertain", run.error_code
            await system_event(
                db,
                run,
                kind="action",
                status="suspended",
                error_code=run.error_code,
                summary={"job_id": job.id},
            )
            await db.commit()
            return True
        if result.status != "pending_approval":
            job.attempts = invocation.attempt + 1
        job.receipt_id = result.execution_receipt
        await system_event(
            db,
            run,
            kind="action",
            status=result.status,
            error_code=result.error.code if result.error else None,
            summary={
                "job_id": job.id,
                "attempt": invocation.attempt,
                "receipt_id": result.execution_receipt,
            },
        )
        config = machine.config(machine.nodes[job.node_id])
        if result.status == "succeeded":
            try:
                write_outputs(
                    config, result.output or {}, machine.values, machine.declarations
                )
                if spec.descriptor.side_effect not in {"none", "read_only"}:
                    machine.state["past"] = []
                machine.state.pop("confirmed_values", None)
                machine.state.pop("confirmed_at", None)
                machine.resume_at("success")
                job.status = "succeeded"
                job.error_code = None
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
            job.error_code = (
                result.error.code if result.error else "runtime_action_failed"
            )
            if (
                result.status == "retryable"
                and spec is not None
                and invocation.attempt < spec.descriptor.max_retries
                and spec.descriptor.side_effect != "irreversible"
            ):
                job.status = "pending"
                job.available_at = security.clock() + timedelta(
                    seconds=min(300, 2**job.attempts)
                )
                run.status = "waiting_action"
                run.updated_at = security.clock()
                run.lock_version += 1
                await db.commit()
                return True
            job.status = "failed"
            try:
                machine.move(
                    "unavailable" if result.status == "unavailable" else "error"
                )
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
            .join(WorkflowRun, WorkflowRun.id == WorkflowOutbox.run_id)
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
            .order_by(
                WorkflowOutbox.created_at, WorkflowOutbox.sequence, WorkflowOutbox.id
            )
            .with_for_update(of=WorkflowRun, skip_locked=True)
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
            .execution_options(populate_existing=True)
        )
        if (
            row is None
            or row.status not in {"pending", "retryable"}
            or security.utc(row.available_at) > security.clock()
        ):
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
        if not isinstance(run.state, dict) or not isinstance(row.payload, dict):
            row.status, row.error_code = "cancelled", "runtime_stored_delivery_invalid"
            await quarantine_run(db, run, row.error_code)
            await db.commit()
            return True
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
            row.status = "cancelled"
            row.error_code = "runtime_actor_unavailable"
            if run.status not in TERMINAL:
                run.status = "suspended"
                run.error_code = row.error_code
            await db.commit()
            return True
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
            .execution_options(populate_existing=True)
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
            # The durable claim commits before this transaction; actor access
            # can be revoked in that interval, just like the Bot/Runtime gates.
            await customer_principal(
                db, verified_bot=context, platform_user_id=run.user_id
            )
        except (security.SecurityRejected, ActionRejected):
            row.status = "cancelled"
            row.error_code = "runtime_actor_unavailable"
            attempt.outcome = "cancelled"
            attempt.error_code = row.error_code
            if run.status not in TERMINAL:
                run.status = "suspended"
                run.error_code = row.error_code
            await db.commit()
            return True
        try:
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


def _pending_answer():
    """Prioritize an already accepted answer for its exact input-wait epoch."""
    return (
        select(WorkflowInbox.id)
        .where(
            WorkflowInbox.run_id == WorkflowWait.run_id,
            WorkflowInbox.epoch == WorkflowWait.epoch,
            WorkflowInbox.status == "pending",
            WorkflowInbox.created_at < WorkflowWait.deadline,
        )
        .correlate(WorkflowWait)
        .exists()
    )


async def timeout_once(session_factory):
    """Serialize elapsed waits against customer input, worker actions and cancellation."""
    async with session_factory() as db:
        wait = await db.scalar(
            select(WorkflowWait)
            .join(WorkflowRun, WorkflowRun.id == WorkflowWait.run_id)
            .where(
                WorkflowWait.deadline <= security.clock(),
                # Retained waits on cancelled/suspended Runs must not occupy
                # the oldest candidate forever and starve live due waits.
                WorkflowWait.run_id.in_(
                    eligible_runs().where(
                        WorkflowRun.status.in_(("waiting_input", "waiting_timeout"))
                    )
                ),
                or_(WorkflowWait.kind == "delay", ~_pending_answer()),
            )
            .order_by(WorkflowWait.deadline)
            .with_for_update(of=WorkflowRun, skip_locked=True)
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
            or (isinstance(run.state, dict) and wait.epoch != run.state.get("epoch"))
            or security.utc(wait.deadline) > security.clock()
        ):
            return False
        try:
            context = await context_for(db, run)
            if not await _lock_gates(db, context):
                return False
        except security.SecurityRejected:
            return False
        machine = await _worker_machine(db, run)
        if machine is None:
            return True
        if not await event_capacity(db, run):
            machine.status, machine.error = "failed", "runtime_event_budget"
            await persist(db, run, machine)
            await db.commit()
            return True
        if security.utc(run.expires_at) <= security.clock():
            machine.status, machine.error = "expired", "runtime_run_expired"
        elif machine.status == "waiting_timeout":
            machine.resume_at()
        else:
            # A new inbox may have committed after the scheduler's first read.
            if await db.scalar(
                select(WorkflowWait.id).where(
                    WorkflowWait.id == wait.id, _pending_answer()
                )
            ):
                return False
            machine.timeout(wait.timeout_node)
        await system_event(
            db,
            run,
            kind="timeout",
            status=machine.status,
            error_code=machine.error
            or ("runtime_input_timeout" if wait.kind != "delay" else None),
        )
        await persist(db, run, machine)
        await db.commit()
        return True


async def inbox_once(session_factory):
    """Resume one accepted input after process restart; keep private payload only while pending."""
    async with session_factory() as db:
        preceding = aliased(WorkflowInbox)
        control = and_(
            WorkflowInbox.payload["kind"].as_string() == "command",
            WorkflowInbox.payload["text"]
            .as_string()
            .in_(("/cancel", "/menu", "/restart")),
        )
        query = (
            select(WorkflowInbox)
            .join(
                RuntimeSlot,
                and_(
                    RuntimeSlot.bot_id == WorkflowInbox.bot_id,
                    RuntimeSlot.user_id == WorkflowInbox.user_id,
                ),
            )
            .outerjoin(WorkflowRun, WorkflowRun.id == WorkflowInbox.run_id)
            .where(
                WorkflowInbox.status == "pending",
                WorkflowInbox.bot_id.in_(eligible_bots()),
                or_(
                    WorkflowInbox.run_id.is_(None),
                    WorkflowRun.status.not_in(("waiting_action", "waiting_approval")),
                    control,
                ),
                or_(
                    control,
                    WorkflowInbox.run_id.is_(None),
                    ~select(preceding.id)
                    .where(
                        preceding.bot_id == WorkflowInbox.bot_id,
                        preceding.user_id == WorkflowInbox.user_id,
                        preceding.status == "pending",
                        preceding.sequence < WorkflowInbox.sequence,
                    )
                    .exists(),
                ),
            )
            .order_by(
                WorkflowInbox.created_at, WorkflowInbox.sequence, WorkflowInbox.id
            )
        )
        # PostgreSQL cannot lock the nullable side of an outer join. Claim each
        # class separately and pick the oldest: starts without a current Run
        # need the Slot; all other inputs also need its current Run to be free.
        owner = aliased(WorkflowRun)
        bound = await db.scalar(
            query.join(owner, owner.id == RuntimeSlot.run_id)
            .with_for_update(of=(RuntimeSlot, owner), skip_locked=True)
            .limit(1)
        )
        fresh = await db.scalar(
            query.where(RuntimeSlot.run_id.is_(None))
            .with_for_update(of=RuntimeSlot, skip_locked=True)
            .limit(1)
        )
        inbox = min(
            (row for row in (bound, fresh) if row is not None),
            key=lambda row: (row.created_at, row.sequence, row.id),
            default=None,
        )
        if inbox is None:
            return False
        try:
            event = RuntimeInput.model_validate(inbox.payload)
            if (
                event.update_id != inbox.input_id
                or event.user_id != inbox.user_id
                or (event.kind == "command" and not event.text.split())
            ):
                raise ValueError("runtime_stored_input_invalid")
        except ValueError:
            # Only parse/identity errors at the persisted input boundary are
            # quarantined. Database, programming and provider failures propagate.
            inbox.status, inbox.payload, inbox.error_code = (
                "rejected",
                {},
                "runtime_stored_input_invalid",
            )
            inbox.outcome = {
                "handled": True,
                "status": "rejected",
                "error_code": inbox.error_code,
            }
            await db.commit()
            return True
        try:
            context = await resolve_bot_context(
                db,
                authenticated_bot_id=inbox.bot_id,
                authenticated_platform=Platform(event.platform),
            )
            if not await enabled(db, context):
                return False
            result = await handle(db, context=context, event=event, resume_pending=True)
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
        machine = await _worker_machine(db, run)
        if machine is None:
            return True
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
        if not await system_event(
            db, run, kind="timeout", status="expired", error_code="runtime_run_expired"
        ):
            machine.status, machine.error = "failed", "runtime_event_budget"
            machine.outbound = []
        await persist(db, run, machine)
        await db.commit()
        return True


async def run_workers(session_factory, *, stop=None):
    """Run bounded cooperative batches; operational entry point never enables Runtime."""
    stop = stop or asyncio.Event()
    while not stop.is_set():
        if not service_enabled("workflow-runtime"):
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass
            continue
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
