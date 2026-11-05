"""Transactional account security shared by FastAPI routes and offline tests.

Call synchronous operations through AsyncSession.run_sync in the async app.
Callers commit or roll back; no function opens an independent transaction.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.shop_admin_control import AdminEvent, AdminProfile, AdminSession

UTC = timezone.utc
IDLE_LIMIT = timedelta(minutes=30)
ABSOLUTE_LIMIT = timedelta(hours=8)
MFA_REQUIRED_ROLES = frozenset({"superadmin", "finance"})
REAUTH_LIMIT = timedelta(minutes=5)
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
BASE_PERMISSIONS = frozenset({"account.manage_self", "dashboard.read", "reports.read", "workflows.read"})
ROLE_PERMISSIONS = {
    "viewer": BASE_PERMISSIONS,
    "content": BASE_PERMISSIONS | {"catalog.read", "catalog.write", "media.manage", "workflows.write"},
    "sales": BASE_PERMISSIONS | {"customers.read", "customers.import", "orders.read", "orders.manage", "shipping.manage", "coupons.manage"},
    "finance": BASE_PERMISSIONS | {"orders.read", "finance.read", "wallet.adjust", "refund.execute", "reports.read"},
    "marketing": BASE_PERMISSIONS | {"campaigns.manage", "broadcast.approve", "coupons.manage", "reports.read"},
}
ALL_PERMISSIONS = frozenset().union(*ROLE_PERMISSIONS.values()) | {
    "staff.manage",
    "settings.manage",
    "bots.read",
    "bots.configure",
    "bots.apply",
    "audit.read",
    "actions.approve",
}
ROLE_PERMISSIONS["superadmin"] = ALL_PERMISSIONS


class SecurityRejected(ValueError):
    """An allowlisted, client-safe rejection; never contains a secret."""

    def __init__(self, code: str, status: int = 403) -> None:
        """Attach the HTTP status for route adapters."""
        super().__init__(code)
        self.code, self.status = code, status


def utc(value: datetime) -> datetime:
    """Normalize SQLite test timestamps and PostgreSQL aware timestamps."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def clock(now: datetime | None = None) -> datetime:
    """Return a UTC instant, injectable for deterministic expiry tests."""
    return utc(now) if now else datetime.now(UTC)


def has_permission(role: str, permission: str) -> bool:
    """Deny unknown roles and unknown permissions, including for superadmin."""
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def require_permission(role: str, permission: str) -> None:
    """Enforce a named permission using the live database role."""
    if not has_permission(role, permission):
        raise SecurityRejected("permission_denied")


def audit(db: Session, staff_id: int, action: str, target: str = "", *, now=None) -> None:
    """Record only controlled action names and opaque object identifiers."""
    if not re.fullmatch(r"[a-z_.]{1,80}", action):
        raise ValueError("Invalid audit action")
    db.add(AdminEvent(id=str(uuid4()), staff_id=staff_id, action=action,
                      target=target[:80], created_at=clock(now)))


def profile_for(db: Session, staff_id: int, *, lock: bool = True) -> AdminProfile:
    """Read a profile; login/changes serialize on the staff row first."""
    query = select(AdminProfile).where(AdminProfile.staff_id == staff_id)
    if lock:
        query = query.with_for_update()
    profile = db.scalar(query)
    if profile is None:
        profile = AdminProfile(staff_id=staff_id, display_name="", time_zone="Asia/Tehran",
                               last_totp_step=-1, recovery_hashes="[]")
        db.add(profile)
        db.flush()
    return profile


def update_profile(db: Session, staff_id: int, display_name: str, time_zone: str) -> AdminProfile:
    """Validate display preferences without touching login/role fields."""
    if len(display_name) > 120 or len(time_zone) > 80:
        raise SecurityRejected("invalid_request", 422)
    try:
        ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise SecurityRejected("invalid_timezone", 422) from None
    profile = profile_for(db, staff_id)
    profile.display_name, profile.time_zone = display_name.strip(), time_zone
    audit(db, staff_id, "account.profile_changed")
    return profile


def issue_session(db: Session, staff, label: str, *, now=None) -> str:
    """Mint a 256-bit bearer and store only its SHA-256 digest."""
    instant = clock(now)
    token = secrets.token_urlsafe(32)
    # Bound session count without deleting security history.
    active = db.scalars(select(AdminSession).where(
        AdminSession.staff_id == staff.id, AdminSession.revoked_at.is_(None)
    ).order_by(AdminSession.created_at)).all()
    for row in active[:-9] if len(active) >= 10 else []:
        row.revoked_at, row.revoke_reason = instant, "session_limit"
    db.add(AdminSession(
        id=str(uuid4()), token_hash=hashlib.sha256(token.encode()).hexdigest(),
        staff_id=staff.id, version=staff.session_version,
        label=" ".join(label.split())[:160] or "Browser",
        created_at=instant, last_seen_at=instant,
        expires_at=instant + ABSOLUTE_LIMIT, reauthenticated_at=instant,
    ))
    audit(db, staff.id, "session.created", now=instant)
    db.flush()
    return token


def validate_session(db: Session, staff, token: str, *, now=None) -> AdminSession:
    """Reject revocation, inactivity, stale versions and cross-account tokens."""
    instant = clock(now)
    if not TOKEN_RE.fullmatch(token):
        raise SecurityRejected("session_expired", 401)
    row = db.scalar(select(AdminSession).where(
        AdminSession.token_hash == hashlib.sha256(token.encode()).hexdigest()
    ).with_for_update())
    if (row is None or not staff.is_active or row.staff_id != staff.id
            or row.version != staff.session_version or row.revoked_at is not None
            or utc(row.expires_at) <= instant
            or utc(row.last_seen_at) + IDLE_LIMIT <= instant):
        raise SecurityRejected("session_expired", 401)
    if instant > utc(row.last_seen_at):
        row.last_seen_at = instant
    return row


