"""Signed human management routes for native MCP delegation consent."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request

from dashboard.shop_customer_experience_api import Actor, Db, require
from dashboard.shop_workflow_api import respond
from services import shop_admin_security as security
from services.shop_mcp import admin, grants
from services.shop_mcp.contracts import McpRejected
from services.shop_mcp.settings import from_environment

router = APIRouter(prefix="/internal/admin/v1/mcp", tags=["MCP connections"])
account_router = APIRouter(
    prefix="/internal/admin/v1/account/mcp-grants", tags=["Owned MCP grants"]
)


def enabled(request):
    """Permit consent only while the independently configured adapter is on."""
    try:
        settings = getattr(request.app.state, "mcp_settings", None)
        return (settings or from_environment()).enabled
    except McpRejected as error:
        raise security.SecurityRejected(error.code, error.status) from None


async def call(request, actor, db, function, *, extra=None, **arguments):
    """Keep native authority in the service and failures safely projected."""
    staff, scope = require(actor, request, "workflows.read")
    try:
        result = await function(db, scope=scope, actor=staff, **arguments)
        return respond(result | (extra or {}))
    except McpRejected as error:
        await db.rollback()
        raise security.SecurityRejected(error.code, error.status) from None


@router.get("")
async def overview(
    request: Request,
    actor: Actor,
    db: Db,
    page: int = Query(1, ge=1, le=100000),
):
    """List owned, Store-filtered connections."""
    return await call(
        request,
        actor,
        db,
        admin.overview,
        page=page,
        extra={"enabled": enabled(request)},
    )


@router.get("/history")
async def history(
    request: Request,
    actor: Actor,
    db: Db,
    page: int = Query(1, ge=1, le=100000),
):
    """Read bounded operational metadata without raw request bodies."""
    return await call(request, actor, db, admin.history, page=page)


@router.get("/pairings/{pairing_id}")
async def pairing(request: Request, actor: Actor, db: Db, pairing_id: UUID):
    """Review the exact signed identity, Stores and scopes before consent."""
    return await call(
        request, actor, db, admin.pairing_review, pairing_id=str(pairing_id)
    )


@router.post("/pairings/{pairing_id}/confirm")
async def confirm(request: Request, actor: Actor, db: Db, pairing_id: UUID):
    """Require fresh native authentication for the exact stored grant."""
    if not enabled(request):
        raise security.SecurityRejected("mcp_disabled", 503)
    await call(
        request, actor, db, admin.pairing_review, pairing_id=str(pairing_id)
    )
    return await call(
        request, actor, db, grants.confirm_pairing, pairing_id=str(pairing_id)
    )


@router.get("/grants/{grant_id}")
async def detail(request: Request, actor: Actor, db: Db, grant_id: UUID):
    """Reconcile consent or revocation after an unknown response."""
    return await call(
        request, actor, db, admin.grant_detail, grant_id=str(grant_id)
    )


@router.post("/grants/{grant_id}/revoke")
async def revoke(request: Request, actor: Actor, db: Db, grant_id: UUID):
    """Revoke delegation; this never decides a business operation."""
    return await call(
        request, actor, db, grants.revoke_grant, grant_id=str(grant_id)
    )


@account_router.get("/{grant_id}")
@account_router.post("/{grant_id}/revoke")
async def account_grant(
    request: Request, actor: Actor, db: Db, grant_id: UUID
):
    """Inspect or revoke only one's own grant without acquiring Store access."""
    if actor is None:
        raise security.SecurityRejected("session_expired", 401)
    try:
        return respond(
            await grants.account_grant(
                db,
                actor=actor,
                session_id=request.state.admin_session_id,
                grant_id=str(grant_id),
                revoke=request.method == "POST",
            )
        )
    except McpRejected as error:
        await db.rollback()
        raise security.SecurityRejected(error.code, error.status) from None
