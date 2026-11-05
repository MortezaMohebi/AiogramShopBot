"""Atomic Backend Action invocation; no listener, customer FSM or provider I/O."""

from __future__ import annotations

import asyncio
import hmac
import json
import re
import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from models.shop_action import ShopActionExecution
from models.shop_workflow import ShopWorkflow, ShopWorkflowRevision
from services import shop_admin_security as security
from services.shop_actions.approvals import consume_authorizations
from services.shop_actions.context import refresh_principal
from services.shop_actions.contracts import (
    ActionError,
    ActionRejected,
    ActionResult,
    Invocation,
)
from services.shop_actions.hashing import request_hash, sha256
from services.shop_actions.observability import observe
from services.shop_actions.policies import require_available


def _failure(invocation, code, *, retryable=False, unavailable=False):
    """Render only a stable allowlisted-format code, never an exception string."""
    if not re.fullmatch(r"action_[a-z0-9_]{1,56}", code):
        code = "action_failed"
    return ActionResult(
        status="unavailable" if unavailable else "retryable" if retryable else "failed",
        error=ActionError(code=code),
        correlation_id=invocation.correlation_id,
        retryable=retryable,
        retry_count=invocation.attempt,
        retry_after_seconds=1 if retryable else None,
    )


def unavailable_result(invocation: Invocation, code: str | None) -> ActionResult | None:
    """Classify known dependency rejections before execution or proof issuance."""
    if code in {
        "action_service_unavailable",
        "action_return_policy_unavailable",
        "action_platform_unavailable",
        "action_bot_unavailable",
        "action_cart_disabled",
        "action_catalog_unavailable",
        "action_simulation_unavailable",
        "action_dry_run_unavailable",
        "action_unknown",
        "action_version_unavailable",
    }:
        return _failure(invocation, code, unavailable=True)
    return None


async def _workflow_scope(db, principal, invocation):
    """Optional trace references never grant rights to another workflow or node."""
    if invocation.workflow_id is None:
        return
    if invocation.workflow_run_id is not None:
        from models.shop_workflow_runtime import (
            WorkflowRun,
            PublishedWorkflow,
            WorkflowActionJob,
        )
        from services.shop_workflow_schema import canonical_json

        run = await db.scalar(
            select(WorkflowRun).where(
                WorkflowRun.id == invocation.workflow_run_id,
                WorkflowRun.store_id == principal.store_id,
                WorkflowRun.bot_id == principal.bot_id,
                WorkflowRun.customer_id == principal.customer_id,
                WorkflowRun.identity_id == principal.identity_id,
            )
        )
        job = await db.scalar(
            select(WorkflowActionJob).where(
                WorkflowActionJob.run_id == invocation.workflow_run_id,
                WorkflowActionJob.invocation_id == invocation.invocation_id,
                WorkflowActionJob.store_id == principal.store_id,
            )
        )
        published = await db.get(PublishedWorkflow, run.publication_id) if run else None
        if (
            run is None
            or job is None
            or published is None
            or published.workflow_id != invocation.workflow_id
            or published.revision != invocation.workflow_revision
            or job.node_id != invocation.node_id
            or job.action_key != invocation.action_key
            or job.action_version != invocation.action_version
            or canonical_json(job.input) != canonical_json(invocation.input)
        ):
            raise ActionRejected("action_workflow_unavailable")
        if job.status != "succeeded" and (
            run.node_id != job.node_id
            or run.state.get("epoch") != job.epoch
            or run.status not in {"waiting_action", "waiting_approval"}
        ):
            raise ActionRejected("action_workflow_unavailable")
        node = next(
            (n for n in published.definition["nodes"] if n["id"] == invocation.node_id),
            None,
        )
        if (
            node is None
            or node["type"] != "action"
            or node["config"].get("action_key") != invocation.action_key
            or node["config"].get("action_version") != invocation.action_version
        ):
            raise ActionRejected("action_node_binding_mismatch")
        return
    head = await db.scalar(
        select(ShopWorkflow).where(
            ShopWorkflow.id == invocation.workflow_id,
            ShopWorkflow.store_id == principal.store_id,
            ShopWorkflow.status != "deleted",
        )
    )
    revision = await db.scalar(
        select(ShopWorkflowRevision).where(
            ShopWorkflowRevision.workflow_id == invocation.workflow_id,
            ShopWorkflowRevision.store_id == principal.store_id,
            ShopWorkflowRevision.revision == invocation.workflow_revision,
        )
    )
    if head is None or revision is None:
        raise ActionRejected("action_workflow_unavailable")
    if invocation.node_id:
        nodes = json.loads(revision.snapshot_json)["definition"]["nodes"]
        node = next((item for item in nodes if item["id"] == invocation.node_id), None)
        if (
            node is None
            or node["type"] != "action"
            or node["config"].get("action_key") != invocation.action_key
            or node["config"].get("action_version") != invocation.action_version
        ):
            raise ActionRejected("action_node_binding_mismatch")


