"""Store-scoped Runtime inspection and audited recovery without exposing private input."""

from __future__ import annotations

from sqlalchemy import case, extract, func, select

import config
from models.shop_multibot import ShopBot
from models.shop_workflow_runtime import (
    PublishedWorkflow,
    RuntimeAudit,
    RuntimeBinding,
    RuntimeGate,
    WorkflowActionJob,
    WorkflowDeliveryAttempt,
    WorkflowEvent,
    WorkflowInbox,
    WorkflowOutbox,
    WorkflowRun,
)
from services import shop_admin_security as security
from services.shop_runtime.contracts import SUPPORTED_NODES, TERMINAL, RuntimeRejected
from services.shop_runtime.publication import digest, require_manager
from services.shop_runtime.sessions import (
    _slot,
    enabled,
    gate_key,
    machine_for,
    persist,
)
from services.shop_runtime.workers import context_for


def require_manage(actor, scope):
    """Recovery needs a separate permission and manager grant in the current Store."""
    security.require_permission(actor.role, "workflows.runtime.manage")
    scope.require(scope.current_store_id, manage=True)


def safe_run(row):
    """Return operational metadata; all user variables remain private by default."""
    return {
        "id": row.id,
        "store_id": row.store_id,
        "bot_id": row.bot_id,
        "workflow_id": row.workflow_id,
        "publication_id": row.publication_id,
        "node_id": row.node_id,
        "platform": row.platform,
        "status": row.status,
        "lock_version": row.lock_version,
        "created_at": security.utc(row.created_at).isoformat(),
        "updated_at": security.utc(row.updated_at).isoformat(),
        "expires_at": security.utc(row.expires_at).isoformat(),
        "correlation_id": row.correlation_id,
        "error_code": row.error_code,
    }


def safe_outbox(row):
    """Expose delivery outcomes without text, callbacks, private file IDs or payloads."""
    return {
        "id": row.id,
        "run_id": row.run_id,
        "node_id": row.node_id,
        "sequence": row.sequence,
        "status": row.status,
        "attempts": row.attempts,
        "expected_attempts": row.attempts,
        "can_retry": row.status in {"retryable", "dead_letter"}
        and row.attempts < 5
        and row.error_code not in {None, "runtime_delivery_unknown"},
        "message_ids": row.message_ids,
        "error_code": row.error_code,
        "kind": row.payload.get("kind", "text"),
    }