def revoke_session(db: Session, staff_id: int, session_id: str, *, now=None) -> None:
    """Revoke one owned device without permitting session-ID enumeration."""
    row = db.scalar(select(AdminSession).where(
        AdminSession.id == session_id, AdminSession.staff_id == staff_id
    ).with_for_update())
    if row is None:
        raise SecurityRejected("session_not_found", 404)
    if row.revoked_at is None:
        row.revoked_at, row.revoke_reason = clock(now), "user_revoked"
        audit(db, staff_id, "session.revoked", row.id, now=now)


def revoke_others(db: Session, staff_id: int, keep_id: str | None, *, now=None) -> int:
    """Invalidate all other session tokens server-side, retaining audit rows."""
    rows = db.scalars(select(AdminSession).where(
        AdminSession.staff_id == staff_id, AdminSession.revoked_at.is_(None)
    ).with_for_update()).all()
    changed = 0
    for row in rows:
        if row.id != keep_id:
            row.revoked_at, row.revoke_reason = clock(now), "security_change"
            changed += 1
    audit(db, staff_id, "session.others_revoked", now=now)
    return changed


def require_recent(row: AdminSession, *, now=None) -> None:
    """Require explicit recent password/MFA verification for sensitive work."""
    if utc(row.reauthenticated_at) + REAUTH_LIMIT <= clock(now):
        raise SecurityRejected("reauthentication_required")


def cipher() -> Fernet:
    """Use a dedicated deployment key, never a stored password or bot token."""
    key = os.environ.get("SHOP_SECURITY_ENCRYPTION_KEY", "")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError):
        raise SecurityRejected("mfa_not_configured", 503) from None


def totp(secret: str, timestamp: float) -> str:
    """Generate the RFC 6238 SHA-1 six-digit/30-second authenticator code."""
    digest = hmac.new(base64.b32decode(secret, casefold=True),
                      struct.pack(">Q", int(timestamp) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff
    return f"{value % 1_000_000:06d}"


def matching_step(secret: str, code: str, instant: datetime) -> int | None:
    """Accept a narrow clock-skew window, never arbitrary OTP strings."""
    if not re.fullmatch(r"\d{6}", code):
        return None
    step = int(instant.timestamp()) // 30
    for candidate in (step, step - 1, step + 1):
        if hmac.compare_digest(totp(secret, candidate * 30), code):
            return candidate
    return None


def begin_mfa(db: Session, profile: AdminProfile, *, now=None) -> str:
    """Stage an encrypted secret; enrollment is not enabled until confirmed."""
    if profile.mfa_secret:
        raise SecurityRejected("mfa_already_enabled", 409)
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii")
    profile.pending_mfa = cipher().encrypt(secret.encode()).decode()
    profile.pending_until = clock(now) + timedelta(minutes=10)
    audit(db, profile.staff_id, "mfa.enrollment_started", now=now)
    return secret


def confirm_mfa(db: Session, profile: AdminProfile, code: str, *, now=None) -> list[str]:
    """Enable MFA after OTP proof and display recovery codes exactly once."""
    instant = clock(now)
    if (profile.mfa_secret or not profile.pending_mfa or not profile.pending_until
            or utc(profile.pending_until) <= instant):
        raise SecurityRejected("mfa_enrollment_expired", 409)
    try:
        secret = cipher().decrypt(profile.pending_mfa.encode()).decode()
    except InvalidToken:
        raise SecurityRejected("mfa_unavailable", 503) from None
    step = matching_step(secret, code, instant)
    if step is None:
        raise SecurityRejected("invalid_verification", 401)
    recovery = [secrets.token_hex(16) for _ in range(8)]
    profile.mfa_secret, profile.last_totp_step = profile.pending_mfa, step
    profile.pending_mfa, profile.pending_until = None, None
    profile.recovery_hashes = json.dumps([hashlib.sha256(v.encode()).hexdigest() for v in recovery])
    audit(db, profile.staff_id, "mfa.enabled", now=now)
    return recovery


def verify_second_factor(db: Session, profile: AdminProfile, code: str, *, now=None) -> None:
    """Consume a fresh authenticator step or a one-use random recovery code."""
    if not profile.mfa_secret:
        return
    if not code:
        raise SecurityRejected("mfa_required", 428)
    hashes = json.loads(profile.recovery_hashes)
    candidate = hashlib.sha256(code.encode()).hexdigest()
    for stored in hashes:
        if hmac.compare_digest(stored, candidate):
            hashes.remove(stored)
            profile.recovery_hashes = json.dumps(hashes)
            audit(db, profile.staff_id, "mfa.recovery_used", now=now)
            return
    try:
        secret = cipher().decrypt(profile.mfa_secret.encode()).decode()
    except InvalidToken:
        raise SecurityRejected("mfa_unavailable", 503) from None
    step = matching_step(secret, code, clock(now))
    if step is None or step <= profile.last_totp_step:
        raise SecurityRejected("invalid_verification", 401)
    profile.last_totp_step = step


def disable_mfa(db: Session, profile: AdminProfile) -> None:
    """Clear MFA only after the route has performed fresh password/OTP proof."""
    # Role enforcement is performed by the caller while holding its staff row.
    profile.mfa_secret = profile.pending_mfa = profile.pending_until = None
    profile.recovery_hashes, profile.last_totp_step = "[]", -1
    audit(db, profile.staff_id, "mfa.disabled")
