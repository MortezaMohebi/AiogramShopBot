"""Admin API for safe Store-owned units of measure.

Creation and assignment never convert historical stock or paid invoices.
The manager can add conversion units only within one matching category.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.admin_control_api import StrictPayload
from dashboard.next_api import database, signed_staff
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_uom
from services.shop_store_context import StoreContext

router = APIRouter(prefix="/internal/admin/v1", tags=["Store UoM"])
Db = Annotated[AsyncSession, Depends(database)]
Actor = Annotated[ShopStaff | None, Depends(signed_staff)]


class CategoryInput(StrictPayload):
    """Create one category and its nondeletable reference unit together."""

    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    base_code: str = Field(min_length=1, max_length=32)
    base_name: str = Field(min_length=1, max_length=120)
    base_symbol: str = Field(min_length=1, max_length=24)


class UnitInput(StrictPayload):
    """Use integer rational ratios, never floating-point conversion rates."""

    category_id: UUID
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    symbol: str = Field(min_length=1, max_length=24)
    ratio_num: int = Field(ge=1, le=1_000_000_000)
    ratio_den: int = Field(ge=1, le=1_000_000_000)
    rounding: Decimal = Field(default=Decimal("1"), gt=0, le=1_000_000)


def actor_context(
    actor: ShopStaff | None, request: Request, *, write: bool,
) -> StoreContext:
    """Require a signed admin session, capability and Store membership."""
    if actor is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(
        actor.role, "catalog.write" if write else "catalog.read",
    )
    context = getattr(request.state, "store_context", None)
    if not isinstance(context, StoreContext):
        raise security.SecurityRejected("store_access_denied", 403)
    return context


@router.get("/stores/{store_id}/uoms")
async def list_uoms(
    store_id: UUID, request: Request, actor: Actor, db: Db,
) -> dict:
    """Return visible unit categories and units of exactly one active Store."""
    actor_context(actor, request, write=False).require(str(store_id))
    return await shop_uom.list_units(db, store_id=str(store_id))


@router.post("/stores/{store_id}/uom-categories", status_code=201)
async def create_category(
    store_id: UUID, payload: CategoryInput,
    request: Request, actor: Actor, db: Db,
) -> dict:
    """Create the dimension and reference unit as one transaction."""
    actor_context(actor, request, write=True).require(
        str(store_id), manage=True,
    )
    return await shop_uom.create_category(
        db, store_id=str(store_id), **payload.model_dump(),
    )


@router.post("/stores/{store_id}/uoms", status_code=201)
async def create_unit(
    store_id: UUID, payload: UnitInput,
    request: Request, actor: Actor, db: Db,
) -> dict:
    """Create one precisely defined conversion unit in a Store/category."""
    actor_context(actor, request, write=True).require(
        str(store_id), manage=True,
    )
    return await shop_uom.create_unit(
        db, store_id=str(store_id),
        category_id=str(payload.category_id),
        code=payload.code, name=payload.name, symbol=payload.symbol,
        ratio_num=payload.ratio_num, ratio_den=payload.ratio_den,
        rounding=payload.rounding,
    )
