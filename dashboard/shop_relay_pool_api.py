"""Signed Next.js administration API for many bot/Cloudflare Worker routes.

Every mutation requires a revocable admin session, server-side permission
and recent password confirmation. Provider probes never return credentials.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.admin_control_api import (
    Proof, StrictPayload, fresh_proof, throttle,
)
from dashboard.next_api import database, signed_staff
from models.shop_staff import ShopStaff
from models.shop_multibot import ShopBot
from services import shop_admin_security as security
from services import shop_relay_pool as pool

router = APIRouter(prefix="/internal/admin/v1", tags=["Relay Worker Pool"])
Db = Annotated[AsyncSession, Depends(database)]
Actor = Annotated[ShopStaff | None, Depends(signed_staff)]


def require(staff: ShopStaff | None, permission: str) -> ShopStaff:
    """Authorize against the current database role, not browser claims."""
    if staff is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(staff.role, permission)
    return staff


class WorkerCreate(StrictPayload):
    """Create an inert, allowlisted Worker, with bounded capacity."""

    slug: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    origin: str = Field(min_length=8, max_length=300)
    max_rps: int = Field(default=5, ge=1, le=20)
    max_inflight: int = Field(default=10, ge=1, le=50)


class RelayRevision(Proof):
    """Versioned action with explicit confirmation."""

    expected_version: int = Field(ge=1)


class WorkerState(RelayRevision):
    state: Literal["active", "paused", "disabled"]


class WorkerEdit(StrictPayload):
    slug: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    origin: str | None = Field(default=None, min_length=8, max_length=300)
    max_rps: int = Field(ge=1, le=20)
    max_inflight: int = Field(ge=1, le=50)
    expected_version: int = Field(ge=1)
    current_password: str | None = Field(default=None, min_length=1, max_length=256)


class RouteAssign(StrictPayload):
    """Add or reprioritize one bot/worker relation; default is staged."""

    worker_id: UUID
    priority: int = Field(ge=1, le=1000)
    expected_version: int | None = Field(default=None, ge=1)


class SecretStage(StrictPayload):
    """Accept an external-provisioning key only once, never for GET."""

    secret: str = Field(min_length=32, max_length=256)
    expected_version: int | None = Field(default=None, ge=1)


class RouteApply(RelayRevision):
    """Require password proof and current revisions before outbound getMe."""

    credential_version: int = Field(ge=1)


class SecretRevoke(Proof):
    """Revoke only inactive versions after external Worker deprovisioning."""

    version: int = Field(ge=1)


@router.get("/relay-workers")
async def list_workers(staff: Actor, db: Db) -> dict:
    """List non-secret Worker metadata and approved origins."""
    require(staff, "bots.read")
    return await pool.list_workers(db)


@router.post("/relay-workers", status_code=201)
async def create_worker(
    payload: WorkerCreate, staff: Actor, db: Db,
) -> dict:
    """Register an inactive Worker without deploying or probing it."""
    actor = require(staff, "bots.configure")
    return await pool.create_worker(
        db, actor_id=actor.id, **payload.model_dump(),
    )


@router.get("/relay-workers/{worker_id}")
async def read_worker(worker_id: UUID, staff: Actor, db: Db) -> dict:
    require(staff, "bots.read")
    return await pool.read_worker(db, str(worker_id))


@router.patch("/relay-workers/{worker_id}")
async def edit_worker(worker_id: UUID, payload: WorkerEdit, staff: Actor, db: Db) -> dict:
    actor = require(staff, "bots.apply")
    if payload.origin is not None:
        if payload.current_password is None:
            raise security.SecurityRejected("reauthentication_required", 403)
        await fresh_proof(db, actor, Proof(current_password=payload.current_password))
    return await pool.edit_worker(
        db, worker_id=str(worker_id), actor_id=actor.id,
        **payload.model_dump(exclude={"current_password"}),
    )


@router.post("/relay-workers/{worker_id}/remove")
async def remove_worker(worker_id: UUID, payload: RelayRevision, staff: Actor, db: Db) -> dict:
    actor = require(staff, "bots.apply")
    await fresh_proof(db, actor, payload)
    return await pool.remove_worker(
        db, worker_id=str(worker_id), expected_version=payload.expected_version, actor_id=actor.id,
    )


@router.post("/relay-workers/{worker_id}/state")
async def change_worker_state(
    worker_id: UUID, payload: WorkerState, staff: Actor, db: Db,
) -> dict:
    """Pause or resume a worker with password confirmation."""
    actor = require(staff, "bots.apply")
    await fresh_proof(db, actor, payload)
    return await pool.update_worker_state(
        db, worker_id=str(worker_id), actor_id=actor.id,
        expected_version=payload.expected_version,
        state=payload.state,
    )


@router.get("/bot-registry/{bot_id}/relay-routes")
async def read_bot_routes(
    bot_id: UUID, staff: Actor, db: Db,
) -> dict:
    """List only the selected bot's allowed Worker relationships."""
    require(staff, "bots.read")
    return await pool.list_bot_routes(db, str(bot_id))


