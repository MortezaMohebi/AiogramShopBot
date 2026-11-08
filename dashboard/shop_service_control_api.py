"""Signed administrator endpoints for deployment-wide operational controls."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.next_api import database, signed_staff
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_service_controls as controls

router = APIRouter(prefix="/internal/admin/v1", tags=["Operational services"])
Db = Annotated[AsyncSession, Depends(database)]
Staff = Annotated[ShopStaff | None, Depends(signed_staff)]


class ServiceChange(BaseModel):
    """Require a known boolean choice and compare against the observed revision."""

    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool | None
    expected_version: int = Field(ge=0, strict=True)


def _operator(staff: ShopStaff | None) -> ShopStaff:
    """Only administrators with deployment settings authority can use this API."""
    if staff is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(staff.role, "settings.manage")
    return staff


@router.get("/services")
async def list_services(staff: Staff, db: Db) -> dict:
    """List redacted deployment choices and the necessary infrastructure."""
    _operator(staff)
    return {"items": await db.run_sync(controls.describe_controls)}


@router.post("/services/{key}")
async def set_service(
    key: str, payload: ServiceChange, request: Request, staff: Staff, db: Db,
) -> dict:
    """Recheck live administrator proof while serializing the switch write."""
    actor_id = _operator(staff).id

    def change(session):
        actor = _operator(session.scalar(select(ShopStaff).where(
            ShopStaff.id == actor_id,
        ).with_for_update().execution_options(populate_existing=True)))
        row = security.validate_session(
            session, actor, request.headers.get("x-shop-session", ""),
        )
        if row.id != getattr(request.state, "admin_session_id", None):
            raise security.SecurityRejected("session_expired", 401)
        security.require_recent(row)
        return controls.write_override(
            session, key=key, enabled=payload.enabled,
            expected_version=payload.expected_version, actor_id=actor.id,
        )

    result = await db.run_sync(change)
    await db.commit()
    return {"ok": True, **result}