async def _claim(db, principal, invocation, spec, digest):
    """Serialize an identical operation using SQL uniqueness plus row locking."""
    key_hash = sha256(invocation.idempotency_key or invocation.invocation_id)
    query = (
        select(ShopActionExecution)
        .where(
            ShopActionExecution.store_id == principal.store_id,
            ShopActionExecution.actor_key == principal.actor_key,
            ShopActionExecution.idempotency_sha256 == key_hash,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = await db.scalar(query)
    existing = row is not None
    if row is None:
        row = ShopActionExecution(
            id=invocation.invocation_id,
            store_id=principal.store_id,
            bot_id=principal.bot_id,
            platform=principal.platform,
            actor_key=principal.actor_key,
            action_key=invocation.action_key,
            action_version=invocation.action_version,
            idempotency_sha256=key_hash,
            input_sha256=digest,
            workflow_id=invocation.workflow_id,
            workflow_revision=invocation.workflow_revision,
            workflow_run_id=invocation.workflow_run_id,
            node_id=invocation.node_id,
            side_effect=spec.descriptor.side_effect,
            status="pending_approval",
            result_json="{}",
            retry_count=0,
            correlation_id=invocation.correlation_id,
            started_at=security.clock(),
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            # A competing committed writer is visible after the savepoint rollback.
            row = await db.scalar(query)
            existing = True
    if (
        row is None
        or row.id != invocation.invocation_id
        or not hmac.compare_digest(row.input_sha256, digest)
    ):
        raise ActionRejected("action_idempotency_conflict")
    return row, existing


async def invoke(
    db, principal, invocation: Invocation, *, registry=None
) -> ActionResult:
    """Execute one authorized Action and its receipt in the caller's dedicated session.

    The caller must give this boundary a dedicated session with no unrelated
    pending writes. All business adapters flush only. No automatic retry runs
    here; future Runtime may retry only the declared safe, same operation.
    """
    if registry is None:
        from services.shop_actions.catalog import actions

        registry = actions()
    started = time.monotonic()
    spec = None
    row = None
    deduplicated = False
    try:
        # Revalidate model_copy/programmatic dictionaries just as strictly as HTTP.
        invocation = Invocation.model_validate(invocation.model_dump())
        principal = await refresh_principal(db, principal)
        spec = registry.resolve(invocation.action_key, invocation.action_version)
        typed_input = spec.input(invocation.input)
        descriptor = spec.descriptor
        await require_available(db, principal, spec, invocation)
        await _workflow_scope(db, principal, invocation)
        if invocation.mode == "simulation":
            if descriptor.simulator != "deterministic" or spec.simulate is None:
                raise ActionRejected("action_simulation_unavailable")
            result = ActionResult(
                status="succeeded",
                output=spec.safe_output(
                    spec.simulate(
                        typed_input.model_dump(mode="json"), principal.platform
                    )
                ),
                correlation_id=invocation.correlation_id,
                simulated=True,
            )
        elif invocation.mode == "dry_run":
            if not descriptor.dry_run:
                raise ActionRejected("action_dry_run_unavailable")
            output = (
                await spec.preflight(db, principal, typed_input)
                if spec.preflight
                else None
            )
            result = ActionResult(
                status="succeeded" if output is not None else "skipped",
                output=spec.safe_output(output) if output is not None else None,
                error=(
                    ActionError(code="action_exact_preview_unavailable")
                    if output is None
                    else None
                ),
                correlation_id=invocation.correlation_id,
                dry_run=True,
                exact_preview=output is not None,
            )
        else:
            if descriptor.idempotency == "required" and not invocation.idempotency_key:
                raise ActionRejected("action_idempotency_required")
            digest = request_hash(principal, invocation, typed_input)
            row, existing = await _claim(db, principal, invocation, spec, digest)
            resumable = (
                row.status == "pending_approval"
                or (
                    row.status == "retryable"
                    and invocation.attempt == row.retry_count + 1
                )
                or (
                    row.error_code
                    in {"action_approval_invalid", "action_approval_expired"}
                )
            )
            if existing and not resumable:
                result = ActionResult.model_validate(json.loads(row.result_json))
                deduplicated = True
            else:
                # A completed receipt remains recoverable after delivery retries;
                # the budget restricts adapter execution, never exact replay.
                if invocation.attempt > descriptor.max_retries:
                    raise ActionRejected("action_retry_exhausted")
                try:
                    async with db.begin_nested():
                        if await consume_authorizations(
                            db,
                            principal=principal,
                            invocation=invocation,
                            spec=spec,
                            digest=digest,
                        ):
                            async with asyncio.timeout(descriptor.timeout_seconds):
                                output = await spec.adapter(db, principal, typed_input)
                                safe_output = spec.safe_output(output)
                            result = ActionResult(
                                status="succeeded",
                                output=safe_output,
                                correlation_id=invocation.correlation_id,
                                execution_receipt=row.id,
                                side_effect_receipt=(
                                    row.id
                                    if descriptor.side_effect
                                    not in {"none", "read_only"}
                                    else None
                                ),
                                retry_count=invocation.attempt,
                            )
                        else:
                            result = ActionResult(
                                status="pending_approval",
                                correlation_id=invocation.correlation_id,
                                execution_receipt=row.id,
                            )
                except (ActionRejected, TimeoutError) as error:
                    code = (
                        error.code
                        if isinstance(error, ActionRejected)
                        else "action_timeout"
                    )
                    retry = (
                        code in descriptor.retryable_codes
                        and invocation.attempt < descriptor.max_retries
                    )
                    result = _failure(invocation, code, retryable=retry)
                    result.execution_receipt = row.id
                except SQLAlchemyError:
                    result = _failure(
                        invocation,
                        "action_busy",
                        retryable=invocation.attempt < descriptor.max_retries,
                    )
                    result.execution_receipt = row.id
                except Exception:
                    # Adapter exceptions are private. The nested transaction is already rolled back.
                    result = _failure(invocation, "action_failed")
                    result.execution_receipt = row.id
                row.status = result.status
                row.error_code = result.error.code if result.error else None
                row.retry_count = invocation.attempt
                row.finished_at = security.clock()
                result.duration_ms = int((time.monotonic() - started) * 1000)
                row.result_json = result.model_dump_json()
            try:
                await db.commit()
            except SQLAlchemyError:
                # A lost commit acknowledgment is unknown, never proof of no effect.
                await db.rollback()
                result = ActionResult(
                    status="pending_external",
                    error=ActionError(code="action_outcome_unknown"),
                    correlation_id=invocation.correlation_id,
                    execution_receipt=invocation.invocation_id,
                )
    except ActionRejected as error:
        result = unavailable_result(invocation, error.code) or _failure(
            invocation, error.code
        )
    except (ValueError, TypeError):
        result = _failure(invocation, "action_invalid_request")
    except SQLAlchemyError:
        await db.rollback()
        result = _failure(
            invocation,
            "action_busy",
            retryable=bool(spec and spec.descriptor.max_retries),
        )
    result.duration_ms = int((time.monotonic() - started) * 1000)
    observe(spec, principal, result, deduplicated=deduplicated)
    return result
