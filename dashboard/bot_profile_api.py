"""Authenticated bot profiles, receiver diagnostics and identity verification.

Credentials remain in deployment secrets. This API never accepts or exposes
active provider tokens and never registers/removes a webhook implicitly.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from dashboard.next_api import database, signed_staff
from models.shop_admin_control import ConnectionChange, ConnectionConfig
from models.shop_bot_profile import ShopBotProfile
from models.shop_delivery import ShopInboundUpdate
from models.shop_engagement import ShopBroadcastWorkerHeartbeat
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_bot_profiles as profiles
from services.shop_telegram_transport import decrypted
from models.shop_telegram_transport import ShopTelegramTransport

router = APIRouter(prefix="/internal/admin/v1", tags=["Bot operations"])
Db = Annotated[AsyncSession, Depends(database)]
Actor = Annotated[ShopStaff | None, Depends(signed_staff)]


def require(actor: ShopStaff | None, permission: str = "bots.read") -> ShopStaff:
    """Only the live database role grants bot configuration permissions."""
    if actor is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(actor.role, permission)
    return actor


class BotProfilePatch(BaseModel):
    """Strict bot settings with no credential, URL or webhook secret input."""

    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(max_length=120)
    owner_staff_id: int | None = Field(default=None, gt=0)
    environment: Literal["codespaces", "staging", "production"] = "staging"
    maintenance_enabled: bool
    request_timeout_seconds: int = Field(ge=5, le=60)
    poll_timeout_seconds: int = Field(ge=0, le=30)
    allowed_updates: list[str] = Field(max_length=5)


@router.get("/bot-profiles")
async def bot_profiles(actor: Actor, db: Db) -> dict:
    """Read two non-secret bot profiles plus their actual receiver mode."""
    require(actor)
    modes = {
        row.platform: row for row in (
            await db.scalars(select(ConnectionConfig))
        ).all()
    }
    active_transport = await db.get(ShopTelegramTransport, 1)
    telegram_transport_mode = (
        decrypted(active_transport.config_ciphertext).mode
        if active_transport else config.TELEGRAM_API_MODE
    )
    result = []
    for platform in profiles.SUPPORTED_PLATFORMS:
        options = await profiles.get_bot_options(db, platform)
        item = profiles.safe_data(options)
        config_mode = modes.get(platform)
        item["receiver_mode"] = config_mode.mode if config_mode else (
            config.TELEGRAM_UPDATE_MODE if platform == "telegram" else "webhook"
        )
        item["receiver_version"] = config_mode.version if config_mode else 1
        item["transport_active"] = (
            telegram_transport_mode if platform == "telegram" else "direct"
        )
        item["credential_configured"] = bool(
            config.TOKEN if platform == "telegram" else config.BALE_BOT_TOKEN
        )
        result.append(item)
    return {"items": result}


@router.post("/bot-profiles/{platform}")
async def update_bot_profile(
    platform: Literal["telegram", "bale"],
    payload: BotProfilePatch, actor: Actor, db: Db,
) -> dict:
    """Commit safe settings atomically without touching active API tokens."""
    member = require(actor, "bots.configure")
    if not payload.display_name.strip() and payload.display_name:
        raise security.SecurityRejected("invalid_request", 422)
    try:
        updates = profiles.validate_allowed_updates(payload.allowed_updates)
    except ValueError:
        raise security.SecurityRejected("invalid_request", 422) from None

    if payload.owner_staff_id is not None:
        owner = await db.get(ShopStaff, payload.owner_staff_id)
        if owner is None or not owner.is_active:
            raise security.SecurityRejected("staff_not_found", 404)
    record = await db.scalar(select(ShopBotProfile).where(
        ShopBotProfile.platform == platform,
    ).with_for_update())
    if record is None:
        record = ShopBotProfile(platform=platform)
        db.add(record)
    record.display_name = payload.display_name.strip()
    record.owner_staff_id = payload.owner_staff_id
    record.environment = payload.environment
    record.maintenance_enabled = payload.maintenance_enabled
    record.request_timeout_seconds = payload.request_timeout_seconds
    record.poll_timeout_seconds = payload.poll_timeout_seconds
    record.allowed_updates_json = json.dumps(list(updates), separators=(",", ":"))
    await db.run_sync(lambda sync: security.audit(
        sync, member.id, "bots.profile_updated", platform,
    ))
    await db.commit()
    return {"ok": True}


@router.post("/bot-profiles/{platform}/verify")
async def verify_bot_identity(
    platform: Literal["telegram", "bale"],
    actor: Actor, db: Db, request: Request,
) -> dict:
    """Verify the currently deployed credential with getMe; fail on bot swap."""
    member = require(actor, "bots.configure")
    from dashboard.admin_control_api import throttle

    await throttle("bot-verify:" + platform, 3, 60)
    if platform == "telegram":
        if not config.TOKEN:
            raise security.SecurityRejected("provider_not_configured", 409)
        # Verify the live managed session, not stale Deployment-only ENV.
        bot = getattr(request.app.state, "telegram_bot", None)
        if bot is None:
            raise security.SecurityRejected("transport_worker_unavailable", 503)
        try:
            info = await asyncio.wait_for(bot.get_me(), timeout=10)
            provider_id, username = info.id, info.username
        except Exception:
            raise security.SecurityRejected("provider_state_unavailable", 503) from None
    else:
        if not config.BALE_BOT_TOKEN:
            raise security.SecurityRejected("provider_not_configured", 409)
        from aiohttp import ClientSession, ClientTimeout
        from channels.bale import BaleTransport

        try:
            async with ClientSession(
                timeout=ClientTimeout(total=10), trust_env=False,
            ) as http:
                info = await BaleTransport(
                    config.BALE_BOT_TOKEN, http,
                )._call("getMe", {})
            if not isinstance(info, dict):
                raise ValueError("Invalid provider identity")
            provider_id = info.get("id")
            username = info.get("username")
        except Exception:
            raise security.SecurityRejected("provider_state_unavailable", 503) from None

    if (
        type(provider_id) is not int or provider_id < 1
        or (username is not None and not isinstance(username, str))
    ):
        raise security.SecurityRejected("provider_state_unavailable", 503)

    record = await db.scalar(select(ShopBotProfile).where(
        ShopBotProfile.platform == platform,
    ).with_for_update())
    if record is None:
        record = ShopBotProfile(platform=platform)
        db.add(record)
    elif record.provider_bot_id is not None and record.provider_bot_id != provider_id:
        # Never interpret a different bot token as a routine credential rotate.
        raise security.SecurityRejected("bot_identity_mismatch", 409)
    record.provider_bot_id = provider_id
    record.provider_username = (username or "")[:255] or None
    record.verified_at = datetime.now(timezone.utc)
    await db.run_sync(lambda sync: security.audit(
        sync, member.id, "bots.identity_verified", platform,
    ))
    await db.commit()
    return {
        "ok": True, "platform": platform,
        "provider_bot_id": str(provider_id),
        "username": record.provider_username,
    }


@router.get("/bot-profiles/health")
async def bot_health(actor: Actor, db: Db) -> dict:
    """Layered DB-level receiver/processing/worker health without fake uptime."""
    require(actor)
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=1)
    receiver_configs = {
        row.platform: row for row in (
            await db.scalars(select(ConnectionConfig))
        ).all()
    }
    heartbeat = await db.scalar(select(func.max(
        ShopBroadcastWorkerHeartbeat.last_seen_at
    )))
    result = []
    for platform in profiles.SUPPORTED_PLATFORMS:
        waiting = int(await db.scalar(
            select(func.count()).select_from(ShopInboundUpdate).where(
                ShopInboundUpdate.platform == platform,
                ShopInboundUpdate.status == "processing",
                ShopInboundUpdate.received_at >= since,
            )
        ) or 0)
        needs_review = int(await db.scalar(
            select(func.count()).select_from(ShopInboundUpdate).where(
                ShopInboundUpdate.platform == platform,
                ShopInboundUpdate.status == "needs_review",
                ShopInboundUpdate.received_at >= since,
            )
        ) or 0)
        latest = await db.scalar(select(func.max(
            ShopInboundUpdate.received_at
        )).where(ShopInboundUpdate.platform == platform))
        changes = int(await db.scalar(
            select(func.count()).select_from(ConnectionChange).where(
                ConnectionChange.platform == platform,
                ConnectionChange.state.in_(("queued", "applying", "needs_review")),
            )
        ) or 0)
        config_row = receiver_configs.get(platform)
        result.append({
            "platform": platform,
            "credential_configured": bool(
                config.TOKEN if platform == "telegram" else config.BALE_BOT_TOKEN
            ),
            "provider_api_health": "not_probed",
            "receiver_mode": config_row.mode if config_row else "unknown",
            "receiver_last_verified_at": (
                config_row.verified_at.isoformat()
                if config_row and config_row.verified_at else None
            ),
            "processing_last_seen_at": latest.isoformat() if latest else None,
            "processing_inflight_last_hour": waiting,
            "processing_needs_review_last_hour": needs_review,
            "receiver_pending_changes": changes,
            "broadcast_worker_last_seen_at": heartbeat.isoformat() if heartbeat else None,
        })
    return {"items": result}
