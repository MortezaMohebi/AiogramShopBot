"""Signed per-bot settings, state, verification and evidence-based health.

All endpoints are server-owned, permission-checked and require a recent
authenticated session for mutations. They do not start newly drafted bots.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from dashboard.admin_control_api import throttle
from dashboard.next_api import database, signed_staff
from models.shop_bot_operations import ShopBotOperations
from models.shop_delivery import ShopInboundUpdate
from models.shop_multibot import ShopBot, ShopBotRegistryEvent
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_bot_operations as operations
from services import shop_bot_registry as registry
from services import shop_bot_verification as verification
from services.shop_media_delivery import bot_fingerprint

router = APIRouter(prefix="/internal/admin/v1", tags=["Multi-bot management"])
Db = Annotated[AsyncSession, Depends(database)]
Actor = Annotated[ShopStaff | None, Depends(signed_staff)]


def required(actor: ShopStaff | None, permission: str) -> ShopStaff:
    """Authorize against the live role, never browser-supplied permissions."""
    if actor is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(actor.role, permission)
    return actor


class StrictPayload(BaseModel):
    """Reject undeclared fields that could affect provider or billing state."""

    model_config = ConfigDict(extra="forbid")


class BotSettings(StrictPayload):
    """Non-secret name, ownership, environment and bot-facing help text."""

    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=160)
    owner_staff_id: int | None = Field(default=None, gt=0)
    environment: Literal["codespaces", "staging", "production"] = "staging"
    welcome_message: str | None = Field(default=None, max_length=4096)
    maintenance_message: str | None = Field(default=None, max_length=4096)
    support_url: str = Field(default="", max_length=500)


class BotStateUpdate(StrictPayload):
    """A bounded state change without any webhook or token mutation."""

    expected_version: int = Field(ge=1)
    state: Literal["active", "maintenance", "paused", "disabled"]
    reason: str = Field(default="", max_length=500)


class BotIdentityVerification(StrictPayload):
    """Optional staged credential version; None resolves current legacy only."""

    version: int | None = Field(default=None, ge=1)


async def bot_health_data(db: AsyncSession, bot: ShopBot) -> dict:
    """Distinguish verified identity from actual per-bot receiver observations."""
    operational = await db.get(ShopBotOperations, bot.id)
    target_state = (
        operational.desired_state if operational is not None
        else "active" if bot.runtime_owner == "legacy" else "disabled"
    )
    result = {
        "bot_id": bot.id,
        "runtime_owner": bot.runtime_owner,
        "runtime_ready": bot.runtime_owner == "legacy",
        "desired_state": target_state,
        "provider_api": "not_probed",
        "verified_identity_at": (
            bot.verified_at.isoformat() if bot.verified_at else None
        ),
        "receiver_status": (
            "legacy_receiver" if bot.runtime_owner == "legacy"
            else "not_installed"
        ),
        "received_last_at": None,
        "processing_last_hour": 0,
        "needs_review_last_hour": 0,
        "has_live_credential": bool(bot.credential_version),
    }
    if bot.runtime_owner != "legacy":
        return result

    token = (
        config.TOKEN if bot.platform == "telegram"
        else config.BALE_BOT_TOKEN
    )
    if not token:
        result["receiver_status"] = "credential_missing"
        result["has_live_credential"] = False
        return result

    scope = (
        ShopInboundUpdate.platform == bot.platform,
        ShopInboundUpdate.bot_fingerprint == bot_fingerprint(token),
    )
    since = security.clock() - timedelta(hours=1)
    last_seen = await db.scalar(select(func.max(
        ShopInboundUpdate.received_at,
    )).where(*scope))
    counts = (await db.execute(
        select(ShopInboundUpdate.status, func.count()).where(
            *scope,
            ShopInboundUpdate.received_at >= since,
            ShopInboundUpdate.status.in_(("processing", "needs_review")),
        ).group_by(ShopInboundUpdate.status)
    )).all()
    status_counts = dict(counts)
    result["received_last_at"] = (
        last_seen.isoformat() if last_seen else None
    )
    result["processing_last_hour"] = int(
        status_counts.get("processing", 0)
    )
    result["needs_review_last_hour"] = int(
        status_counts.get("needs_review", 0)
    )
    result["receiver_status"] = (
        "legacy_receiver_paused"
        if target_state in {"maintenance", "paused", "disabled"}
        else "legacy_receiver"
    )
    return result


@router.get("/bot-registry/{bot_id}")
async def read_bot(
    bot_id: UUID, actor: Actor, db: Db,
) -> dict:
    """Get the safe profile and last 30 audit events for exactly one bot."""
    required(actor, "bots.read")
    bot = await db.get(ShopBot, str(bot_id))
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    detail = await db.run_sync(lambda sync: registry.serialize_bot(sync, bot))
    events = (await db.scalars(select(ShopBotRegistryEvent).where(
        ShopBotRegistryEvent.bot_id == bot.id,
    ).order_by(ShopBotRegistryEvent.created_at.desc()).limit(30))).all()
    return {
        "bot": detail,
        "health": await bot_health_data(db, bot),
        "events": [{
            "id": entry.id,
            "actor_id": entry.actor_id,
            "action": entry.action,
            "credential_version": entry.credential_version,
            "created_at": (
                entry.created_at.isoformat() if entry.created_at else None
            ),
        } for entry in events],
    }


@router.get("/bot-registry/{bot_id}/health")
async def read_bot_health(
    bot_id: UUID, actor: Actor, db: Db,
) -> dict:
    """Return actual DB observations without implying that getMe was probed."""
    required(actor, "bots.read")
    bot = await db.get(ShopBot, str(bot_id))
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    return await bot_health_data(db, bot)


@router.patch("/bot-registry/{bot_id}/settings")
async def edit_bot(
    bot_id: UUID, payload: BotSettings, actor: Actor, db: Db,
) -> dict:
    """Save per-bot preferences atomically; never change verified IDs."""
    member = required(actor, "bots.configure")
    await db.run_sync(lambda sync: operations.update_details(
        sync,
        bot_id=str(bot_id),
        actor_id=member.id,
        **payload.model_dump(),
    ))
    await db.commit()
    return {"ok": True}


@router.post("/bot-registry/{bot_id}/state")
async def change_bot_state(
    bot_id: UUID, payload: BotStateUpdate, actor: Actor, db: Db,
) -> dict:
    """Immediately gate only legacy bot shopping, preserving payment receipts."""
    member = required(actor, "bots.configure")
    state = await db.run_sync(lambda sync: operations.change_state(
        sync, bot_id=str(bot_id),
        actor_id=member.id,
        **payload.model_dump(),
    ))
    await db.commit()
    return {
        "ok": True, "desired_state": state,
        "receiver_mutated": False,
    }


@router.post("/bot-registry/{bot_id}/verify")
async def verify_bot_credential(
    bot_id: UUID, payload: BotIdentityVerification,
    actor: Actor, db: Db,
) -> dict:
    """Probe staged or legacy credential via provider getMe; no activation."""
    member = required(actor, "bots.configure")
    await throttle("registry-verify:" + str(member.id), 4, 60)
    return await verification.verify_bot(
        db, bot_id=str(bot_id), actor_id=member.id,
        version=payload.version,
    )