async def overview(db, scope, actor):
    """Aggregate finite operational state labels within the current Store only."""
    store = scope.current_store_id
    counts = (
        await db.execute(
            select(WorkflowRun.status, func.count())
            .where(WorkflowRun.store_id == store)
            .group_by(WorkflowRun.status)
        )
    ).all()
    deliveries = (
        await db.execute(
            select(WorkflowOutbox.status, func.count())
            .where(WorkflowOutbox.store_id == store)
            .group_by(WorkflowOutbox.status)
        )
    ).all()
    gates = (
        await db.scalars(select(RuntimeGate).where(RuntimeGate.store_id == store))
    ).all()
    duration = extract("epoch", WorkflowRun.updated_at) - extract(
        "epoch", WorkflowRun.created_at
    )
    run_metrics = (
        (
            await db.execute(
                select(
                    func.count().label("runs_started"),
                    func.avg(case((WorkflowRun.status == "completed", duration))).label(
                        "completed_duration_seconds_avg"
                    ),
                    func.coalesce(
                        func.sum(WorkflowRun.state["node_transitions"].as_integer()), 0
                    ).label("node_transitions"),
                    func.coalesce(
                        func.sum(WorkflowRun.state["validation_errors"].as_integer()), 0
                    ).label("input_validation_errors"),
                ).where(WorkflowRun.store_id == store)
            )
        )
        .mappings()
        .one()
    )
    metrics = dict(run_metrics)
    # PostgreSQL AVG(EXTRACT(...)) returns Decimal; response JSON accepts a
    # float duration while retaining null when there are no completed Runs.
    average = metrics["completed_duration_seconds_avg"]
    metrics["completed_duration_seconds_avg"] = (
        float(average) if average is not None else None
    )
    for status in ("completed", "cancelled", "failed"):
        metrics["runs_" + status] = dict(counts).get(status, 0)
    metrics["duplicate_events"] = await db.scalar(
        select(func.coalesce(func.sum(WorkflowInbox.duplicate_count), 0)).where(
            WorkflowInbox.store_id == store
        )
    )
    event_metrics = (
        (
            await db.execute(
                select(
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (WorkflowEvent.kind == "action")
                                    & WorkflowEvent.status.in_(
                                        ("failed", "retryable", "unavailable")
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("action_failures"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (WorkflowEvent.kind == "timeout")
                                    | (
                                        (WorkflowEvent.kind == "action")
                                        & (WorkflowEvent.error_code == "action_timeout")
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("timeouts"),
                ).where(WorkflowEvent.store_id == store)
            )
        )
        .mappings()
        .one()
    )
    metrics.update(dict(event_metrics))
    metrics["outbox_retries"] = await db.scalar(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (WorkflowOutbox.attempts > 1, WorkflowOutbox.attempts - 1),
                        else_=0,
                    )
                ),
                0,
            )
        ).where(WorkflowOutbox.store_id == store)
    )
    metrics["outbox_deadletters"] = dict(deliveries).get("dead_letter", 0)
    metrics["delivery_failures_by_platform"] = dict(
        (
            await db.execute(
                select(WorkflowRun.platform, func.count())
                .join(WorkflowOutbox, WorkflowOutbox.run_id == WorkflowRun.id)
                .where(
                    WorkflowRun.store_id == store,
                    WorkflowOutbox.store_id == store,
                    WorkflowOutbox.id.in_(
                        select(WorkflowDeliveryAttempt.outbox_id).where(
                            WorkflowDeliveryAttempt.store_id == store,
                            WorkflowDeliveryAttempt.outcome.in_(
                                ("rejected", "uncertain")
                            ),
                        )
                    ),
                )
                .group_by(WorkflowRun.platform)
            )
        ).all()
    )
    groups = (
        (
            await db.execute(
                select(
                    WorkflowRun.workflow_id,
                    WorkflowRun.publication_id,
                    PublishedWorkflow.revision,
                    func.count().label("active_runs"),
                )
                .join(
                    PublishedWorkflow,
                    PublishedWorkflow.id == WorkflowRun.publication_id,
                )
                .where(
                    WorkflowRun.store_id == store,
                    PublishedWorkflow.store_id == store,
                    WorkflowRun.status.not_in(tuple(TERMINAL | {"suspended"})),
                    WorkflowRun.expires_at > security.clock(),
                )
                .group_by(
                    WorkflowRun.workflow_id,
                    WorkflowRun.publication_id,
                    PublishedWorkflow.revision,
                )
                .order_by(WorkflowRun.workflow_id, WorkflowRun.publication_id)
                .limit(101)
            )
        )
        .mappings()
        .all()
    )
    return {
        "global_enabled": config.SHOP_WORKFLOW_RUNTIME_ENABLED,
        "global_killed": config.SHOP_WORKFLOW_RUNTIME_KILL_SWITCH,
        "runs": dict(counts),
        "deliveries": dict(deliveries),
        "metrics": metrics,
        "active_groups": [dict(group) for group in groups[:100]],
        "active_groups_has_more": len(groups) > 100,
        "metrics_scope": {
            "store_id": store,
            "window": "all_retained_history",
            "duration": "SQL average updated_at minus created_at for completed Runs, in seconds",
            "delivery_failures": "distinct outbox intents with a rejected or uncertain physical delivery attempt, grouped by platform",
            "active": "unexpired nonterminal, nonsuspended Runs; at most 100 workflow/publication/revision groups",
        },
        "supported_nodes": sorted(SUPPORTED_NODES),
        "can_publish": security.has_permission(actor.role, "workflows.publish")
        and scope.current_store.access_level == "manager",
        "can_manage": security.has_permission(actor.role, "workflows.runtime.manage")
        and scope.current_store.access_level == "manager",
        "gates": [
            {
                "scope_key": x.scope_key,
                "bot_id": x.bot_id,
                "enabled": x.enabled,
                "killed": x.killed,
                "version": x.version,
            }
            for x in gates
        ],
    }


