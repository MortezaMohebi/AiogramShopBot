"""Signed admin API for Telegram Direct, HTTP/SOCKS5 and Worker routes.

The live Telegram token remains in Deployment secrets. Every mutation is
permission checked, newly staged, audited and subject to recent authentication.
"""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from dashboard.admin_control_api import (
    Proof,
    StrictPayload,
    fresh_proof,
    throttle,
)
from dashboard.next_api import database, signed_staff
from models.shop_admin_control import ConnectionChange
from models.shop_bot_profile import ShopBotProfile
from models.shop_staff import ShopStaff
from models.shop_telegram_transport import ShopTelegramTransportChange
from services import shop_admin_security as security
from services import shop_telegram_transport_control as control
from services.shop_telegram_transport import (
    decrypted,
    make_session,
)
from utils.telegram import create_bot
from utils.telegram_rotating_session import RotatingTelegramSession

router = APIRouter(prefix="/internal/admin/v1", tags=["Telegram transport"])
Db = Annotated[AsyncSession, Depends(database)]
Actor = Annotated[ShopStaff | None, Depends(signed_staff)]


def required(staff: ShopStaff | None, permission: str) -> ShopStaff:
    """Authorize through current database role rather than browser claims."""
    if staff is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(staff.role, permission)
    return staff


def live_bot(request: Request):
    """Resolve the in-process, managed Telegram Bot instance only."""
    instance = getattr(request.app.state, "telegram_bot", None)
    if instance is None or not isinstance(
        getattr(instance, "session", None), RotatingTelegramSession,
    ):
        raise security.SecurityRejected("transport_worker_unavailable", 503)
    return instance


async def ensure_receiver_idle(db: AsyncSession) -> None:
    """Prevent changing API route during ambiguous inbound receiver changes."""
    pending = await db.scalar(select(ConnectionChange.id).where(
        ConnectionChange.platform == "telegram",
        ConnectionChange.state.in_(("queued", "applying", "needs_review")),
    ).limit(1))
    if pending is not None:
        raise security.SecurityRejected("connection_change_in_progress", 409)


class TransportStage(StrictPayload):
    """Validate only the necessary transport settings; no bot token field."""

    mode: Literal["direct", "http_proxy", "cloudflare_worker"]
    expected_version: int = Field(ge=1)
    proxy_url: str = Field(default="", max_length=255)
    proxy_username: str = Field(default="", max_length=128)
    proxy_password: str = Field(default="", max_length=256)
    worker_url: str = Field(default="", max_length=255)
    worker_secret: str = Field(default="", max_length=256)


class ChangeReference(StrictPayload):
    """Reference a known opaque operation without supplied transport secrets."""

    change_id: UUID


class TransportRollback(StrictPayload):
    """Stage a known verified previous setting without silently applying it."""

    source_change_id: UUID
    expected_version: int = Field(ge=1)


class TransportApply(Proof):
    """Require owner password and MFA before activating the new API route."""

    change_id: UUID


@router.get("/telegram-transport")
async def transport_settings(staff: Actor, db: Db) -> dict:
    """Show redacted active/staged transport settings and approved endpoints."""
    required(staff, "bots.read")
    return await control.overview(db)


@router.post("/telegram-transport/stage", status_code=201)
async def transport_stage(
    payload: TransportStage, staff: Actor, db: Db,
) -> dict:
    """Stage encrypted changes, leaving the current connection untouched."""
    actor = required(staff, "bots.configure")
    await ensure_receiver_idle(db)
    fields = payload.model_dump(exclude={"expected_version"})
    row = await control.stage(
        db, actor_id=actor.id, values=fields,
        version=payload.expected_version,
    )
    return {"ok": True, "change_id": row.id, "status": row.status}


@router.post("/telegram-transport/rollback", status_code=201)
async def transport_rollback(
    payload: TransportRollback, staff: Actor, db: Db,
) -> dict:
    """Stage historical verified settings; require a separate probe and apply."""
    actor = required(staff, "bots.configure")
    await ensure_receiver_idle(db)
    row = await control.stage_rollback(
        db, actor_id=actor.id,
        source_id=str(payload.source_change_id),
        version=payload.expected_version,
    )
    return {"ok": True, "change_id": row.id, "status": row.status}


@router.post("/telegram-transport/cancel")
async def transport_cancel(
    payload: ChangeReference, staff: Actor, db: Db,
) -> dict:
    """Revoke a pending proposal without touching active sessions."""
    actor = required(staff, "bots.configure")
    await control.cancel(
        db, actor_id=actor.id, change_id=str(payload.change_id),
    )
    return {"ok": True}


@router.post("/telegram-transport/probe")
async def transport_probe(
    payload: ChangeReference, staff: Actor, db: Db,
) -> dict:
    """Test a staged route with getMe, without switching active Bot traffic."""
    required(staff, "bots.configure")
    if not config.TOKEN:
        raise security.SecurityRejected("provider_not_configured", 409)
    await throttle("telegram-transport-probe", 4, 60)
    row = await db.get(
        ShopTelegramTransportChange, str(payload.change_id),
    )
    if row is None or row.status != "pending":
        raise security.SecurityRejected("invalid_operation_state", 409)

    session = None
    started = monotonic()
    try:
        session = make_session(decrypted(row.proposed_ciphertext))
        isolated = create_bot(config.TOKEN, session)
        identity = await asyncio.wait_for(isolated.get_me(), 15)
        profile = await db.get(ShopBotProfile, "telegram")
        if (
            profile and profile.provider_bot_id is not None
            and identity.id != profile.provider_bot_id
        ):
            raise security.SecurityRejected("bot_identity_mismatch", 409)
        return {
            "ok": True, "status": "reachable",
            "verified_bot_id": str(identity.id),
            "round_trip_ms": int((monotonic() - started) * 1000),
            "applied": False,
        }
    except security.SecurityRejected:
        raise
    except Exception:
        raise security.SecurityRejected("transport_probe_failed", 503) from None
    finally:
        if session is not None:
            await session.close()


@router.post("/telegram-transport/apply")
async def transport_apply(
    payload: TransportApply, request: Request, staff: Actor, db: Db,
) -> dict:
    """Reauthenticate, probe via candidate, then hot-switch and commit receipt."""
    actor = required(staff, "bots.apply")
    await throttle("telegram-transport-apply", 3, 60)
    await fresh_proof(db, actor, payload)
    await ensure_receiver_idle(db)
    # A failed apply consumes its fresh MFA proof, avoiding replay.
    return await control.apply(
        db, actor_id=actor.id, change_id=str(payload.change_id),
        bot=live_bot(request),
    )
