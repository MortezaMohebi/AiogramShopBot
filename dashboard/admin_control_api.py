"""Authenticated self-service control plane over the existing signed bridge."""
from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from dashboard.next_api import database, signed_staff
from models.shop_staff import ShopStaff
from models.shop_admin_control import AdminEvent, AdminSession, ConnectionChange, ConnectionConfig
from models.shop_staff_security import ShopStaffInvitation, ShopStaffPasswordReset
from models.shop_channel_features import ShopChannelFeature
from services.shop_channel_features import get_features, to_data, PLATFORMS
from services import shop_staff_lifecycle as lifecycle
from services import shop_staff_preferences as staff_preferences
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from services import shop_admin_security as security
from services.shop_mfa_qr import make_mfa_qr_data_uri, make_otpauth_uri
from services.shop_connection_control import stage_change, transition
from utils.utils import hash_password, verify_password

Db = Annotated[AsyncSession, Depends(database)]
Staff = Annotated[ShopStaff | None, Depends(signed_staff)]
router = APIRouter(prefix="/internal/admin/v1")
# Unknown accounts still pay the same password-verification cost.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


class StrictPayload(BaseModel):
    """Reject hidden role/account fields rather than ignoring them."""
    model_config = ConfigDict(extra="forbid")


class Login(StrictPayload):
    """Credentials are confined to the authenticated server-to-server bridge."""
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=1, max_length=256)
    second_factor: str = Field(default="", max_length=64)
    device: str = Field(default="Browser", max_length=160)


class Proof(StrictPayload):
    """Fresh proof, never an English confirmation phrase in lieu of a password."""
    current_password: str = Field(min_length=1, max_length=256)
    second_factor: str = Field(default="", max_length=64)


class PasswordChange(Proof):
    """Preserve all entered password characters, including whitespace."""
    new_password: str = Field(min_length=12, max_length=256)


class ProfileChange(StrictPayload):
    """Only safe personal display preferences; no username or role edits."""
    display_name: str = Field(default="", max_length=120)
    time_zone: str = Field(default="Asia/Tehran", min_length=1, max_length=80)


class PreferencesChange(StrictPayload):
    """Per-user display and non-security work alert preferences."""

    language: Literal["fa", "en"] = "fa"
    calendar: Literal["auto", "jalali", "gregorian"] = "auto"
    notify_orders: bool = True
    notify_campaigns: bool = True
    notify_finance: bool = True
    notify_system: bool = True


class UsernameChange(Proof):
    """Rename only the current authenticated account after recent proof."""

    username: str = Field(min_length=3, max_length=80)


class Code(StrictPayload):
    """A bounded authenticator code for the pending enrollment."""
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class SessionTarget(StrictPayload):
    """Public session identifier, distinct from the secret session bearer."""
    session_id: UUID


class StageChange(StrictPayload):
    """One idempotent change request bound to the intended receiver."""
    platform: Literal["telegram", "bale"]
    mode: Literal["webhook", "polling"]
    idempotency_key: UUID


class ChangeAction(Proof):
    """Applying an external change requires fresh password/MFA proof."""
    operation_id: UUID
    action: Literal["apply", "cancel", "reconcile"]


async def throttle(key: str, limit: int, seconds: int) -> None:
    """Atomically count attempts with a TTL; Redis outages fail closed."""
    from redis.asyncio import Redis
    cache = Redis(host=config.REDIS_HOST, password=config.REDIS_PASSWORD,
                  socket_connect_timeout=2, socket_timeout=2)
    script = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"
    try:
        count = await cache.eval(script, 1, "shop:security:" + key, seconds)
        if count > limit:
            raise HTTPException(429, "temporarily_locked")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "security_service_unavailable") from None
    finally:
        await cache.aclose()


def required(staff: ShopStaff | None, permission="account.manage_self") -> ShopStaff:
    """Authorize live role metadata, never client-supplied role names."""
    if staff is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(staff.role, permission)
    return staff


def own_session(request: Request) -> str:
    """Use only a session identifier established by the security middleware."""
    identifier = getattr(request.state, "admin_session_id", None)
    if not identifier:
        raise security.SecurityRejected("session_expired", 401)
    return identifier


