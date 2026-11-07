"""Signed superadmin API for independent bot receiver activation and state.

New bots require a verified staged credential, safe per-bot webhook ownership,
an authenticated administrator, an active shop and an opt-in runtime flag.
No credential, webhook authenticator, or live endpoint URL is returned.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

import config
from dashboard.admin_control_api import StrictPayload, throttle
from dashboard.next_api import database, signed_staff
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_multibot_receiver_control as control

router = APIRouter(prefix="/internal/admin/v1", tags=["Multi-Bot Receivers"])
Db = Annotated[AsyncSession, Depends(database)]
Staff = Annotated[ShopStaff | None, Depends(signed_staff)]


def require(staff: ShopStaff | None, permission: str) -> ShopStaff:
    """Check the current database role rather than browser claims."""
    if staff is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(staff.role, permission)
    return staff


class ReceiverStage(StrictPayload):
    """Choose only one safe provider receiver mode per verified bot."""

    mode: Literal["webhook", "polling"]


class ReceiverApply(StrictPayload):
    """Bind activation to the staged revision and authenticated administrator."""

    expected_version: int = Field(ge=1)


@router.get("/bot-registry/{bot_id}/receiver")
async def receiver_info(
    bot_id: UUID, request: Request, staff: Staff, db: Db,
) -> dict:
    """Return non-secret receiver state and actual activation prerequisites."""
    require(staff, "bots.read")
    snapshot = await control.receiver_snapshot(db, str(bot_id))
    supervisor = getattr(request.app.state, "multi_bot_supervisor", None)
    return {
        **snapshot,
        "runtime_enabled": bool(config.MULTIBOT_V2_RUNTIME_ENABLED),
        "worker_ready": bool(
            supervisor is not None and supervisor.owns_lease
        ),
    }


@router.post("/bot-registry/{bot_id}/receiver/stage", status_code=201)
async def stage_receiver(
    bot_id: UUID, payload: ReceiverStage, staff: Staff, db: Db,
) -> dict:
    """Stage an opaque binding and encrypted webhook secret without network I/O."""
    actor = require(staff, "bots.configure")
    return await control.stage_receiver(
        db, bot_id=str(bot_id), actor_id=actor.id,
        mode=payload.mode,
    )


@router.post("/bot-registry/{bot_id}/receiver/activate")
async def activate_receiver(
    bot_id: UUID, payload: ReceiverApply, request: Request,
    staff: Staff, db: Db,
) -> dict:
    """Apply the verified draft's receiver under an authorized session and lease."""
    actor = require(staff, "bots.apply")
    await throttle("multibot-activate:" + str(actor.id), 3, 60)
    supervisor = getattr(request.app.state, "multi_bot_supervisor", None)
    return await control.activate_receiver(
        db, bot_id=str(bot_id), actor_id=actor.id,
        expected_version=payload.expected_version,
        supervisor=supervisor,
    )
