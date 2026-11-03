"""Authenticated Store environment switching and per-user membership APIs.

Store IDs supplied by a browser are only proposed selections. Every endpoint
revalidates grants against the current database and the revocable admin
session. Multiple active Stores are for reads; every mutation has one current
Store, independent of any other signed-in browser/device.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.admin_control_api import Proof, StrictPayload, fresh_proof
from dashboard.next_api import database, signed_staff
from models.shop_staff import ShopStaff
from models.shop_staff_store import ShopStaffStorePreference
from services import shop_admin_security as security
from services import shop_store_context as stores

router = APIRouter(prefix="/internal/admin/v1", tags=["Store Environment"])
Db = Annotated[AsyncSession, Depends(database)]
Actor = Annotated[ShopStaff | None, Depends(signed_staff)]


def require(actor: ShopStaff | None, permission: str) -> ShopStaff:
    """Use only current server-side staff roles for global capabilities."""
    if actor is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(actor.role, permission)
    return actor


def context(request: Request) -> stores.StoreContext:
    """Use the verified middleware scope, never a client-selected header."""
    scope = getattr(request.state, "store_context", None)
    if not isinstance(scope, stores.StoreContext):
        raise security.SecurityRejected("store_access_denied", 403)
    return scope


class StoreSelection(StrictPayload):
    """A complete optimistic concurrency update for one admin device."""

    expected_version: int = Field(ge=1)
    current_store_id: UUID
    active_store_ids: list[UUID] = Field(min_length=1, max_length=32)


class DefaultStoreChange(StrictPayload):
    """A persistent default Store for the next browser login."""

    store_id: UUID
    expected_version: int = Field(ge=0)


class StoreGrant(StrictPayload):
    """One explicit per-user permission; no implicit global Store access."""

    store_id: UUID
    access_level: Literal["viewer", "editor", "manager"]


class StaffStorePermissions(Proof):
    """Whole-set permissions with recent password and MFA verification."""

    grants: list[StoreGrant] = Field(min_length=1, max_length=100)
    default_store_id: UUID | None = None


@router.get("/store-context")
async def read_current_context(
    request: Request, actor: Actor, db: Db,
) -> dict:
    """Return the authorized Store set and current device's active subset."""
    require(actor, "dashboard.read")
    result = context(request).serialize()
    preference = await db.get(ShopStaffStorePreference, actor.id)
    result["preference_version"] = preference.version if preference else 0
    return result


@router.post("/store-context/select")
async def select_active_stores(
    payload: StoreSelection, request: Request, actor: Actor, db: Db,
) -> dict:
    """Switch one session; revocation takes effect on the next request."""
    staff = require(actor, "dashboard.read")
    current = context(request)
    updated = await stores.switch_session(
        db, staff_id=staff.id, session_id=current.session_id,
        expected_version=payload.expected_version,
        current_store_id=str(payload.current_store_id),
        active_store_ids=[str(item) for item in payload.active_store_ids],
    )
    return updated.serialize()


@router.post("/store-context/default")
async def update_own_default_store(
    payload: DefaultStoreChange, actor: Actor, db: Db,
) -> dict:
    """Save an authorized user's default Store without altering other devices."""
    staff = require(actor, "dashboard.read")
    return await stores.save_default(
        db, staff_id=staff.id, store_id=str(payload.store_id),
        expected_version=payload.expected_version,
    )


@router.get("/staff/{member_id}/store-access")
async def read_staff_store_access(
    member_id: int, request: Request, actor: Actor, db: Db,
) -> dict:
    """Present only Stores on which the operator is a Store manager."""
    require(actor, "staff.manage")
    if member_id <= 0:
        raise security.SecurityRejected("staff_not_found", 404)
    return await stores.store_permissions(
        db, member_id=member_id, operator=context(request),
    )


@router.post("/staff/{member_id}/store-access")
async def change_staff_store_access(
    member_id: int, payload: StaffStorePermissions,
    request: Request, actor: Actor, db: Db,
) -> dict:
    """Change another user's grants with fresh MFA and manager membership."""
    staff = require(actor, "staff.manage")
    if member_id <= 0:
        raise security.SecurityRejected("staff_not_found", 404)
    await fresh_proof(db, staff, payload)
    return await stores.update_staff_permissions(
        db, actor=context(request), target_id=member_id,
        grants=[{
            "store_id": str(item.store_id),
            "access_level": item.access_level,
        } for item in payload.grants],
        default_store_id=(
            str(payload.default_store_id)
            if payload.default_store_id is not None else None
        ),
    )
