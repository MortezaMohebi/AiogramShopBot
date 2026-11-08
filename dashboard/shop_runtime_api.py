"""Signed Store-scoped publication, runtime inspection and audited recovery API."""

from __future__ import annotations

from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Query, Request
from pydantic import Field
from sqlalchemy import select, func

from dashboard.shop_customer_experience_api import Actor, Db, require
from dashboard.shop_workflow_api import payload, respond
from models.shop_admin_control import AdminSession
from models.shop_workflow_runtime import (
    PublishedWorkflow,
    RuntimeBinding,
    RuntimeAudit,
    WorkflowRun,
    WorkflowOutbox,
)
from services import shop_admin_security as security
from services.shop_workflow_schema import StrictModel
from services.shop_runtime import admin, publication
from services.shop_runtime.contracts import BindingSpec

router = APIRouter(
    prefix="/internal/admin/v1/workflow-runtime", tags=["Workflow Runtime"]
)
ID = Field(min_length=36, max_length=36, pattern=r"^[0-9a-fA-F-]{36}$")


class PublishPreview(StrictModel):
    """Review exact saved revision and explicit per-Bot entry point assignments."""

    workflow_id: str = ID
    revision: int = Field(ge=1)
    bindings: list[BindingSpec] = Field(min_length=1, max_length=40)


class Activation(StrictModel):
    """The user approves an expiring server-held preview, never a new raw definition."""

    preview_id: str = ID
    approved: Literal[True]


class Operation(StrictModel):
    """A stable UUID reconciles an administrative response lost after commit."""

    operation_id: str = ID


class Gate(Operation):
    """Separate persistent Store and Bot opt-in, with optimistic edit conflict checks."""

    bot_id: str | None = None
    expected_version: int = Field(ge=0)
    enabled: bool
    killed: bool


class Recovery(Operation):
    """Allowlist recovery; no arbitrary node jump, variable injection or forced resend."""

    expected_version: int = Field(ge=0)
    operation: Literal["resume", "retry_failed", "cancel", "mark_failed"]


async def fresh(db, actor, scope):
    """Require a recent password/MFA-authenticated device session for live changes."""
    row = await db.get(AdminSession, scope.session_id)
    if row is None or row.staff_id != actor.id:
        raise security.SecurityRejected("session_expired", 401)
    security.require_recent(row)


@router.get("")
async def overview(request: Request, actor: Actor, db: Db):
    """Display truthful global/gate state and finite operational counters."""
    staff, scope = require(actor, request, "workflows.read")
    return respond(await admin.overview(db, scope, staff))


@router.get("/publications")
async def publications(
    request: Request,
    actor: Actor,
    db: Db,
    page: int = Query(1, ge=1),
    workflow_id: UUID | None = None,
):
    """List immutable versions alongside activation and retirement evidence."""
    _, scope = require(actor, request, "workflows.read")
    query = select(PublishedWorkflow).where(
        PublishedWorkflow.store_id == scope.current_store_id
    )
    if workflow_id:
        query = query.where(PublishedWorkflow.workflow_id == str(workflow_id))
    rows = (
        await db.scalars(
            query.order_by(PublishedWorkflow.created_at.desc(), PublishedWorkflow.id)
            .offset((page - 1) * 50)
            .limit(51)
        )
    ).all()
    result = []
    for row in rows[:50]:
        active = await db.scalar(
            select(func.count())
            .select_from(RuntimeBinding)
            .where(
                RuntimeBinding.publication_id == row.id,
                RuntimeBinding.enabled.is_(True),
            )
        )
        retired = await db.scalar(
            select(RuntimeAudit.id).where(
                RuntimeAudit.store_id == scope.current_store_id,
                RuntimeAudit.action == "retire",
                RuntimeAudit.target_id == row.id,
            )
        )
        result.append(
            {
                "id": row.id,
                "workflow_id": row.workflow_id,
                "revision": row.revision,
                "digest": row.digest,
                "active_bindings": active,
                "retired": retired is not None,
                "created_at": security.utc(row.created_at).isoformat(),
            }
        )
    return respond({"items": result, "page": page, "has_more": len(rows) > 50})


