"""Server-authorized payment-method registry; no merchant secrets in JSON."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from dashboard.next_api import database, signed_staff
from models.shop_payment_rail import ShopPaymentRail
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services.shop_payment_rails import SUPPORTED, list_rails
from services.shop_channel_features import get_features

router = APIRouter(prefix="/internal/admin/v1", tags=["Payment controls"])
Db = Annotated[AsyncSession, Depends(database)]
Actor = Annotated[ShopStaff | None, Depends(signed_staff)]


def authorize(staff: ShopStaff | None) -> ShopStaff:
    """Permit only administrators who may change merchant checkout settings."""
    if staff is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(staff.role, "settings.manage")
    return staff


def runtime_ready(platform: str, rail_type: str) -> bool:
    """Never advertise an unconfigured external payment rail as usable."""
    if rail_type == "store_credit":
        return True
    if platform == "bale" and rail_type == "bale_wallet":
        return bool(
            config.BALE_WALLET_CHECKOUT_ENABLED
            and config.BALE_WALLET_PROVIDER_TOKEN
        )
    if platform == "telegram" and rail_type == "telegram_stars":
        return bool(config.TELEGRAM_STARS_CHECKOUT_ENABLED)
    if platform == "telegram" and rail_type == "telegram_fiat":
        return bool(
            config.TELEGRAM_FIAT_CHECKOUT_ENABLED
            and config.TELEGRAM_FIAT_PROVIDER_TOKEN
            and config.TELEGRAM_IRR_MINOR_MULTIPLIER > 0
        )
    return False


class PaymentRail( BaseModel):
    """Named supported checkout rail without accepting custom provider code."""

    model_config = ConfigDict(extra="forbid")
    platform: Literal["telegram", "bale"]
    rail_type: Literal[
        "store_credit", "telegram_fiat", "telegram_stars", "bale_wallet",
    ]
    display_name: str = Field(min_length=1, max_length=80)
    enabled: bool


class PaymentRailUpdate(BaseModel):
    """A full, atomic policy update; cannot silently disable other rails."""

    model_config = ConfigDict(extra="forbid")
    items: list[PaymentRail] = Field(min_length=5, max_length=5)


@router.get("/payment-rails")
async def get_payment_rails(staff: Actor, db: Db) -> dict:
    """Read configured labels and real environment capabilities separately."""
    authorize(staff)
    rows = await list_rails(db)
    for row in rows:
        ready = runtime_ready(row["platform"], row["rail_type"])
        if row["rail_type"] == "store_credit":
            features = await get_features(db, row["platform"])
            ready = ready and features.store_credit_enabled
        row["runtime_ready"] = ready
        row["effective_enabled"] = row["enabled"] and ready
    return {"items": rows}


@router.post("/payment-rails")
async def update_payment_rails(
    payload: PaymentRailUpdate, staff: Actor, db: Db,
) -> dict:
    """Create or toggle only known wallet methods, preserving all ledgers."""
    actor = authorize(staff)
    expected = {
        (platform, method) for platform, methods in SUPPORTED.items()
        for method in methods
    }
    incoming = {(item.platform, item.rail_type) for item in payload.items}
    if incoming != expected:
        raise security.SecurityRejected("invalid_request", 422)
    # Every supported method must be present exactly once.
    if len(incoming) != len(payload.items):
        raise security.SecurityRejected("invalid_request", 422)
    for item in payload.items:
        name = item.display_name.strip()
        if not name or len(name) > 80:
            raise security.SecurityRejected("invalid_request", 422)
        row = await db.scalar(select(ShopPaymentRail).where(
            ShopPaymentRail.platform == item.platform,
            ShopPaymentRail.rail_type == item.rail_type,
        ).with_for_update())
        if row is None:
            row = ShopPaymentRail(
                platform=item.platform, rail_type=item.rail_type,
            )
            db.add(row)
        row.display_name = name
        row.enabled = item.enabled
        row.changed_by = actor.id

    await db.run_sync(lambda sync: security.audit(
        sync, actor.id, "settings.payment_rails_changed",
    ))
    await db.commit()
    return {"ok": True}
