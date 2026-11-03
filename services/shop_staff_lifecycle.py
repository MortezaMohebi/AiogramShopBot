"""Transactional one-time staff enrollment and recovery operations.

Every operation uses an existing SQLAlchemy transaction. Callers commit on
success or roll back on failure. Passwords and raw capability links must
never appear in audit logs, database records or application logs.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.shop_staff import ShopStaff
from models.shop_staff_security import (
    ShopPasswordPolicy,
    ShopStaffInvitation,
    ShopStaffPasswordReset,
)
from services import shop_admin_security as security

USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{2,79}\Z")
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}\Z")
ROLES = frozenset(security.ROLE_PERMISSIONS)
INVITE_LIFETIME = timedelta(hours=48)
RESET_LIFETIME = timedelta(minutes=30)


def policy_for(db: Session, *, lock: bool = False) -> ShopPasswordPolicy:
    """Read the active policy or supply secure defaults without creating rows."""
    stmt = select(ShopPasswordPolicy).where(ShopPasswordPolicy.id == 1)
    if lock:
        stmt = stmt.with_for_update()
    return db.scalar(stmt) or ShopPasswordPolicy(id=1, min_length=14)


def validate_password(db: Session, value: str) -> None:
    """Reject weak passwords according to the latest administrator policy."""
    policy = policy_for(db)
    if (
        not isinstance(value, str)
        or len(value) < policy.min_length
        or len(value) > 256
        or (policy.require_upper and not any(char.isupper() for char in value))
        or (policy.require_lower and not any(char.islower() for char in value))
        or (policy.require_digit and not any(char.isdecimal() for char in value))
        or (policy.require_symbol and not any(not char.isalnum() for char in value))
    ):
        raise security.SecurityRejected("password_policy_failed", 422)


def configure_policy(
    db: Session, actor_id: int, *, min_length: int,
    require_upper: bool, require_lower: bool,
    require_digit: bool, require_symbol: bool,
) -> ShopPasswordPolicy:
    """Persist a validated policy and audit the changed configuration."""
    if not 12 <= min_length <= 64:
        raise security.SecurityRejected("invalid_request", 422)
    policy = policy_for(db, lock=True)
    if policy not in db:
        db.add(policy)
    policy.min_length = min_length
    policy.require_upper = require_upper
    policy.require_lower = require_lower
    policy.require_digit = require_digit
    policy.require_symbol = require_symbol
    security.audit(db, actor_id, "staff.password_policy_updated")
    db.flush()
    return policy


def _token() -> tuple[str, str]:
    """Generate 256 random bits; return the bearer and stored SHA-256 digest."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode("ascii")).hexdigest()


def issue_invitation(
    db: Session, actor_id: int, username: str, role: str,
    *, now: datetime | None = None,
) -> tuple[ShopStaffInvitation, str]:
    """Issue a new invitation, revoking any outstanding one for the username."""
    instant = security.clock(now)
    normalized = username.strip().casefold()
    if not USERNAME_RE.fullmatch(normalized) or role not in ROLES:
        raise security.SecurityRejected("invalid_request", 422)
    if db.scalar(select(ShopStaff.id).where(ShopStaff.username == normalized)):
        raise security.SecurityRejected("staff_username_exists", 409)
    pending = db.scalars(select(ShopStaffInvitation).where(
        ShopStaffInvitation.username == normalized,
        ShopStaffInvitation.accepted_at.is_(None),
        ShopStaffInvitation.cancelled_at.is_(None),
    ).with_for_update()).all()
    for old in pending:
        old.cancelled_at = instant
    raw, digest = _token()
    item = ShopStaffInvitation(
        id=str(uuid4()), token_hash=digest, username=normalized,
        role=role, created_by=actor_id, created_at=instant,
        expires_at=instant + INVITE_LIFETIME,
    )
    db.add(item)
    security.audit(db, actor_id, "staff.invitation_issued", item.id, now=instant)
    db.flush()
    return item, raw


def cancel_invitation(
    db: Session, actor_id: int, item_id: str, *, now: datetime | None = None,
) -> None:
    """Revoke a pending invitation before it can be accepted."""
    item = db.scalar(select(ShopStaffInvitation).where(
        ShopStaffInvitation.id == item_id,
    ).with_for_update())
    if item is None or item.accepted_at is not None:
        raise security.SecurityRejected("invitation_not_found", 404)
    if item.cancelled_at is None:
        item.cancelled_at = security.clock(now)
        security.audit(db, actor_id, "staff.invitation_cancelled", item.id, now=now)


