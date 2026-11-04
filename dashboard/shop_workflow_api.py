"""Typed Store-owned Studio endpoints on the existing signed Admin boundary."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from dashboard.shop_customer_experience_api import Actor, Db, require
from services import shop_admin_security as security
from services import shop_workflows as workflows
from services.shop_workflow_bindings import bot_choices, media_choices
from services.shop_workflow_catalog import node_catalog
from services.shop_workflow_simulator import SimulationRequest
from services.shop_workflow_requests import (
    CreateDraft,
    DuplicateDraft,
    Operation,
    RestoreDraft,
    SaveDraft,
    ValidateDraft,
)

router = APIRouter(
    prefix="/internal/admin/v1/workflows", tags=["Workflow Studio"]
)


async def payload(request: Request, model):
    """Reject malformed JSON without echoing credential-like raw validation input."""
    if not request.headers.get("content-type", "").startswith(
        "application/json"
    ):
        raise security.SecurityRejected("workflow_invalid_request", 415)
    try:
        return model.model_validate(await request.json())
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise security.SecurityRejected(
            "workflow_invalid_request", 422
        ) from None


def respond(value, status=200):
    """Never cache private workflow definitions or concurrency receipts."""
    return JSONResponse(
        value, status_code=status, headers={"Cache-Control": "no-store"}
    )


@router.get("/catalog")
async def catalog(request: Request, actor: Actor):
    """Expose typed configuration metadata and truthful Runtime availability."""
    staff, scope = require(actor, request, "workflows.read")
    return respond(
        node_catalog()
        | {
            "store_id": scope.current_store_id,
            "can_write": security.has_permission(staff.role, "workflows.write")
            and scope.current_store.access_level in {"editor", "manager"},
            "limits": {
                "request_bytes": 262144,
                "nodes": 200,
                "edges": 800,
                "variables": 100,
            },
        }
    )


@router.get("/bots")
async def bots(
    request: Request,
    actor: Actor,
    db: Db,
    store_id: UUID | None = None,
    page: int = Query(1, ge=1),
    q: str = Query("", max_length=100),
):
    """Page eligible Bot choices using actual Store ownership."""
    staff, scope = require(actor, request, "workflows.read")
    return respond(
        await bot_choices(
            db,
            scope=scope,
            actor=staff,
            store_id=str(store_id) if store_id else None,
            page=page,
            q=q,
        )
    )


@router.get("/media")
async def media(
    request: Request,
    actor: Actor,
    db: Db,
    store_id: UUID | None = None,
    page: int = Query(1, ge=1),
    kind: Literal["photo", "video", "audio", "document"] | None = None,
    q: str = Query("", max_length=100),
):
    """Use existing private media identities, never provider URLs or tokens."""
    staff, scope = require(actor, request, "workflows.read")
    return respond(
        await media_choices(
            db,
            scope=scope,
            actor=staff,
            store_id=str(store_id) if store_id else None,
            page=page,
            kind=kind,
            q=q,
        )
    )


@router.get("")
async def listing(
    request: Request,
    actor: Actor,
    db: Db,
    page: int = Query(1, ge=1),
    q: str = Query("", max_length=100),
    status: Literal["draft", "archived", "deleted", "all"] = "draft",
    store_id: UUID | None = None,
):
    """List visible Store drafts with bounded pagination and no capacity metrics."""
    staff, scope = require(actor, request, "workflows.read")
    return respond(
        await workflows.list_workflows(
            db,
            scope=scope,
            actor=staff,
            page=page,
            q=q,
            status=status,
            store_id=str(store_id) if store_id else None,
        )
    )


@router.post("")
async def create(request: Request, actor: Actor, db: Db):
    """Create one unsent workflow using a caller-reconcilable identifier."""
    staff, scope = require(actor, request, "workflows.write", write=True)
    data = await payload(request, CreateDraft)
    return respond(
        await workflows.create_draft(
            db, scope=scope, actor=staff, payload=data.model_dump(mode="json")
        ),
        201,
    )


@router.get("/{workflow_id}")
async def detail(workflow_id: UUID, request: Request, actor: Actor, db: Db):
    """Read an explicitly owned head, with current validation findings."""
    staff, scope = require(actor, request, "workflows.read")
    return respond(
        await workflows.read_workflow(
            db, scope=scope, actor=staff, workflow_id=str(workflow_id)
        )
    )


@router.patch("/{workflow_id}")
async def save(workflow_id: UUID, request: Request, actor: Actor, db: Db):
    """Compare-and-swap a draft without overwriting another tab's revision."""
    staff, scope = require(actor, request, "workflows.write", write=True)
    data = await payload(request, SaveDraft)
    return respond(
        await workflows.save_draft(
            db,
            scope=scope,
            actor=staff,
            workflow_id=str(workflow_id),
            payload=data.model_dump(mode="json"),
        )
    )


@router.get("/{workflow_id}/revisions")
async def versions(
    workflow_id: UUID,
    request: Request,
    actor: Actor,
    db: Db,
    page: int = Query(1, ge=1),
):
    """Page immutable revision metadata through its Store-owned parent."""
    staff, scope = require(actor, request, "workflows.read")
    return respond(
        await workflows.list_revisions(
            db,
            scope=scope,
            actor=staff,
            workflow_id=str(workflow_id),
            page=page,
        )
    )


