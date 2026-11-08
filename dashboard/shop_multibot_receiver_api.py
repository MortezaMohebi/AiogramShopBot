"""Signed superadmin API for independent bot receiver activation and state.

New bots require a verified staged credential, safe per-bot webhook ownership,
an authenticated administrator, an active shop and an opt-in runtime flag.
Receiver snapshots omit secrets. Reading the active webhook URL requires
an explicit request with recent administrator proof.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.admin_control_api import StrictPayload, throttle
from dashboard.next_api import database, signed_staff
from models.shop_multibot_receiver import ShopBotReceiver
from models.shop_staff import ShopStaff
from services.shop_bot_secrets import decrypt_receiver_secret
from services.shop_multibot_webhook import webhook_url
from services.shop_service_controls import service_enabled
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
        "runtime_enabled": bool(service_enabled("receivers")),
        "worker_ready": bool(
            supervisor is not None and supervisor.owns_lease
        ),
    }


@router.post("/bot-registry/{bot_id}/receiver/webhook-url")
async def reveal_webhook_url(bot_id: UUID, staff: Staff, db: Db) -> JSONResponse:
    """Read the configured callback under the signed, recent-auth boundary."""
    require(staff, "bots.apply")
    row = await db.get(ShopBotReceiver, str(bot_id))
    if row is None or row.mode != "webhook" or row.state != "active":
        raise security.SecurityRejected("invalid_operation_state", 409)
    secret = decrypt_receiver_secret(str(bot_id), row.webhook_secret_ciphertext)
    url = webhook_url(row.binding_id, secret)
    if not url:
        raise security.SecurityRejected("webhook_url_invalid", 422)
    return JSONResponse({"url": url}, headers={"Cache-Control": "private, no-store"})


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