@router.get("/bot-registry/{bot_id}/relay-workers")
async def bot_worker_choices(
    bot_id: UUID, staff: Actor, db: Db,
) -> dict:
    """Read shared Worker choices after validating this bot's Store access.

    The signed session boundary authorizes the active Store and bot before
    dispatch. Route counts belong only to that bot's Store; credentials and
    assignments in other Stores never appear in this selection response.
    """
    require(staff, "bots.read")
    bot = await db.get(ShopBot, str(bot_id))
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    return await pool.list_workers(db, store_id=bot.store_id)


@router.post("/bot-registry/{bot_id}/relay-routes")
async def assign_route(
    bot_id: UUID, payload: RouteAssign, staff: Actor, db: Db,
) -> dict:
    """Stage one Many2many relation; do not alter provider traffic."""
    actor = require(staff, "bots.configure")
    return await pool.assign_route(
        db, bot_id=str(bot_id), worker_id=str(payload.worker_id),
        actor_id=actor.id, priority=payload.priority,
        expected_version=payload.expected_version,
    )


@router.post(
    "/bot-registry/{bot_id}/relay-routes/{worker_id}/credentials/stage",
    status_code=201,
)
async def stage_route_key(
    bot_id: UUID, worker_id: UUID, payload: SecretStage,
    staff: Actor, db: Db,
) -> dict:
    """Encrypt the per-bot/Worker key without exposing it in the reply."""
    actor = require(staff, "bots.configure")
    return await pool.stage_credential(
        db, bot_id=str(bot_id), worker_id=str(worker_id),
        secret=payload.secret, actor_id=actor.id, expected_version=payload.expected_version,
    )


@router.post("/bot-registry/{bot_id}/relay-routes/{worker_id}/activate")
async def activate_route(
    bot_id: UUID, worker_id: UUID, payload: RouteApply,
    staff: Actor, db: Db,
) -> dict:
    """Prove read-only provider identity before promoting the route."""
    actor = require(staff, "bots.apply")
    await throttle("relay-apply:" + str(actor.id), 3, 60)
    await fresh_proof(db, actor, payload)
    return await pool.activate_route(
        db, bot_id=str(bot_id), worker_id=str(worker_id),
        actor_id=actor.id, expected_version=payload.expected_version,
        credential_version=payload.credential_version,
    )


@router.post("/bot-registry/{bot_id}/relay-routes/{worker_id}/pause")
async def pause_route(
    bot_id: UUID, worker_id: UUID, payload: RelayRevision,
    staff: Actor, db: Db,
) -> dict:
    """Stop selecting a route while retaining receipts and credentials."""
    actor = require(staff, "bots.apply")
    await fresh_proof(db, actor, payload)
    return await pool.pause_route(
        db, bot_id=str(bot_id), worker_id=str(worker_id),
        expected_version=payload.expected_version, actor_id=actor.id,
    )


@router.post("/bot-registry/{bot_id}/relay-routes/{worker_id}/remove")
async def remove_route(
    bot_id: UUID, worker_id: UUID, payload: RelayRevision, staff: Actor, db: Db,
) -> dict:
    actor = require(staff, "bots.apply")
    await fresh_proof(db, actor, payload)
    return await pool.remove_route(
        db, bot_id=str(bot_id), worker_id=str(worker_id),
        expected_version=payload.expected_version, actor_id=actor.id,
    )


@router.post(
    "/bot-registry/{bot_id}/relay-routes/{worker_id}/credentials/revoke",
)
async def revoke_route_key(
    bot_id: UUID, worker_id: UUID, payload: SecretRevoke,
    staff: Actor, db: Db,
) -> dict:
    """Mark an inactive key revoked; remove Worker-side key separately."""
    actor = require(staff, "bots.apply")
    await fresh_proof(db, actor, payload)
    return await pool.revoke_unused_credential(
        db, bot_id=str(bot_id), worker_id=str(worker_id),
        version=payload.version, actor_id=actor.id,
    )