@router.get("/{workflow_id}/revisions/{revision}")
async def revision(
    workflow_id: UUID, revision: int, request: Request, actor: Actor, db: Db
):
    """Inspect a scoped immutable definition and its integrity hash."""
    staff, scope = require(actor, request, "workflows.read")
    return respond(
        await workflows.read_workflow(
            db,
            scope=scope,
            actor=staff,
            workflow_id=str(workflow_id),
            revision=revision,
        )
    )


@router.get("/{workflow_id}/operations/{operation_id}")
async def operation(
    workflow_id: UUID,
    operation_id: UUID,
    request: Request,
    actor: Actor,
    db: Db,
):
    """Reconcile a possibly committed mutation without replaying it."""
    staff, scope = require(actor, request, "workflows.read")
    return respond(
        await workflows.operation_result(
            db,
            scope=scope,
            actor=staff,
            workflow_id=str(workflow_id),
            operation_id=str(operation_id),
        )
    )


@router.get("/{workflow_id}/compare")
async def compare(
    workflow_id: UUID,
    request: Request,
    actor: Actor,
    db: Db,
    left: int = Query(ge=1),
    right: int = Query(ge=1),
):
    """Compare named domain sections from two owned immutable revisions."""
    staff, scope = require(actor, request, "workflows.read")
    return respond(
        await workflows.compare_revisions(
            db,
            scope=scope,
            actor=staff,
            workflow_id=str(workflow_id),
            left=left,
            right=right,
        )
    )


@router.post("/{workflow_id}/validate")
async def validate(workflow_id: UUID, request: Request, actor: Actor, db: Db):
    """Validate saved or unsaved definitions without a database mutation."""
    staff, scope = require(actor, request, "workflows.read")
    data = await payload(request, ValidateDraft)
    return respond(
        await workflows.validate_workflow(
            db,
            scope=scope,
            actor=staff,
            workflow_id=str(workflow_id),
            definition=data.definition,
        )
    )


@router.post("/{workflow_id}/duplicate")
async def duplicate(workflow_id: UUID, request: Request, actor: Actor, db: Db):
    """Copy a same-Store snapshot into a distinct unsent draft."""
    staff, scope = require(actor, request, "workflows.write", write=True)
    data = await payload(request, DuplicateDraft)
    return respond(
        await workflows.duplicate_workflow(
            db,
            scope=scope,
            actor=staff,
            workflow_id=str(workflow_id),
            payload=data.model_dump(mode="json"),
        ),
        201,
    )


@router.post("/{workflow_id}/restore")
async def restore(workflow_id: UUID, request: Request, actor: Actor, db: Db):
    """Append an earlier definition as a new draft revision."""
    staff, scope = require(actor, request, "workflows.write", write=True)
    data = await payload(request, RestoreDraft)
    return respond(
        await workflows.restore_revision(
            db,
            scope=scope,
            actor=staff,
            workflow_id=str(workflow_id),
            payload=data.model_dump(mode="json"),
        )
    )


@router.post("/{workflow_id}/archive")
async def archive(workflow_id: UUID, request: Request, actor: Actor, db: Db):
    """Archive without deleting immutable definition history."""
    staff, scope = require(actor, request, "workflows.write", write=True)
    data = await payload(request, Operation)
    return respond(
        await workflows.set_status(
            db,
            scope=scope,
            actor=staff,
            workflow_id=str(workflow_id),
            payload=data.model_dump(mode="json"),
            status="archived",
        )
    )


@router.delete("/{workflow_id}")
async def delete(workflow_id: UUID, request: Request, actor: Actor, db: Db):
    """Soft-delete a draft; a retained revision can still be restored."""
    staff, scope = require(actor, request, "workflows.write", write=True)
    data = await payload(request, Operation)
    return respond(
        await workflows.set_status(
            db,
            scope=scope,
            actor=staff,
            workflow_id=str(workflow_id),
            payload=data.model_dump(mode="json"),
            status="deleted",
        )
    )


@router.post("/{workflow_id}/publish")
async def publish(workflow_id: UUID, request: Request, actor: Actor, db: Db):
    """Deny activation truthfully until a reviewed production Runtime exists."""
    staff, scope = require(actor, request, "workflows.write", write=True)
    await workflows.read_workflow(
        db, scope=scope, actor=staff, workflow_id=str(workflow_id)
    )
    raise security.SecurityRejected("workflow_runtime_unavailable", 409)


@router.post("/{workflow_id}/simulate")
async def simulate(workflow_id: UUID, request: Request, actor: Actor, db: Db):
    """Preview an owned revision without provider or customer-affecting operations."""
    staff, scope = require(actor, request, "workflows.read")
    data = await payload(request, SimulationRequest)
    return respond(
        await workflows.simulate_workflow(
            db,
            scope=scope,
            actor=staff,
            workflow_id=str(workflow_id),
            payload=data.model_dump(mode="json"),
        )
    )