def issue_reset(
    db: Session, actor_id: int, staff_id: int,
    *, now: datetime | None = None,
) -> tuple[ShopStaffPasswordReset, str]:
    """Revoke old recovery links; never let an administrator set the password."""
    instant = security.clock(now)
    target = db.scalar(select(ShopStaff).where(
        ShopStaff.id == staff_id,
    ).with_for_update())
    if target is None or not target.is_active:
        raise security.SecurityRejected("staff_not_found", 404)
    pending = db.scalars(select(ShopStaffPasswordReset).where(
        ShopStaffPasswordReset.staff_id == staff_id,
        ShopStaffPasswordReset.used_at.is_(None),
        ShopStaffPasswordReset.cancelled_at.is_(None),
    ).with_for_update()).all()
    for old in pending:
        old.cancelled_at = instant
    raw, digest = _token()
    row = ShopStaffPasswordReset(
        id=str(uuid4()), token_hash=digest, staff_id=staff_id,
        created_by=actor_id, created_at=instant,
        expires_at=instant + RESET_LIFETIME,
    )
    db.add(row)
    security.audit(db, actor_id, "staff.password_reset_issued", row.id, now=instant)
    db.flush()
    return row, raw


def redeem(
    db: Session, kind: str, token: str, password_hash: str, password: str,
    *, now: datetime | None = None,
) -> None:
    """Consume a capability once, then provision or rotate a staff password."""
    instant = security.clock(now)
    if kind not in {"invite", "reset"} or not TOKEN_RE.fullmatch(token):
        raise security.SecurityRejected("invalid_link", 410)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    if kind == "invite":
        item = db.scalar(select(ShopStaffInvitation).where(
            ShopStaffInvitation.token_hash == digest,
        ).with_for_update())
        if (
            item is None or item.accepted_at is not None
            or item.cancelled_at is not None
            or security.utc(item.expires_at) <= instant
        ):
            raise security.SecurityRejected("invalid_link", 410)
        if db.scalar(select(ShopStaff.id).where(ShopStaff.username == item.username)):
            raise security.SecurityRejected("invalid_link", 410)
        validate_password(db, password)
        member = ShopStaff(
            username=item.username, password_hash=password_hash,
            role=item.role, is_active=True, session_version=1,
        )
        db.add(member)
        db.flush()
        item.accepted_at = instant
        security.audit(db, member.id, "staff.invitation_accepted", item.id, now=instant)
    else:
        item = db.scalar(select(ShopStaffPasswordReset).where(
            ShopStaffPasswordReset.token_hash == digest,
        ).with_for_update())
        if (
            item is None or item.used_at is not None
            or item.cancelled_at is not None
            or security.utc(item.expires_at) <= instant
        ):
            raise security.SecurityRejected("invalid_link", 410)
        member = db.scalar(select(ShopStaff).where(
            ShopStaff.id == item.staff_id,
        ).with_for_update())
        if member is None or not member.is_active:
            raise security.SecurityRejected("invalid_link", 410)
        validate_password(db, password)
        member.password_hash = password_hash
        member.session_version += 1
        security.revoke_others(db, member.id, None, now=instant)
        item.used_at = instant
        security.audit(db, member.id, "staff.password_reset_consumed", item.id, now=instant)
    # Do not return a session: sensitive roles must enroll/prove their own MFA.


def serialize_policy(policy: ShopPasswordPolicy) -> dict:
    """Expose public constraints without disclosing private credentials."""
    return {
        "min_length": policy.min_length,
        "require_upper": policy.require_upper,
        "require_lower": policy.require_lower,
        "require_digit": policy.require_digit,
        "require_symbol": policy.require_symbol,
    }


def invitation_status(item: ShopStaffInvitation, *, now=None) -> str:
    """Derive status from immutable outcomes and the current expiry clock."""
    if item.accepted_at is not None:
        return "accepted"
    if item.cancelled_at is not None:
        return "cancelled"
    if security.utc(item.expires_at) <= security.clock(now):
        return "expired"
    return "pending"