async def run_detail(db, scope, run_id):
    """Default-private inspection is safe even for ordinary workflow readers."""
    row = await db.scalar(
        select(WorkflowRun).where(
            WorkflowRun.id == run_id, WorkflowRun.store_id == scope.current_store_id
        )
    )
    if row is None:
        raise RuntimeRejected("runtime_run_unavailable", 404)
    published = await db.get(PublishedWorkflow, row.publication_id)
    events = (
        await db.scalars(
            select(WorkflowEvent)
            .where(
                WorkflowEvent.run_id == row.id, WorkflowEvent.store_id == row.store_id
            )
            .order_by(WorkflowEvent.created_at.desc())
            .limit(200)
        )
    ).all()
    jobs = (
        await db.scalars(
            select(WorkflowActionJob)
            .where(
                WorkflowActionJob.run_id == row.id,
                WorkflowActionJob.store_id == row.store_id,
            )
            .order_by(WorkflowActionJob.created_at)
            .limit(200)
        )
    ).all()
    outbox = (
        await db.scalars(
            select(WorkflowOutbox)
            .where(
                WorkflowOutbox.run_id == row.id, WorkflowOutbox.store_id == row.store_id
            )
            .order_by(WorkflowOutbox.sequence)
            .limit(200)
        )
    ).all()
    return safe_run(row) | {
        "revision": published.revision,
        "variables": [
            {
                "name": v["name"],
                "type": v["type"],
                "is_set": v["name"] in row.values,
                "value": "[private]",
            }
            for v in published.definition["variables"]
        ],
        "events": [
            {
                "id": x.id,
                "kind": x.kind,
                "node_id": x.node_id,
                "status": x.status,
                "summary": x.summary,
                "error_code": x.error_code,
                "created_at": security.utc(x.created_at).isoformat(),
            }
            for x in events
        ],
        "actions": [
            {
                "id": x.id,
                "key": x.action_key,
                "version": x.action_version,
                "node_id": x.node_id,
                "status": x.status,
                "receipt_id": x.receipt_id,
                "attempts": x.attempts,
                "error_code": x.error_code,
            }
            for x in jobs
        ],
        "outbox": [safe_outbox(x) for x in outbox],
    }


async def _replay(db, scope, actor, operation_id, action, target, request):
    """Reconcile lost admin responses while rejecting operation-ID reuse for other work."""
    row = await db.get(RuntimeAudit, operation_id)
    if row is None:
        return False
    if (
        row.store_id != scope.current_store_id
        or row.staff_id != actor.id
        or row.action != action
        or row.target_id != target
        or row.summary.get("request_digest") != digest(request)
    ):
        raise RuntimeRejected("runtime_operation_conflict")
    return True


def _audit(db, scope, actor, operation_id, action, target, request):
    """Store only the request hash and operational identifiers, never fresh proof."""
    db.add(
        RuntimeAudit(
            id=operation_id,
            store_id=scope.current_store_id,
            staff_id=actor.id,
            action=action,
            target_id=target,
            summary={"request_digest": digest(request)},
        )
    )


