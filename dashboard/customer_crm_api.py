"""Authenticated customer case management over Telegram/Bale scoped identities.

Requests are signed by the Next.js server. All mutations are permission
checked and backed by audited PostgreSQL transactions; no provider API calls
are made from the customer dashboard.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.next_api import database, signed_staff
from models.shop_content import ShopIdentity, ShopOrder
from models.shop_customer_crm import (
    ShopCustomerAudit,
    ShopCustomerConsentEvent,
    ShopCustomerNote,
    ShopCustomerProfile,
    ShopCustomerRetentionPolicy,
)
from models.shop_engagement import ShopWalletAccount, ShopWalletEntry
from models.shop_staff import ShopStaff
from services import shop_customer_crm as crm
from services import shop_admin_security as security

router = APIRouter(prefix="/internal/admin/v1", tags=["Customer CRM"])
Db = Annotated[AsyncSession, Depends(database)]
Actor = Annotated[ShopStaff | None, Depends(signed_staff)]


def require(actor: ShopStaff | None, permission: str = "customers.read") -> ShopStaff:
    """Verify the live staff role, independent of client-side navigation."""
    if actor is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(actor.role, permission)
    return actor


def safe_time(value: datetime | None) -> str | None:
    """Serialize optional timestamps without inventing a timezone."""
    return value.isoformat() if value else None


def basic_profile(
    identity: ShopIdentity, profile: ShopCustomerProfile | None,
) -> dict:
    """Return safe CRM metadata, never provider bearer secrets."""
    return {
        "id": identity.id,
        "platform": identity.platform,
        "user_id": str(identity.platform_user_id),
        "name": identity.first_name,
        "username": identity.username,
        "registered_at": safe_time(identity.registered_at),
        "allow_announcements": identity.allow_announcements,
        "is_blocked": crm.effective_restriction(
            identity.is_blocked,
            profile.restriction_until if profile else None,
        ),
        "restriction_reason": profile.restriction_reason if profile else None,
        "restriction_until": safe_time(profile.restriction_until) if profile else None,
        "bot_blocked_by_customer": True if profile and profile.bot_blocked_at else None,
        "tags": crm.tags_from_json(profile.tags_json) if profile else [],
        "owner_staff_id": profile.owner_staff_id if profile else None,
        "support_status": profile.support_status if profile else "open",
    }


@router.get("/customers")
async def list_customers(
    actor: Actor, db: Db, page: int = 1,
    q: str = "", platform: Literal["all", "telegram", "bale"] = "all",
    restriction: Literal["all", "blocked", "active"] = "all",
    consent: Literal["all", "yes", "no"] = "all",
    owner: int | None = None,
    tag: str = "",
) -> dict:
    """Search and filter 20 identities without merging provider user IDs."""
    require(actor)
    if not 1 <= page <= 100000 or len(q) > 100 or len(tag) > 32 or (
        owner is not None and owner < 1
    ):
        raise security.SecurityRejected("invalid_request", 422)

    conditions = []
    if platform != "all":
        conditions.append(ShopIdentity.platform == platform)
    if consent != "all":
        conditions.append(ShopIdentity.allow_announcements.is_(consent == "yes"))
    if owner is not None:
        conditions.append(ShopCustomerProfile.owner_staff_id == owner)
    if tag.strip():
        checked = crm.validate_tags([tag.strip()])[0]
        conditions.append(ShopCustomerProfile.tags_json.contains(
            json.dumps(checked, ensure_ascii=False),
        ))
    if q.strip():
        needle = q.strip()
        conditions.append(or_(
            ShopIdentity.first_name.ilike(f"%{needle}%"),
            ShopIdentity.username.ilike(f"%{needle}%"),
            cast(ShopIdentity.platform_user_id, String).ilike(f"%{needle}%"),
        ))
    if restriction == "blocked":
        conditions.append(ShopIdentity.is_blocked.is_(True))
        conditions.append(or_(
            ShopCustomerProfile.restriction_until.is_(None),
            ShopCustomerProfile.restriction_until > security.clock(),
        ))
    elif restriction == "active":
        conditions.append(or_(
            ShopIdentity.is_blocked.is_(False),
            ShopCustomerProfile.restriction_until <= security.clock(),
        ))

    statement = (
        select(ShopIdentity, ShopCustomerProfile)
        .outerjoin(
            ShopCustomerProfile,
            ShopCustomerProfile.identity_id == ShopIdentity.id,
        )
    )
    count = (
        select(func.count())
        .select_from(ShopIdentity)
        .outerjoin(
            ShopCustomerProfile,
            ShopCustomerProfile.identity_id == ShopIdentity.id,
        )
    )
    if conditions:
        statement = statement.where(*conditions)
        count = count.where(*conditions)
    total = int(await db.scalar(count) or 0)
    rows = (await db.execute(
        statement.order_by(ShopIdentity.id.desc()).offset(
            (page - 1) * 20,
        ).limit(20)
    )).all()
    return {
        "items": [basic_profile(identity, profile) for identity, profile in rows],
        "total": total,
        "page": page,
        "page_size": 20,
    }


@router.get("/customers/assignees")
async def customer_assignees(actor: Actor, db: Db) -> dict:
    """Return assignable staff identities without leaking credentials."""
    require(actor)
    rows = (await db.scalars(select(ShopStaff).where(
        ShopStaff.is_active.is_(True),
        ShopStaff.role.in_(("superadmin", "sales")),
    ).order_by(ShopStaff.username).limit(250))).all()
    return {"items": [
        {"id": member.id, "username": member.username}
        for member in rows
    ]}


@router.get("/customers/{customer_id}")
async def customer_case(
    customer_id: int, actor: Actor, db: Db,
) -> dict:
    """Assemble one support case with orders, notes, consent, and credit."""
    require(actor)
    if not 1 <= customer_id:
        raise security.SecurityRejected("invalid_request", 422)
    identity = await db.get(ShopIdentity, customer_id)
    if identity is None:
        raise security.SecurityRejected("customer_not_found", 404)
    profile = await db.get(ShopCustomerProfile, identity.id)
    orders = (await db.scalars(select(ShopOrder).where(
        ShopOrder.platform == identity.platform,
        ShopOrder.platform_user_id == identity.platform_user_id,
    ).order_by(ShopOrder.id.desc()).limit(50))).all()
    notes = (await db.scalars(select(ShopCustomerNote).where(
        ShopCustomerNote.identity_id == identity.id,
    ).order_by(ShopCustomerNote.id.desc()).limit(100))).all()
    consent = (await db.scalars(select(ShopCustomerConsentEvent).where(
        ShopCustomerConsentEvent.identity_id == identity.id,
    ).order_by(ShopCustomerConsentEvent.id.desc()).limit(40))).all()
    activity = (await db.scalars(select(ShopCustomerAudit).where(
        ShopCustomerAudit.identity_id == identity.id,
    ).order_by(ShopCustomerAudit.id.desc()).limit(40))).all()
    wallet = await db.scalar(select(ShopWalletAccount).where(
        ShopWalletAccount.identity_id == identity.id,
    ))
    ledger = (await db.scalars(select(ShopWalletEntry).where(
        ShopWalletEntry.account_id == wallet.id,
    ).order_by(ShopWalletEntry.id.desc()).limit(40))).all() if wallet else []

    return {
        "customer": basic_profile(identity, profile),
        "wallet_balance_irr": str(wallet.balance_irr) if wallet else "0",
        "orders": [{
            "id": item.id, "status": item.status,
            "total_irr": str(item.total_irr),
            "provider": item.provider, "created_at": safe_time(item.created_at),
        } for item in orders],
        "notes": [{
            "id": item.id, "actor": item.actor_id, "content": item.content,
            "created_at": safe_time(item.created_at),
        } for item in notes],
        "consent": [{
            "allowed": item.allowed, "source": item.source,
            "topic": item.topic, "created_at": safe_time(item.created_at),
        } for item in consent],
        "activity": [{
            "action": item.action, "actor": item.actor_id,
            "reason": item.reason, "created_at": safe_time(item.created_at),
        } for item in activity],
        "ledger": [{
            "id": item.id, "delta_irr": str(item.delta_irr),
            "balance_after_irr": str(item.balance_after_irr),
            "created_at": safe_time(item.created_at),
            "reason": item.reason,
        } for item in ledger],
    }


class StrictPayload(BaseModel):
    """Reject hidden fields instead of silently updating private data."""

    model_config = ConfigDict(extra="forbid")


class CustomerProfileChange(StrictPayload):
    """Assign follow-up, bounded labels and current support status."""

    tags: list[str] = Field(max_length=12)
    owner_staff_id: int | None = Field(default=None, gt=0)
    support_status: Literal["open", "pending", "resolved"] = "open"


class CustomerNoteChange(StrictPayload):
    """Require a substantive internal case note."""

    content: str = Field(min_length=1, max_length=4000)


class CustomerRestriction(StrictPayload):
    """Document every new block with a reason and optional expiration."""

    blocked: bool
    reason: str = Field(default="", max_length=500)
    until: datetime | None = None


@router.post("/customers/{customer_id}/profile")
async def save_customer_profile(
    customer_id: int, payload: CustomerProfileChange,
    actor: Actor, db: Db,
) -> dict:
    """Save customer follow-up metadata in a single audited transaction."""
    member = require(actor)
    await db.run_sync(lambda sync: crm.update_profile(
        sync, customer_id, member.id, **payload.model_dump(),
    ))
    await db.commit()
    return {"ok": True}


@router.post("/customers/{customer_id}/notes")
async def save_customer_note(
    customer_id: int, payload: CustomerNoteChange,
    actor: Actor, db: Db,
) -> dict:
    """Append a support note; editing history or impersonating staff is denied."""
    member = require(actor)
    await db.run_sync(lambda sync: crm.add_note(
        sync, customer_id, member.id, payload.content,
    ))
    await db.commit()
    return {"ok": True}


@router.post("/customers/{customer_id}/restriction")
async def restrict_customer(
    customer_id: int, payload: CustomerRestriction,
    actor: Actor, db: Db,
) -> dict:
    """Restrict only the shop identity, never the underlying messaging account."""
    member = require(actor)
    await db.run_sync(lambda sync: crm.change_restriction(
        sync, customer_id, member.id,
        blocked=payload.blocked, reason=payload.reason, until=payload.until,
    ))
    await db.commit()
    return {"ok": True}


@router.get("/customers/{customer_id}/export")
async def export_customer(
    customer_id: int, actor: Actor, db: Db,
) -> dict:
    """Export personal customer events under superadmin-only audit permission."""
    member = require(actor, "audit.read")
    case = await customer_case(customer_id, actor, db)
    # Support notes and CRM audit remain private and are not exported as
    # customer-owned content. The financial ledger and orders are included.
    public_customer = dict(case["customer"])
    public_customer.pop("restriction_reason", None)
    public_customer.pop("owner_staff_id", None)
    public_customer.pop("tags", None)
    public_customer.pop("support_status", None)
    payload = {
        "customer": public_customer,
        "orders": case["orders"],
        "ledger": case["ledger"],
        "consent": case["consent"],
        "wallet_balance_irr": case["wallet_balance_irr"],
    }
    await db.run_sync(lambda sync: crm.audit_export(
        sync, customer_id, member.id,
    ))
    await db.commit()
    return {"ok": True, "export": payload}


class RetentionChange(StrictPayload):
    """Validated private case and audit log retention periods."""

    note_retention_days: int = Field(ge=30, le=3650)
    audit_retention_days: int = Field(ge=365, le=3650)


@router.get("/customer-retention")
async def get_retention(actor: Actor, db: Db) -> dict:
    """Describe explicit retention windows without deleting data."""
    require(actor, "audit.read")
    policy = await db.get(ShopCustomerRetentionPolicy, 1)
    return {
        "note_retention_days": policy.note_retention_days if policy else 365,
        "audit_retention_days": policy.audit_retention_days if policy else 730,
    }


@router.post("/customer-retention")
async def set_retention(
    payload: RetentionChange, actor: Actor, db: Db,
) -> dict:
    """Update retention policy; no implicit deletion of financial data."""
    member = require(actor, "audit.read")
    row = await db.get(ShopCustomerRetentionPolicy, 1, with_for_update=True)
    if row is None:
        row = ShopCustomerRetentionPolicy(id=1)
        db.add(row)
    row.note_retention_days = payload.note_retention_days
    row.audit_retention_days = payload.audit_retention_days
    row.updated_by = member.id
    await db.run_sync(lambda sync: security.audit(
        sync, member.id, "settings.customer_retention_updated",
    ))
    await db.commit()
    return {"ok": True}