async def fresh_proof(db: AsyncSession, staff: ShopStaff, payload: Proof) -> None:
    """Serialize security changes against password rotation and MFA replay."""
    await throttle("reauth:" + str(staff.id), 8, 60)
    await db.execute(select(ShopStaff.id).where(ShopStaff.id == staff.id).with_for_update())
    await db.refresh(staff)
    if not await asyncio.to_thread(verify_password, payload.current_password, staff.password_hash):
        raise security.SecurityRejected("invalid_credentials", 401)
    def verify(sync):
        profile = security.profile_for(sync, staff.id)
        security.verify_second_factor(sync, profile, payload.second_factor)
    await db.run_sync(verify)


@router.post("/auth/login")
async def login(payload: Login, staff: Staff, db: Db) -> dict:
    """Password/MFA login creates a separately revocable server-side session."""
    if staff is not None:
        raise HTTPException(400, "unexpected_session")
    username = payload.username.strip().casefold()
    name_hash = hashlib.sha256(username.encode()).hexdigest()
    await throttle("login-rate:" + name_hash, 30, 60)
    from redis.asyncio import Redis
    limiter = Redis(host=config.REDIS_HOST, password=config.REDIS_PASSWORD,
                    socket_connect_timeout=2, socket_timeout=2)
    failure_key = "shop:security:login-failure:" + name_hash
    try:
        if int(await limiter.get(failure_key) or 0) >= 10:
            raise HTTPException(429, "temporarily_locked")
        account = await db.scalar(select(ShopStaff).where(
            ShopStaff.username == username, ShopStaff.is_active.is_(True)).with_for_update())
        valid = await asyncio.to_thread(verify_password, payload.password,
                                      account.password_hash if account else _DUMMY_HASH)
        if account is None or not valid:
            await throttle("login-failure:" + name_hash, 10, 600)
            raise security.SecurityRejected("invalid_credentials", 401)
        try:
            def complete(sync):
                profile = security.profile_for(sync, account.id)
                security.verify_second_factor(sync, profile, payload.second_factor)
                return security.issue_session(sync, account, payload.device), bool(profile.mfa_secret)
            token, has_mfa = await db.run_sync(complete)
        except security.SecurityRejected as error:
            if error.status == 401:
                await throttle("login-failure:" + name_hash, 10, 600)
            raise
        await db.commit()
        await limiter.delete(failure_key)
        return {"id": account.id, "username": account.username, "role": account.role,
                "session_version": account.session_version, "session_token": token,
                "mfa_setup_required": account.role in security.MFA_REQUIRED_ROLES
                    and not has_mfa}
    except (security.SecurityRejected, HTTPException):
        raise
    except Exception:
        raise HTTPException(503, "security_service_unavailable") from None
    finally:
        await limiter.aclose()


@router.get("/auth/me")
async def whoami(staff: Staff) -> dict:
    """Return the effective permission set for display; enforcement stays here."""
    member = required(staff)
    return {"id": member.id, "username": member.username, "role": member.role,
            "permissions": sorted(security.ROLE_PERMISSIONS[member.role])}


@router.post("/auth/logout")
async def logout(request: Request, staff: Staff, db: Db) -> dict:
    """Revoke the database session, not merely the local browser cookie."""
    member = required(staff)
    await db.run_sync(lambda sync: security.revoke_session(sync, member.id, own_session(request)))
    await db.commit()
    return {"ok": True}


