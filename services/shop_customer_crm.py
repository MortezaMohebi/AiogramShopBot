"""Business rules for audited, provider-scoped customer support operations.

Mutations are applied in an existing transaction and never edit historical
order totals, wallet entries, marketing opt-in, or provider identities.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.shop_content import ShopIdentity
from models.shop_customer_crm import (
    ShopCustomerAudit, ShopCustomerNote, ShopCustomerProfile,
)
from services.shop_admin_security import SecurityRejected, clock, utc
from utils.shop_text import clean_text

TAG_RE = re.compile(r"^[^<>\\/\x00-\x1f]{1,32}$")
MAX_TAGS = 12


def tags_from_json(value: str) -> list[str]:
    """Decode tags defensively, without executing database JSON content."""
    try:
        result = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(result, list):
        return []
    return [
        tag for tag in result[:MAX_TAGS]
        if isinstance(tag, str) and TAG_RE.fullmatch(tag)
    ]


def validate_tags(tags: list[str]) -> list[str]:
    """Trim and deduplicate an allowlisted, bounded set of CRM tags."""
    if not isinstance(tags, list) or len(tags) > MAX_TAGS:
        raise SecurityRejected("invalid_request", 422)
    result: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            raise SecurityRejected("invalid_request", 422)
        normalized = clean_text(tag)
        if not TAG_RE.fullmatch(normalized):
            raise SecurityRejected("invalid_request", 422)
        if normalized.casefold() not in {item.casefold() for item in result}:
            result.append(normalized)
    return result


def profile_for(db: Session, identity_id: int) -> ShopCustomerProfile:
    """Get or create the exact platform identity's private CRM profile."""
    record = db.scalar(
        select(ShopCustomerProfile).where(
            ShopCustomerProfile.identity_id == identity_id,
        ).with_for_update()
    )
    if record is None:
        if db.get(ShopIdentity, identity_id) is None:
            raise SecurityRejected("customer_not_found", 404)
        record = ShopCustomerProfile(
            identity_id=identity_id, tags_json="[]", support_status="open",
        )
        db.add(record)
        db.flush()
    return record


def add_note(db: Session, identity_id: int, actor_id: int, content: str) -> None:
    """Store a new immutable internal note and record its author."""
    value = clean_text(content, multiline=True)
    if not 1 <= len(value) <= 4000:
        raise SecurityRejected("invalid_request", 422)
    profile_for(db, identity_id)
    db.add(ShopCustomerNote(
        identity_id=identity_id, actor_id=actor_id, content=value,
    ))
    db.add(ShopCustomerAudit(
        identity_id=identity_id, actor_id=actor_id, action="note_added",
    ))


def update_profile(
    db: Session, identity_id: int, actor_id: int, *,
    tags: list[str], owner_staff_id: int | None, support_status: str,
) -> None:
    """Update tags, assignee and support status; never alter consent flags."""
    if support_status not in {"open", "pending", "resolved"}:
        raise SecurityRejected("invalid_request", 422)
    from models.shop_staff import ShopStaff

    if owner_staff_id is not None:
        staff = db.get(ShopStaff, owner_staff_id)
        if staff is None or not staff.is_active:
            raise SecurityRejected("staff_not_found", 404)
    record = profile_for(db, identity_id)
    record.tags_json = json.dumps(
        validate_tags(tags), ensure_ascii=False, separators=(",", ":"),
    )
    record.owner_staff_id = owner_staff_id
    record.support_status = support_status
    db.add(ShopCustomerAudit(
        identity_id=identity_id, actor_id=actor_id, action="profile_updated",
    ))


def change_restriction(
    db: Session, identity_id: int, actor_id: int, *,
    blocked: bool, reason: str, until: datetime | None, now=None,
) -> None:
    """Apply documented, expiring shop restriction independently of bot bans."""
    instant = clock(now)
    cleaned = reason.strip()
    if blocked and (not 8 <= len(cleaned) <= 500):
        raise SecurityRejected("restriction_reason_required", 422)
    if until is not None:
        if until.tzinfo is None or utc(until) <= instant:
            raise SecurityRejected("invalid_request", 422)
    identity = db.scalar(
        select(ShopIdentity).where(ShopIdentity.id == identity_id)
        .with_for_update()
    )
    if identity is None:
        raise SecurityRejected("customer_not_found", 404)
    record = profile_for(db, identity_id)
    identity.is_blocked = blocked
    record.restriction_reason = cleaned if blocked else None
    record.restriction_until = until if blocked else None
    record.restricted_by = actor_id if blocked else None
    record.restricted_at = instant if blocked else None
    db.add(ShopCustomerAudit(
        identity_id=identity_id, actor_id=actor_id,
        action="restricted" if blocked else "restriction_cleared",
        reason=cleaned if blocked else None,
    ))


def effective_restriction(
    blocked: bool, until: datetime | None, *, now=None,
) -> bool:
    """A restriction without expiry remains active until expressly cleared."""
    if not blocked:
        return False
    return until is None or utc(until) > clock(now)


def audit_export(db: Session, identity_id: int, actor_id: int) -> None:
    """Record an authorized export without logging any customer information."""
    if db.get(ShopIdentity, identity_id) is None:
        raise SecurityRejected("customer_not_found", 404)
    db.add(ShopCustomerAudit(
        identity_id=identity_id, actor_id=actor_id, action="data_exported",
    ))