async def set_gate(
    db, *, scope, actor, bot_id, expected_version, enabled_value, killed, operation_id
):
    """CAS update opt-in flags; no request can enable another Store's Bot."""
    require_manage(actor, scope)
    key = gate_key(scope.current_store_id, bot_id)
    request = {
        "bot_id": bot_id,
        "expected_version": expected_version,
        "enabled": enabled_value,
        "killed": killed,
    }
    if await _replay(db, scope, actor, operation_id, "gate", key, request):
        return {"replayed": True, "operation_id": operation_id, "scope_key": key}
    if bot_id:
        bot = await db.get(ShopBot, bot_id)
        if bot is None or bot.store_id != scope.current_store_id:
            raise RuntimeRejected("runtime_bot_unavailable", 404)
    # The Store row serializes absent-gate creation and establishes consistent gate order.
    from models.shop_multibot import ShopStore

    await db.scalar(
        select(ShopStore)
        .where(ShopStore.id == scope.current_store_id)
        .with_for_update(key_share=True)  # NO KEY UPDATE permits concurrent FK checks.
    )
    row = await db.scalar(
        select(RuntimeGate)
        .where(
            RuntimeGate.scope_key == key, RuntimeGate.store_id == scope.current_store_id
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (row.version if row else 0) != expected_version:
        raise RuntimeRejected("runtime_gate_conflict")
    if row is None:
        row = RuntimeGate(
            store_id=scope.current_store_id, scope_key=key, bot_id=bot_id, version=1
        )
        db.add(row)
    else:
        row.version += 1
    row.enabled = enabled_value
    row.killed = killed
    _audit(db, scope, actor, operation_id, "gate", key, request)
    await db.commit()
    return {
        "version": row.version,
        "scope_key": key,
        "operation_id": operation_id,
        "enabled": row.enabled,
        "killed": row.killed,
        "replayed": False,
    }


async def recover(
    db, *, scope, actor, run_id, expected_version, operation, operation_id
):
    """Recovery never replays an irreversible or unknown Action or outbound attempt."""
    require_manage(actor, scope)
    request = {"expected_version": expected_version, "operation": operation}
    if await _replay(db, scope, actor, operation_id, "recover", run_id, request):
        return {"replayed": True, "operation_id": operation_id, "id": run_id}
    # Resolve routing metadata without taking the Run lock. Customer handlers
    # always acquire Slot before Run, including when recovery must create it.
    routing = await db.execute(
        select(WorkflowRun.bot_id, WorkflowRun.user_id).where(
            WorkflowRun.id == run_id, WorkflowRun.store_id == scope.current_store_id
        )
    )
    routing = routing.first()
    if routing is None:
        raise RuntimeRejected("runtime_run_unavailable", 404)
    from types import SimpleNamespace

    slot = await _slot(
        db,
        SimpleNamespace(store_id=scope.current_store_id, bot_id=routing.bot_id),
        routing.user_id,
    )
    row = await db.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.id == run_id, WorkflowRun.store_id == scope.current_store_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise RuntimeRejected("runtime_run_unavailable", 404)
    if row.lock_version != expected_version:
        raise RuntimeRejected("runtime_run_conflict")
    if operation in {"cancel", "mark_failed"}:
        if row.status in TERMINAL:
            raise RuntimeRejected("runtime_recovery_not_applicable")
        row.status = "cancelled" if operation == "cancel" else "failed"
        row.error_code = "runtime_operator_" + operation
        row.lock_version += 1
        row.updated_at = security.clock()
    elif operation in {"resume", "retry_failed"}:
        if slot.run_id and slot.run_id != row.id:
            competing = await db.scalar(
                select(WorkflowRun)
                .where(
                    WorkflowRun.id == slot.run_id,
                    WorkflowRun.store_id == row.store_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                competing is not None
                and competing.status not in TERMINAL | {"suspended"}
                and security.utc(competing.expires_at) > security.clock()
            ):
                raise RuntimeRejected("runtime_session_conflict")
        context = await context_for(db, row)
        if not await enabled(db, context):
            raise RuntimeRejected("runtime_disabled")
        expected = "suspended" if operation == "resume" else "failed"
        if row.status != expected or security.utc(row.expires_at) <= security.clock():
            raise RuntimeRejected("runtime_recovery_not_applicable")
        machine = await machine_for(db, row)
        node = machine.nodes[row.node_id]
        if node.type == "action":
            job = await db.scalar(
                select(WorkflowActionJob)
                .where(
                    WorkflowActionJob.run_id == row.id,
                    WorkflowActionJob.node_id == row.node_id,
                    WorkflowActionJob.epoch == row.state.get("epoch"),
                )
                .with_for_update()
            )
            if job is None or job.status not in {"pending", "waiting_approval"}:
                raise RuntimeRejected("runtime_effect_replay_forbidden")
            row.status = (
                "waiting_approval"
                if job.status == "waiting_approval"
                else "waiting_action"
            )
            row.lock_version += 1
            row.updated_at = security.clock()
        elif node.type.startswith("ask_") or node.type in {
            "confirm",
            "show_buttons",
            "wait_for_input",
        }:
            machine.state["restoring"] = True
            machine.state["attempts"] = 0
            machine.advance()
            await persist(db, row, machine)
        else:
            raise RuntimeRejected("runtime_effect_replay_forbidden")
        slot.run_id = row.id
    else:
        raise RuntimeRejected("runtime_recovery_invalid", 422)
    _audit(db, scope, actor, operation_id, "recover", row.id, request)
    await db.commit()
    return safe_run(row) | {"replayed": False, "operation_id": operation_id}


async def retire(db, *, scope, actor, publication_id, operation_id):
    """Retire entry activation while retaining immutable snapshots and pinned Runs."""
    require_manager(actor, scope)
    from services.shop_runtime.publication import lock_routes

    await lock_routes(db, scope.current_store_id)
    if await _replay(db, scope, actor, operation_id, "retire", publication_id, {}):
        return {
            "replayed": True,
            "operation_id": operation_id,
            "publication_id": publication_id,
            "retired": True,
        }
    row = await db.scalar(
        select(PublishedWorkflow).where(
            PublishedWorkflow.id == publication_id,
            PublishedWorkflow.store_id == scope.current_store_id,
        )
    )
    if row is None:
        raise RuntimeRejected("runtime_publication_missing", 404)
    bindings = (
        await db.scalars(
            select(RuntimeBinding)
            .where(
                RuntimeBinding.publication_id == row.id,
                RuntimeBinding.store_id == scope.current_store_id,
            )
            .order_by(RuntimeBinding.id)
            .with_for_update()
        )
    ).all()
    for binding in bindings:
        binding.enabled = False
        binding.version += 1
    _audit(db, scope, actor, operation_id, "retire", row.id, {})
    await db.commit()
    return {
        "replayed": False,
        "retired": True,
        "operation_id": operation_id,
        "publication_id": publication_id,
    }


async def approve_action(
    db, *, scope, actor, job_id, expected_version, operation_id, execution_factory=None
):
    """Issue a short-lived operator proof only for the exact waiting Action request."""
    from services.shop_actions.approvals import issue_authorization
    from services.shop_actions.catalog import actions
    from services.shop_actions.context import customer_principal, staff_principal
    from services.shop_actions.contracts import Invocation

    require_manage(actor, scope)
    security.require_permission(actor.role, "actions.approve")
    request = {"expected_version": expected_version}
    if await _replay(db, scope, actor, operation_id, "approve_action", job_id, request):
        return {"replayed": True, "operation_id": operation_id, "job_id": job_id}
    job = await db.scalar(
        select(WorkflowActionJob).where(
            WorkflowActionJob.id == job_id,
            WorkflowActionJob.store_id == scope.current_store_id,
        )
    )
    if job is None:
        raise RuntimeRejected("runtime_action_unavailable", 404)
    run = await db.scalar(
        select(WorkflowRun)
        .where(
            WorkflowRun.id == job.run_id, WorkflowRun.store_id == scope.current_store_id
        )
        .with_for_update()
    )
    job = await db.scalar(
        select(WorkflowActionJob)
        .where(WorkflowActionJob.id == job.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run.lock_version != expected_version:
        raise RuntimeRejected("runtime_run_conflict")
    if (
        run.status != "waiting_approval"
        or job.status != "waiting_approval"
        or job.node_id != run.node_id
        or job.epoch != run.state.get("epoch")
    ):
        raise RuntimeRejected("runtime_approval_not_pending")
    spec = actions().resolve(job.action_key, job.action_version)
    if spec.descriptor.confirmation not in {"operator_approval", "both"}:
        raise RuntimeRejected("runtime_operator_approval_not_required")
    context = await context_for(db, run)
    if not await enabled(db, context):
        raise RuntimeRejected("runtime_disabled")
    published = await db.get(PublishedWorkflow, run.publication_id)
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
    if execution_factory is None:
        from db import session_maker

        execution_factory = session_maker
    async with execution_factory() as execution_db:
        subject = await customer_principal(
            execution_db, verified_bot=context, platform_user_id=run.user_id
        )
        approver = await staff_principal(
            execution_db, scope=scope, actor=actor, bot_id=run.bot_id
        )
        proof = await issue_authorization(
            execution_db,
            subject=subject,
            approver=approver,
            invocation=invocation,
            purpose="operator_approval",
            registry=actions(),
        )
    job.approval_id = security.cipher().encrypt(proof.encode()).decode()
    job.status = "pending"
    run.status = "waiting_action"
    run.lock_version += 1
    run.updated_at = security.clock()
    _audit(db, scope, actor, operation_id, "approve_action", job.id, request)
    await db.commit()
    return {
        "job_id": job.id,
        "operation_id": operation_id,
        "status": "pending",
        "lock_version": run.lock_version,
        "replayed": False,
    }


async def retry_delivery(
    db, *, scope, actor, outbox_id, expected_attempts, operation_id
):
    """Retry only a definitely rejected send; unknown delivery can never be replayed."""
    from models.shop_workflow_runtime import WorkflowDeliveryAttempt

    require_manage(actor, scope)
    request = {"expected_attempts": expected_attempts}
    if await _replay(
        db, scope, actor, operation_id, "retry_delivery", outbox_id, request
    ):
        return {"replayed": True, "operation_id": operation_id, "id": outbox_id}
    candidate = await db.scalar(
        select(WorkflowOutbox).where(
            WorkflowOutbox.id == outbox_id,
            WorkflowOutbox.store_id == scope.current_store_id,
        )
    )
    if candidate is None:
        raise RuntimeRejected("runtime_outbox_unavailable", 404)
    run = await db.scalar(
        select(WorkflowRun).where(WorkflowRun.id == candidate.run_id).with_for_update()
    )
    row = await db.scalar(
        select(WorkflowOutbox)
        .where(WorkflowOutbox.id == candidate.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.attempts != expected_attempts:
        raise RuntimeRejected("runtime_delivery_conflict")
    attempt = await db.scalar(
        select(WorkflowDeliveryAttempt).where(
            WorkflowDeliveryAttempt.outbox_id == row.id,
            WorkflowDeliveryAttempt.number == row.attempts,
        )
    )
    if (
        row.status not in {"retryable", "dead_letter"}
        or attempt is None
        or attempt.outcome != "rejected"
        or row.attempts >= 5
    ):
        raise RuntimeRejected("runtime_delivery_replay_forbidden")
    from services.shop_runtime.workers import stale

    if stale(run, row):
        raise RuntimeRejected("runtime_prompt_obsolete")
    context = await context_for(db, run)
    if not await enabled(db, context):
        raise RuntimeRejected("runtime_disabled")
    row.status = "retryable"
    row.available_at = security.clock()
    _audit(db, scope, actor, operation_id, "retry_delivery", row.id, request)
    await db.commit()
    return {
        "id": row.id,
        "status": row.status,
        "replayed": False,
        "operation_id": operation_id,
    }