@router.get("/account")
async def account(request: Request, staff: Staff, db: Db) -> dict:
    """Read self-service information without secret hashes, OTP seeds or tokens."""
    member = required(staff)
    await db.execute(select(ShopStaff.id).where(ShopStaff.id == member.id).with_for_update())
    profile = await db.run_sync(lambda sync: security.profile_for(sync, member.id))
    rows = (await db.scalars(select(AdminSession).where(
        AdminSession.staff_id == member.id).order_by(AdminSession.created_at.desc()).limit(30))).all()
    events = (await db.scalars(select(AdminEvent).where(
        AdminEvent.staff_id == member.id).order_by(AdminEvent.created_at.desc()).limit(30))).all()
    result = {
        "username": member.username, "role": member.role,
        "display_name": profile.display_name, "time_zone": profile.time_zone,
        "mfa_enabled": bool(profile.mfa_secret),
        "mfa_required_by_role": member.role in security.MFA_REQUIRED_ROLES,
        "password_policy": await db.run_sync(lambda sync: lifecycle.serialize_policy(lifecycle.policy_for(sync))),
        "preferences": await db.run_sync(lambda sync: staff_preferences.serialize(
            staff_preferences.for_user(sync, member.id),
        )),
        "permissions": sorted(security.ROLE_PERMISSIONS[member.role]),
        "sessions": [{"id": row.id, "label": row.label,
            "current": row.id == own_session(request), "created_at": row.created_at.isoformat(),
            "last_seen_at": row.last_seen_at.isoformat(), "expires_at": row.expires_at.isoformat(),
            "revoked": row.revoked_at is not None,
            "active": row.revoked_at is None and row.version == member.session_version and security.utc(row.expires_at) > security.clock()
                and security.utc(row.last_seen_at) + security.IDLE_LIMIT > security.clock()} for row in rows],
        "events": [{"id": row.id, "action": row.action,
                    "created_at": row.created_at.isoformat()} for row in events],
    }
    await db.commit()
    return result


@router.post("/account/profile")
async def profile(payload: ProfileChange, staff: Staff, db: Db) -> dict:
    """Save only the current user's display preferences."""
    member = required(staff)
    await db.execute(select(ShopStaff.id).where(ShopStaff.id == member.id).with_for_update())
    await db.run_sync(lambda sync: security.update_profile(sync, member.id, payload.display_name, payload.time_zone))
    await db.commit()
    return {"ok": True}


@router.post("/account/preferences")
async def save_preferences(
    payload: PreferencesChange, staff: Staff, db: Db,
) -> dict:
    """Persist language, calendar and work notifications for the owner."""
    member = required(staff)
    await db.execute(select(ShopStaff.id).where(
        ShopStaff.id == member.id,
    ).with_for_update())
    await db.run_sync(lambda sync: staff_preferences.update(
        sync, member.id, **payload.model_dump(),
    ))
    await db.commit()
    return {"ok": True}