@router.post("/publications/preview")
async def preview(request: Request, actor: Actor, db: Db):
    """Create the explicit risk/dependency/diff review without changing live routing."""
    staff, scope = require(actor, request, "workflows.publish", write=True, manage=True)
    data = await payload(request, PublishPreview)
    return respond(
        await publication.preview(
            db,
            actor=staff,
            scope=scope,
            workflow_id=data.workflow_id,
            revision=data.revision,
            bindings=[x.model_dump() for x in data.bindings],
        )
    )


@router.post("/publications/activate")
async def activate(request: Request, actor: Actor, db: Db):
    """Activate or roll back only the exact reviewed preview after recent authentication."""
    staff, scope = require(actor, request, "workflows.publish", write=True, manage=True)
    data = await payload(request, Activation)
    await fresh(db, staff, scope)
    return respond(
        await publication.activate(
            db,
            actor=staff,
            scope=scope,
            preview_id=data.preview_id,
            approved=data.approved,
        )
    )


@router.post("/publications/{publication_id}/retire")
async def retire(publication_id: UUID, request: Request, actor: Actor, db: Db):
    """Retirement stops new entry points; active Runs retain their pinned definitions."""
    staff, scope = require(actor, request, "workflows.publish", write=True, manage=True)
    data = await payload(request, Operation)
    await fresh(db, staff, scope)
    return respond(
        await admin.retire(
            db,
            scope=scope,
            actor=staff,
            publication_id=str(publication_id),
            operation_id=data.operation_id,
        )
    )


@router.get("/bindings")
async def bindings(request: Request, actor: Actor, db: Db, page: int = Query(1, ge=1)):
    """Inspect stable entry keys and exact active version pointers without secrets."""
    _, scope = require(actor, request, "workflows.read")
    rows = (
        await db.scalars(
            select(RuntimeBinding)
            .where(RuntimeBinding.store_id == scope.current_store_id)
            .order_by(RuntimeBinding.bot_id, RuntimeBinding.kind, RuntimeBinding.key)
            .offset((page - 1) * 50)
            .limit(51)
        )
    ).all()
    return respond(
        {
            "items": [
                {
                    "id": x.id,
                    "bot_id": x.bot_id,
                    "workflow_id": x.workflow_id,
                    "publication_id": x.publication_id,
                    "kind": x.kind,
                    "key": x.key,
                    "node_id": x.node_id,
                    "enabled": x.enabled,
                    "priority": x.priority,
                    "version": x.version,
                    "eligibility": x.eligibility,
                    "fallback": x.fallback,
                }
                for x in rows[:50]
            ],
            "page": page,
            "has_more": len(rows) > 50,
        }
    )


@router.post("/gates")
async def gate(request: Request, actor: Actor, db: Db):
    """Only a freshly authenticated manager may change opt-in or the emergency stop."""
    staff, scope = require(
        actor, request, "workflows.runtime.manage", write=True, manage=True
    )
    data = await payload(request, Gate)
    await fresh(db, staff, scope)
    return respond(
        await admin.set_gate(
            db,
            scope=scope,
            actor=staff,
            bot_id=data.bot_id,
            expected_version=data.expected_version,
            enabled_value=data.enabled,
            killed=data.killed,
            operation_id=data.operation_id,
        )
    )


@router.get("/runs")
async def runs(
    request: Request,
    actor: Actor,
    db: Db,
    page: int = Query(1, ge=1),
    status: str = Query("", max_length=24),
    workflow_id: UUID | None = None,
    publication_id: UUID | None = None,
):
    """Page Run metadata with explicit filters; never return customer input values."""
    _, scope = require(actor, request, "workflows.read")
    query = select(WorkflowRun).where(WorkflowRun.store_id == scope.current_store_id)
    if status:
        query = query.where(WorkflowRun.status == status)
    if workflow_id:
        query = query.where(WorkflowRun.workflow_id == str(workflow_id))
    if publication_id:
        query = query.where(WorkflowRun.publication_id == str(publication_id))
    rows = (
        await db.scalars(
            query.order_by(WorkflowRun.created_at.desc(), WorkflowRun.id)
            .offset((page - 1) * 50)
            .limit(51)
        )
    ).all()
    return respond(
        {
            "items": [admin.safe_run(x) for x in rows[:50]],
            "page": page,
            "has_more": len(rows) > 50,
        }
    )


