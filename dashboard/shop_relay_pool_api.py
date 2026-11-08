"""Signed Next.js administration API for many bot/Cloudflare Worker routes.

Every mutation requires a revocable admin session, server-side permission
and a recent reauthentication. Provider probing additionally requires fresh
password/MFA; no route secret or Telegram token is ever returned.
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


class WorkerState(Proof):
    """Require MFA for availability state changes."""

    expected_version: int = Field(ge=1)
    state: Literal["active", "paused", "disabled"]


class RouteAssign(StrictPayload):
    """Add or reprioritize one bot/worker relation; default is staged."""

    worker_id: UUID
    priority: int = Field(ge=1, le=1000)
    expected_version: int | None = Field(default=None, ge=1)


class SecretStage(StrictPayload):
    """Accept an external-provisioning key only once, never for GET."""

    secret: str = Field(min_length=32, max_length=256)


class RouteApply(Proof):
    """Require fresh MFA and optimistic versions before outbound getMe."""

    expected_version: int = Field(ge=1)
    credential_version: int = Field(ge=1)


class RoutePause(Proof):
    """Disable a route without dropping any delivery or replay receipt."""

    expected_version: int = Field(ge=1)


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


@router.post("/relay-workers/{worker_id}/state")
async def change_worker_state(
    worker_id: UUID, payload: WorkerState, staff: Actor, db: Db,
) -> dict:
    """Pause or resume a worker only with a fresh second factor."""
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
        secret=payload.secret, actor_id=actor.id,
    )


@router.post("/bot-registry/{bot_id}/relay-routes/{worker_id}/activate")
async def activate_route(
    bot_id: UUID, worker_id: UUID, payload: RouteApply,
    staff: Actor, db: Db,
) -> dict:
    """Prove read-only provider identity; promote a route with fresh MFA."""
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
    bot_id: UUID, worker_id: UUID, payload: RoutePause,
    staff: Actor, db: Db,
) -> dict:
    """Stop selecting a route while retaining receipts and credentials."""
    actor = require(staff, "bots.apply")
    await fresh_proof(db, actor, payload)
    return await pool.pause_route(
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