@router.post("/account/username")
async def change_username(
    payload: UsernameChange, staff: Staff, db: Db,
) -> dict:
    """Rename the current staff subject, re-authenticate, and revoke sessions."""
    import re

    member = required(staff)
    name = payload.username.strip().casefold()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,79}", name):
        raise security.SecurityRejected("invalid_request", 422)
    await fresh_proof(db, member, payload)
    if member.username == name:
        raise security.SecurityRejected("username_unchanged", 422)
    member.username = name
    member.session_version += 1
    await db.run_sync(lambda sync: security.revoke_others(
        sync, member.id, None,
    ))
    await db.run_sync(lambda sync: security.audit(
        sync, member.id, "account.username_changed",
    ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise security.SecurityRejected("staff_username_exists", 409) from None
    return {"ok": True, "login_required": True}


@router.post("/account/reauthenticate")
async def reauthenticate(payload: Proof, request: Request, staff: Staff, db: Db) -> dict:
    """Grant a short recent-auth window without creating another session."""
    member = required(staff)
    await fresh_proof(db, member, payload)
    row = await db.get(AdminSession, own_session(request))
    row.reauthenticated_at = datetime.now(timezone.utc)
    await db.run_sync(lambda sync: security.audit(sync, member.id, "account.reauthenticated"))
    await db.commit()
    return {"ok": True}


@router.post("/account/password")
async def password(payload: PasswordChange, request: Request, staff: Staff, db: Db) -> dict:
    """Require the current password/MFA and invalidate every old session."""
    member = required(staff)
    await fresh_proof(db, member, payload)
    if payload.new_password == payload.current_password:
        raise security.SecurityRejected("password_unchanged", 422)
    await db.run_sync(lambda sync: lifecycle.validate_password(sync, payload.new_password))
    member.password_hash = await asyncio.to_thread(hash_password, payload.new_password)
    member.session_version += 1
    await db.run_sync(lambda sync: security.revoke_others(sync, member.id, None))
    await db.run_sync(lambda sync: security.audit(sync, member.id, "account.password_changed"))
    await db.commit()
    return {"ok": True, "login_required": True}


@router.post("/account/revoke-session")
async def revoke(payload: SessionTarget, request: Request, staff: Staff, db: Db) -> dict:
    """Refuse cross-account session revocation, including guessed UUIDs."""
    member = required(staff)
    await db.run_sync(lambda sync: security.revoke_session(sync, member.id, str(payload.session_id)))
    await db.commit()
    return {"ok": True, "login_required": str(payload.session_id) == own_session(request)}


@router.post("/account/revoke-others")
async def revoke_all(request: Request, staff: Staff, db: Db) -> dict:
    """Preserve this authenticated session while revoking all other devices."""
    member = required(staff)
    count = await db.run_sync(lambda sync: security.revoke_others(sync, member.id, own_session(request)))
    await db.commit()
    return {"ok": True, "revoked": count}


@router.post("/account/mfa-setup")
async def mfa_setup(payload: Proof, staff: Staff, db: Db) -> dict:
    """Reveal a fresh enrollment secret only after current-password proof."""
    member = required(staff)
    await fresh_proof(db, member, payload)
    def start(sync):
        return security.begin_mfa(sync, security.profile_for(sync, member.id))
    secret = await db.run_sync(start)
    await db.commit()
    uri = make_otpauth_uri(secret, member.username)
    return {
        "ok": True,
        "secret": secret,
        "uri": uri,
        # This QR is generated in-process; never send TOTP seeds to a
        # third-party image service or public CDN.
        "qr_data_uri": make_mfa_qr_data_uri(uri),
    }


@router.post("/account/mfa-confirm")
async def mfa_confirm(payload: Code, request: Request, staff: Staff, db: Db) -> dict:
    """Confirm enrollment; other devices must log in with the new factor."""
    member = required(staff)
    await throttle("mfa-enroll:" + str(member.id), 8, 60)
    await db.execute(select(ShopStaff.id).where(ShopStaff.id == member.id).with_for_update())
    def complete(sync):
        codes = security.confirm_mfa(sync, security.profile_for(sync, member.id), payload.code)
        security.revoke_others(sync, member.id, own_session(request))
        return codes
    recovery = await db.run_sync(complete)
    await db.commit()
    return {"ok": True, "recovery_codes": recovery}


@router.post("/account/mfa-disable")
async def mfa_disable(payload: Proof, request: Request, staff: Staff, db: Db) -> dict:
    """Disable MFA only with fresh password and current OTP/recovery proof."""
    member = required(staff)
    if member.role in security.MFA_REQUIRED_ROLES:
        raise security.SecurityRejected("mfa_required_by_role", 409)
    await fresh_proof(db, member, payload)
    def disable(sync):
        security.disable_mfa(sync, security.profile_for(sync, member.id))
        security.revoke_others(sync, member.id, own_session(request))
    await db.run_sync(disable)
    await db.commit()
    return {"ok": True}


@router.get("/account/permissions")
async def permissions(staff: Staff) -> dict:
    """Describe fixed roles without implying editable arbitrary privileges."""
    member = required(staff)
    return {"role": member.role, "effective": sorted(security.ROLE_PERMISSIONS[member.role]),
            "roles": {name: sorted(values) for name, values in security.ROLE_PERMISSIONS.items()}}


@router.get("/connection-changes")
async def changes(staff: Staff, db: Db) -> dict:
    """Show requested, active and ambiguous state, not optimistic success."""
    required(staff, "bots.read")
    rows = (await db.scalars(select(ConnectionChange).order_by(ConnectionChange.created_at.desc()).limit(50))).all()
    cfg = (await db.scalars(select(ConnectionConfig))).all()
    return {"active": {v.platform: {"mode": v.mode, "version": v.version, "verified_at": v.verified_at.isoformat() if v.verified_at else None,
                "webhook_label": config.WEBHOOK_URL if v.platform == "telegram" else config.WEBHOOK_HOST + "/webhooks/bale/[private-secret]",
                "configured": bool(config.TOKEN if v.platform == "telegram" else config.BALE_BOT_TOKEN)} for v in cfg},
            "items": [{"id": v.id, "platform": v.platform, "previous_mode": v.previous_mode,
                "requested_mode": v.requested_mode, "state": v.state, "error_code": v.error_code,
                "created_at": v.created_at.isoformat(), "updated_at": v.updated_at.isoformat(), "requested_by": v.staff_id, "approved_by": v.approved_by} for v in rows]}


@router.post("/connection-changes")
async def stage(payload: StageChange, staff: Staff, db: Db) -> dict:
    """Stage with an idempotency key; no network or receiver change occurs."""
    member = required(staff, "bots.configure")
    mode = config.TELEGRAM_UPDATE_MODE if payload.platform == "telegram" else "webhook"
    row = await db.run_sync(lambda sync: stage_change(sync, actor_id=member.id,
        platform=payload.platform, current_mode=mode, requested_mode=payload.mode,
        key=str(payload.idempotency_key)))
    result = {"ok": True, "operation_id": row.id, "state": row.state}
    await db.commit()
    return result


@router.post("/connection-changes/action")
async def change_action(payload: ChangeAction, request: Request, staff: Staff, db: Db) -> dict:
    """Queue/cancel a known operation; only the supervised worker calls APIs."""
    member = required(staff, "bots.apply")
    await fresh_proof(db, member, payload)
    row = await db.scalar(select(ConnectionChange).where(
        ConnectionChange.id == str(payload.operation_id)).with_for_update())
    if row is None:
        raise security.SecurityRejected("operation_not_found", 404)
    if payload.action in {"apply", "reconcile"}:
        worker = getattr(request.app.state, "connection_supervisor", None)
        if worker is None or worker.worker is None or worker.worker.done():
            raise security.SecurityRejected("connection_worker_unavailable", 503)
    if payload.action == "reconcile":
        if row.state != "needs_review":
            raise security.SecurityRejected("invalid_operation_state", 409)
        row.verification_only = True
    row.approved_by = member.id
    target = "cancelled" if payload.action == "cancel" else "queued"
    # Repeated HTTP confirmation returns the durable existing result.
    if row.state != target:
        await db.run_sync(lambda sync: transition(sync, row, target, actor_id=member.id))
    result = {"ok": True, "operation_id": row.id, "state": row.state}
    await db.commit()
    return result


@router.post("/bot-connections/telegram-mode-request")
async def retired_mode_request(staff: Staff) -> dict:
    """Do not permit old Redis-only staging to bypass durable apply/audit."""
    required(staff, "bots.configure")
    raise security.SecurityRejected("legacy_endpoint_retired", 409)


class ChannelFeatureItem(StrictPayload):
    """One provider's shopping and internal-credit controls."""

    platform: Literal["telegram", "bale"]
    cart_enabled: bool
    store_credit_enabled: bool
    store_credit_label: str = Field(min_length=1, max_length=80)


class ChannelFeaturesUpdate(StrictPayload):
    """Replace the two provider policies in one atomic transaction."""

    items: list[ChannelFeatureItem] = Field(min_length=2, max_length=2)


@router.get("/channel-features")
async def channel_features(staff: Staff, db: Db) -> dict:
    """Return the current effective flags for both Telegram and Bale."""
    required(staff, "settings.manage")
    rows = [to_data(await get_features(db, platform)) for platform in PLATFORMS]
    return {"items": rows}


@router.post("/channel-features")
async def update_channel_features(
    payload: ChannelFeaturesUpdate, staff: Staff, db: Db,
) -> dict:
    """Toggle provider features atomically; preserve all carts and ledgers."""
    actor = required(staff, "settings.manage")
    options = {item.platform: item for item in payload.items}
    if set(options) != set(PLATFORMS):
        raise security.SecurityRejected("invalid_request", 422)

    for platform in PLATFORMS:
        item = options[platform]
        name = item.store_credit_label.strip()
        if not name or len(name) > 80:
            raise security.SecurityRejected("invalid_request", 422)
        record = await db.scalar(
            select(ShopChannelFeature)
            .where(ShopChannelFeature.platform == platform)
            .with_for_update()
        )
        if record is None:
            record = ShopChannelFeature(platform=platform)
            db.add(record)
        record.cart_enabled = item.cart_enabled
        record.store_credit_enabled = item.store_credit_enabled
        record.store_credit_label = name
        record.changed_by = actor.id

    await db.run_sync(lambda sync: security.audit(
        sync, actor.id, "settings.channel_features_changed",
    ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise security.SecurityRejected("configuration_changed", 409) from None
    return {"ok": True, "items": [
        to_data(await get_features(db, platform)) for platform in PLATFORMS
    ]}


class StaffInvite(StrictPayload):
    """Invite a user with an explicit role, not an administrator-chosen password."""

    username: str = Field(min_length=3, max_length=80)
    role: Literal["superadmin", "viewer", "content", "sales", "marketing", "finance"] = "viewer"


class PasswordResetRequest(StrictPayload):
    """Select the staff account whose password owner will reset."""

    staff_id: int = Field(ge=1)


class InvitationCancel(StrictPayload):
    """Select exactly one pending invitation to revoke."""

    invitation_id: UUID


class StaffUpdate(StrictPayload):
    """Only role or status are editable by a manager; passwords are private."""

    role: Literal["superadmin", "viewer", "content", "sales", "marketing", "finance"] | None = None
    is_active: bool | None = None


class PasswordPolicyPatch(StrictPayload):
    """The administrator configures minimum length and optional complexity."""

    min_length: int = Field(ge=12, le=64)
    require_upper: bool = False
    require_lower: bool = False
    require_digit: bool = False
    require_symbol: bool = False


class RedeemRequest(StrictPayload):
    """Anonymous one-time capability, never a signed-in or manager-set password."""

    kind: Literal["invite", "reset"]
    token: str = Field(min_length=43, max_length=43)
    password: str = Field(min_length=12, max_length=256)


@router.post("/auth/redeem")
async def redeem_staff(payload: RedeemRequest, staff: Staff, db: Db) -> dict:
    """Redeem a hashed link atomically after rate limiting attempts."""
    if staff is not None:
        raise security.SecurityRejected("invalid_request", 422)
    digest = hashlib.sha256(payload.token.encode("ascii")).hexdigest()
    # A global cap prevents attackers from bypassing per-link throttling by
    # generating unlimited random non-existing tokens.
    await throttle("staff-redeem-global", 500, 60)
    await throttle("staff-redeem:" + digest, 8, 600)
    await db.run_sync(lambda sync: lifecycle.prepare_redemption(
        sync, payload.kind, payload.token, payload.password,
    ))
    password_hash = await asyncio.to_thread(hash_password, payload.password)
    try:
        await db.run_sync(lambda sync: lifecycle.redeem(
            sync, payload.kind, payload.token, password_hash, payload.password,
        ))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise security.SecurityRejected("invalid_link", 410) from None
    return {"ok": True}


@router.post("/staff", status_code=410)
async def retired_staff_creation(staff: Staff) -> dict:
    """Never fall through to the legacy direct-password creation handler."""
    required(staff, "staff.manage")
    raise security.SecurityRejected("invitation_only", 410)


@router.get("/staff/invitations")
async def staff_invitations(staff: Staff, db: Db) -> dict:
    """Return status and expiry, not invitation tokens."""
    required(staff, "staff.manage")
    rows = (await db.scalars(select(ShopStaffInvitation)
        .order_by(ShopStaffInvitation.created_at.desc()).limit(100))).all()
    return {"items": [{
        "id": row.id, "username": row.username, "role": row.role,
        "status": lifecycle.invitation_status(row),
        "expires_at": row.expires_at.isoformat(),
    } for row in rows]}


@router.post("/staff/invitations", status_code=201)
async def invite_staff(payload: StaffInvite, staff: Staff, db: Db) -> dict:
    """Return a one-time bearer once; admins must share the link securely."""
    actor = required(staff, "staff.manage")
    item, token = await db.run_sync(lambda sync: lifecycle.issue_invitation(
        sync, actor.id, payload.username, payload.role,
    ))
    await db.commit()
    return {"ok": True, "id": item.id, "token": token,
            "expires_at": item.expires_at.isoformat()}


@router.post("/staff/invitations/cancel")
async def cancel_staff_invitation(payload: InvitationCancel, staff: Staff, db: Db) -> dict:
    """Revoke a pending invitation without changing existing staff accounts."""
    actor = required(staff, "staff.manage")
    await db.run_sync(lambda sync: lifecycle.cancel_invitation(
        sync, actor.id, str(payload.invitation_id),
    ))
    await db.commit()
    return {"ok": True}


@router.post("/staff/password-reset")
async def issue_staff_reset(payload: PasswordResetRequest, staff: Staff, db: Db) -> dict:
    """Issue a short-lived reset capability; never reveal or assign passwords."""
    actor = required(staff, "staff.manage")
    if payload.staff_id == actor.id:
        raise security.SecurityRejected("use_my_account", 409)
    item, token = await db.run_sync(lambda sync: lifecycle.issue_reset(
        sync, actor.id, payload.staff_id,
    ))
    await db.commit()
    return {"ok": True, "id": item.id, "token": token,
            "expires_at": item.expires_at.isoformat()}


@router.get("/staff/password-policy")
async def get_staff_password_policy(staff: Staff, db: Db) -> dict:
    """Expose current requirements to the administrator."""
    required(staff, "staff.manage")
    return await db.run_sync(lambda sync: lifecycle.serialize_policy(
        lifecycle.policy_for(sync),
    ))


@router.post("/staff/password-policy")
async def set_staff_password_policy(payload: PasswordPolicyPatch, staff: Staff, db: Db) -> dict:
    """Require recent authentication, persist policy and emit an audit event."""
    actor = required(staff, "staff.manage")
    result = await db.run_sync(lambda sync: lifecycle.configure_policy(
        sync, actor.id, **payload.model_dump(),
    ))
    serialized = lifecycle.serialize_policy(result)
    await db.commit()
    return {"ok": True, **serialized}


@router.patch("/staff/{member_id}")
async def change_staff(member_id: int, payload: StaffUpdate, staff: Staff, db: Db) -> dict:
    """Serialize last-admin protection and invalidate sessions on role changes."""
    member = required(staff, "staff.manage")
    admins = (await db.scalars(select(ShopStaff).where(
        ShopStaff.role == "superadmin", ShopStaff.is_active.is_(True)
    ).order_by(ShopStaff.id).with_for_update())).all()
    target = await db.scalar(select(ShopStaff).where(ShopStaff.id == member_id).with_for_update())
    if target is None:
        raise security.SecurityRejected("staff_not_found", 404)
    if target.id == member.id and (payload.is_active is False
            or (payload.role is not None and payload.role != target.role)):
        raise security.SecurityRejected("use_my_account", 409)
    demoting = payload.role is not None and payload.role != "superadmin"
    if (target.role == "superadmin" and target.is_active
            and (demoting or payload.is_active is False) and len(admins) <= 1):
        raise security.SecurityRejected("last_admin_protected", 409)
    changed = False
    for field in ("role", "is_active"):
        value = getattr(payload, field)
        if value is not None and getattr(target, field) != value:
            setattr(target, field, value)
            changed = True
    if not changed:
        raise security.SecurityRejected("invalid_request", 422)
    target.session_version += 1
    await db.run_sync(lambda sync: security.revoke_others(sync, target.id, None))
    await db.run_sync(lambda sync: security.audit(sync, member.id, "staff.changed", str(target.id)))
    await db.commit()
    return {"id": member_id, "sessions_revoked": True}


@router.get("/account/audit")
async def audit_log(
    staff: Staff, db: Db, page: int = 1, actor: int | None = None,
    action: str = "", since: datetime | None = None, until: datetime | None = None,
) -> dict:
    """Search administrative activity with bounded, authorized pagination."""
    required(staff, "audit.read")
    if page < 1 or page > 10000 or len(action) > 80 or (
        actor is not None and actor < 1
    ):
        raise security.SecurityRejected("invalid_request", 422)
    conditions = []
    if actor is not None:
        conditions.append(AdminEvent.staff_id == actor)
    if action:
        if not action.replace(".", "").replace("_", "").isalpha():
            raise security.SecurityRejected("invalid_request", 422)
        conditions.append(AdminEvent.action == action)
    if since is not None:
        conditions.append(AdminEvent.created_at >= security.utc(since))
    if until is not None:
        conditions.append(AdminEvent.created_at <= security.utc(until))
    stmt = select(AdminEvent)
    count = select(func.count()).select_from(AdminEvent)
    if conditions:
        stmt = stmt.where(*conditions)
        count = count.where(*conditions)
    total = int(await db.scalar(count) or 0)
    rows = (await db.scalars(stmt.order_by(AdminEvent.created_at.desc(), AdminEvent.id.desc())
        .offset((page - 1) * 50).limit(50))).all()
    return {"items": [{
        "id": row.id, "actor": row.staff_id, "action": row.action,
        "target": row.target, "created_at": row.created_at.isoformat(),
    } for row in rows], "total": total, "page": page, "page_size": 50}
