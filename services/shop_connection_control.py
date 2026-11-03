"""Durable, idempotent connection-change state machine, without provider I/O."""
from uuid import UUID, uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from models.shop_admin_control import ConnectionChange, ConnectionConfig
from services.shop_admin_security import SecurityRejected, audit, clock

TRANSITIONS = {
    "pending": {"queued", "cancelled"},
    "queued": {"applying", "cancelled", "failed"},
    "applying": {"succeeded", "failed", "needs_review"},
    "succeeded": set(), "failed": set(), "cancelled": set(), "needs_review": {"queued"},
}


def stage_change(db: Session, *, actor_id: int, platform: str, current_mode: str,
                 requested_mode: str, key: str, now=None) -> ConnectionChange:
    """Serialize staging on the platform config and reject conflicting requests."""
    if platform not in {"telegram", "bale"} or requested_mode not in {"webhook", "polling"}:
        raise SecurityRejected("invalid_request", 422)
    try:
        UUID(key)
    except (ValueError, TypeError):
        raise SecurityRejected("invalid_request", 422) from None
    cfg = db.scalar(select(ConnectionConfig).where(ConnectionConfig.platform == platform).with_for_update())
    if cfg is None:
        cfg = ConnectionConfig(platform=platform, mode=current_mode, version=1)
        db.add(cfg)
        db.flush()
    prior = db.scalar(select(ConnectionChange).where(
        ConnectionChange.staff_id == actor_id, ConnectionChange.idempotency_key == key))
    if prior:
        if prior.platform != platform or prior.requested_mode != requested_mode:
            raise SecurityRejected("idempotency_conflict", 409)
        return prior
    active = db.scalar(select(ConnectionChange.id).where(
        ConnectionChange.platform == platform,
        ConnectionChange.state.in_(("pending", "queued", "applying", "needs_review"))))
    if active:
        raise SecurityRejected("connection_change_in_progress", 409)
    row = ConnectionChange(id=str(uuid4()), staff_id=actor_id,
        idempotency_key=key, platform=platform, previous_mode=cfg.mode,
        requested_mode=requested_mode, expected_version=cfg.version,
        state="pending", created_at=clock(now), updated_at=clock(now))
    db.add(row)
    audit(db, actor_id, "connection.staged", row.id, now=now)
    db.flush()
    return row


def transition(db: Session, change: ConnectionChange, state: str, *, actor_id: int,
               error_code: str | None = None, now=None) -> None:
    """Validate lifecycle transitions and advance only verified configuration."""
    if change.state == "needs_review" and not change.verification_only:
        raise SecurityRejected("reconciliation_required", 409)
    if state not in TRANSITIONS.get(change.state, set()):
        raise SecurityRejected("invalid_operation_state", 409)
    cfg = db.scalar(select(ConnectionConfig).where(
        ConnectionConfig.platform == change.platform).with_for_update())
    if state in {"queued", "applying", "succeeded"} and (
        cfg is None or cfg.version != change.expected_version):
        raise SecurityRejected("configuration_changed", 409)
    if state == "succeeded":
        cfg.mode = change.requested_mode
        cfg.version += 1
        cfg.verified_at = clock(now)
    change.state, change.updated_at = state, clock(now)
    change.error_code = error_code
    audit(db, actor_id, "connection." + state, change.id, now=now)
