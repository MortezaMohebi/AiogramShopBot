"""Authenticated settings and public, non-secret PWA appearance."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.next_api import database, signed_staff
from models.shop_pwa_settings import ShopPwaSettings
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from utils.shop_text import clean_text

router = APIRouter(prefix="/internal/admin/v1", tags=["PWA settings"])
Db = Annotated[AsyncSession, Depends(database)]
Staff = Annotated[ShopStaff | None, Depends(signed_staff)]

DEFAULT = {
    "name": "مدیریت فروشگاه",
    "short_name": "فروشگاه",
    "theme_color": "#146b66",
    "version": 0,
}


class Appearance(BaseModel):
    """Validate bounded, visible installation labels."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=80)
    short_name: str = Field(min_length=2, max_length=24)
    theme_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    expected_version: int = Field(ge=0)


def values(row: ShopPwaSettings | None) -> dict:
    """Expose only public install labels and a revision for icon refresh."""
    return DEFAULT.copy() if row is None else {
        "name": row.name, "short_name": row.short_name,
        "theme_color": row.theme_color, "version": row.version,
    }


@router.get("/pwa-settings")
async def get_appearance(staff: Staff, db: Db) -> dict:
    """Read deployment appearance from the authenticated dashboard."""
    if staff is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(staff.role, "settings.manage")
    return values(await db.get(ShopPwaSettings, 1))


@router.patch("/pwa-settings")
async def save_appearance(payload: Appearance, request: Request, staff: Staff, db: Db) -> dict:
    """Save labels with an optimistic revision and a recent admin session."""
    if staff is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(staff.role, "settings.manage")
    session = await db.run_sync(lambda sync: security.validate_session(
        sync, staff, request.headers.get("x-shop-session", ""),
    ))
    security.require_recent(session)
    name = clean_text(payload.name)
    short_name = clean_text(payload.short_name)
    if (not 2 <= len(name) <= 80 or not 2 <= len(short_name) <= 24
        or not re.search(r"\w", name, re.UNICODE)):
        raise security.SecurityRejected("invalid_request", 422)
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy import text
        await db.execute(text("SELECT pg_advisory_xact_lock(90211039)"))
    row = await db.get(ShopPwaSettings, 1, with_for_update=True)
    if (row.version if row else 0) != payload.expected_version:
        raise security.SecurityRejected("configuration_changed", 409)
    if row is None:
        row = ShopPwaSettings(id=1, name=name, short_name=short_name,
                              theme_color=payload.theme_color.lower(), version=1)
        db.add(row)
    else:
        row.name = name
        row.short_name = short_name
        row.theme_color = payload.theme_color.lower()
        row.version += 1
    await db.commit()
    return values(row)