@router.get("/runs/{run_id}")
async def run(run_id: UUID, request: Request, actor: Actor, db: Db):
    """Inspect typed/private variable projection, trace, Actions and outbound results."""
    staff, scope = require(actor, request, "workflows.read")
    detail = await admin.run_detail(db, scope, str(run_id))
    can_approve = (
        security.has_permission(staff.role, "actions.approve")
        and security.has_permission(staff.role, "workflows.runtime.manage")
        and scope.current_store.access_level == "manager"
    )
    for job in detail["actions"]:
        job["can_approve"] = can_approve and job["status"] == "waiting_approval"
        job["expected_version"] = detail["lock_version"]
    return respond(detail)


@router.post("/runs/{run_id}/recover")
async def recover(run_id: UUID, request: Request, actor: Actor, db: Db):
    """An audited safe operation cannot become an arbitrary state or Action executor."""
    staff, scope = require(
        actor, request, "workflows.runtime.manage", write=True, manage=True
    )
    data = await payload(request, Recovery)
    await fresh(db, staff, scope)
    return respond(
        await admin.recover(
            db,
            scope=scope,
            actor=staff,
            run_id=str(run_id),
            expected_version=data.expected_version,
            operation=data.operation,
            operation_id=data.operation_id,
        )
    )


@router.get("/outbox")
async def outbox(
    request: Request,
    actor: Actor,
    db: Db,
    page: int = Query(1, ge=1),
    status: str = Query("", max_length=24),
):
    """Expose delivery status and safe receipts, keeping outbound content private."""
    _, scope = require(actor, request, "workflows.read")
    query = select(WorkflowOutbox).where(
        WorkflowOutbox.store_id == scope.current_store_id
    )
    if status:
        query = query.where(WorkflowOutbox.status == status)
    rows = (
        await db.scalars(
            query.order_by(WorkflowOutbox.created_at.desc(), WorkflowOutbox.id)
            .offset((page - 1) * 50)
            .limit(51)
        )
    ).all()
    return respond(
        {
            "items": [admin.safe_outbox(x) for x in rows[:50]],
            "page": page,
            "has_more": len(rows) > 50,
        }
    )


@router.get("/history")
async def history(request: Request, actor: Actor, db: Db, page: int = Query(1, ge=1)):
    """Return immutable activation, rollback, gate and recovery evidence."""
    _, scope = require(actor, request, "workflows.read")
    rows = (
        await db.scalars(
            select(RuntimeAudit)
            .where(RuntimeAudit.store_id == scope.current_store_id)
            .order_by(RuntimeAudit.created_at.desc(), RuntimeAudit.id)
            .offset((page - 1) * 50)
            .limit(51)
        )
    ).all()
    return respond(
        {
            "items": [
                {
                    "id": x.id,
                    "action": x.action,
                    "target_id": x.target_id,
                    "summary": x.summary,
                    "created_at": security.utc(x.created_at).isoformat(),
                }
                for x in rows[:50]
            ],
            "page": page,
            "has_more": len(rows) > 50,
        }
    )


class ActionApproval(Operation):
    """Approve only an unchanged exact pending Action at the Run's current version."""

    expected_version: int = Field(ge=0)


class DeliveryRetry(Operation):
    """Retry a known rejection with a stable operation and attempt counter."""

    expected_attempts: int = Field(ge=1, le=4)


@router.post("/actions/{job_id}/approve")
async def approve_action(job_id: UUID, request: Request, actor: Actor, db: Db):
    """Operator approval is fresh, permissioned, request-bound and audited."""
    staff, scope = require(
        actor, request, "workflows.runtime.manage", write=True, manage=True
    )
    data = await payload(request, ActionApproval)
    await fresh(db, staff, scope)
    return respond(
        await admin.approve_action(
            db,
            scope=scope,
            actor=staff,
            job_id=str(job_id),
            expected_version=data.expected_version,
            operation_id=data.operation_id,
        )
    )


@router.post("/outbox/{outbox_id}/retry")
async def retry_delivery(outbox_id: UUID, request: Request, actor: Actor, db: Db):
    """An ambiguous provider outcome cannot be converted into an automatic resend."""
    staff, scope = require(
        actor, request, "workflows.runtime.manage", write=True, manage=True
    )
    data = await payload(request, DeliveryRetry)
    await fresh(db, staff, scope)
    return respond(
        await admin.retry_delivery(
            db,
            scope=scope,
            actor=staff,
            outbox_id=str(outbox_id),
            expected_attempts=data.expected_attempts,
            operation_id=data.operation_id,
        )
    )
