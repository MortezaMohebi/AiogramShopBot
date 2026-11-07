"""Signed, session-protected Foundation APIs for Store and Bot Registry.

Phase 1 deliberately has no enable/publish/activate-credential endpoint.
Creating a draft registration cannot register a webhook, start polling,
issue an invoice, or mutate the two existing provider connections.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.next_api import database, signed_staff
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_bot_registry as registry
from services import shop_bot_secrets as vault

router = APIRouter(prefix="/internal/admin/v1", tags=["Multi-bot foundation"])
Db = Annotated[AsyncSession, Depends(database)]
Staff = Annotated[ShopStaff | None, Depends(signed_staff)]


class StrictPayload(BaseModel):
    """Reject unexpected fields so clients cannot forge status or owner IDs."""

    model_config = ConfigDict(extra="forbid")


class StoreCreate(StrictPayload):
    """Human-edited name and an immutable URL-safe store slug."""

    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=3, max_length=64)


class StoreStateChange(StrictPayload):
    """Allow only the two reversible Store states and an expected prior state."""

    expected_state: Literal["active", "paused"]
    state: Literal["active", "paused"]


class BotCreate(StrictPayload):
    """Register a disabled-by-default logical bot in the specified store."""

    store_id: UUID
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=3, max_length=64)
    platform: Literal["telegram", "bale"]


class BotTokenStage(StrictPayload):
    """Stage an encrypted bot token; never store it in audit or return it."""

    token: str = Field(min_length=24, max_length=512)


class CredentialRevoke(StrictPayload):
    """Identify only an unused secret version for revocation."""

    version: int = Field(ge=1)


def require(staff: ShopStaff | None, permission: str) -> ShopStaff:
    """Authorize the current database role, never a submitted client claim."""
    if staff is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(staff.role, permission)
    return staff


async def commit_safely(db: AsyncSession, *, conflict_code: str) -> None:
    """Map uniqueness races to an opaque client-safe error."""
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise security.SecurityRejected(conflict_code, 409) from None


@router.get("/stores")
async def list_stores(staff: Staff, db: Db) -> dict:
    """List bounded store metadata, including the preserved default store."""
    require(staff, "bots.read")
    snapshot = await db.run_sync(registry.registry_snapshot)
    return {
        "items": snapshot["stores"],
        "default_store_id": snapshot["default_store_id"],
    }


@router.post("/stores", status_code=201)
async def create_store(
    payload: StoreCreate, staff: Staff, db: Db,
) -> dict:
    """Create only a paused store until later catalog isolation is complete."""
    actor = require(staff, "bots.configure")
    try:
        store = await db.run_sync(lambda sync: registry.create_store(
            sync, slug=payload.slug, name=payload.name, actor_id=actor.id,
        ))
    except IntegrityError:
        await db.rollback()
        raise security.SecurityRejected("store_slug_exists", 409) from None
    await commit_safely(db, conflict_code="store_slug_exists")
    return {"ok": True, "store": registry.serialize_store(store)}


@router.post("/stores/{store_id}/state")
async def change_store_state(
    store_id: UUID, payload: StoreStateChange, staff: Staff, db: Db,
) -> dict:
    """Update only the explicitly authorized Store after recent session proof."""
    actor = require(staff, "bots.apply")
    store = await db.run_sync(lambda sync: registry.change_store_state(
        sync, store_id=str(store_id), actor_id=actor.id,
        expected_state=payload.expected_state, state=payload.state,
    ))
    result = registry.serialize_store(store)
    await db.commit()
    return {"ok": True, "store": result}


@router.get("/bot-registry")
async def list_bots(
    staff: Staff, db: Db, store_id: UUID | None = None,
    platform: Literal["telegram", "bale"] | None = None,
    page: int = 1, page_size: int = 50,
) -> dict:
    """Return paginated redacted bots without an artificial 300-bot limit."""
    require(staff, "bots.read")
    return await db.run_sync(lambda sync: registry.registry_snapshot(
        sync, store_id=str(store_id) if store_id else None,
        platform=platform, page=page, page_size=page_size,
    ))


@router.post("/bot-registry", status_code=201)
async def create_bot(
    payload: BotCreate, staff: Staff, db: Db,
) -> dict:
    """Create a draft bot; intentionally never start a receiver."""
    actor = require(staff, "bots.configure")
    bot = await db.run_sync(lambda sync: registry.register_bot(
        sync, store_id=str(payload.store_id),
        platform=payload.platform, slug=payload.slug,
        name=payload.name, actor_id=actor.id,
    ))
    await commit_safely(db, conflict_code="bot_slug_exists")
    result = await db.run_sync(lambda sync: registry.serialize_bot(sync, bot))
    return {"ok": True, "bot": result}


@router.post("/bot-registry/{bot_id}/credentials/stage", status_code=201)
async def stage_bot_credential(
    bot_id: UUID, payload: BotTokenStage,
    staff: Staff, db: Db,
) -> dict:
    """Encrypt and stage; no token is ever echoed or activated."""
    actor = require(staff, "bots.configure")
    result = await db.run_sync(lambda sync: vault.stage_bot_token(
        sync, bot_id=str(bot_id), token=payload.token, actor_id=actor.id,
    ))
    await commit_safely(db, conflict_code="credential_version_conflict")
    return {
        "ok": True,
        "bot_id": str(bot_id),
        "credential_version": result.version,
        "state": "staged",
        "runtime_activated": False,
    }


@router.post("/bot-registry/{bot_id}/credentials/revoke")
async def revoke_bot_credential(
    bot_id: UUID, payload: CredentialRevoke,
    staff: Staff, db: Db,
) -> dict:
    """Revoke only a staged credential; preserve active credentials."""
    actor = require(staff, "bots.configure")
    await db.run_sync(lambda sync: vault.revoke_staged_token(
        sync, bot_id=str(bot_id), version=payload.version,
        actor_id=actor.id,
    ))
    await db.commit()
    return {"ok": True, "state": "revoked"}
