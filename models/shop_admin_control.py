"""Additive control-plane tables; never store plaintext credentials or tokens."""

from datetime import datetime
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class AdminProfile(Base):
    """Self-service preferences and encrypted optional MFA enrollment."""

    __tablename__ = "shop_admin_profiles"
    staff_id: Mapped[int] = mapped_column(ForeignKey("shop_staff.id"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    time_zone: Mapped[str] = mapped_column(String(80), default="Asia/Tehran", nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(Text)
    pending_mfa: Mapped[str | None] = mapped_column(Text)
    pending_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_totp_step: Mapped[int] = mapped_column(Integer, default=-1, nullable=False)
    recovery_hashes: Mapped[str] = mapped_column(Text, default="[]", nullable=False)


class AdminSession(Base):
    """A revocable device session identified only by a hash of its bearer token."""

    __tablename__ = "shop_admin_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    staff_id: Mapped[int] = mapped_column(ForeignKey("shop_staff.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reauthenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(40))
    # The active Store set belongs to this device's revocable session.
    current_store_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
    )
    store_context_version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, server_default="1",
    )
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_admin_session_version"),
        CheckConstraint(
            "store_context_version > 0",
            name="ck_admin_session_store_context_version",
        ),
    )


class AdminEvent(Base):
    """Append-only application audit records, with allowlisted non-secret data."""

    __tablename__ = "shop_admin_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("shop_staff.id"), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConnectionConfig(Base):
    """Durable last-verified receiver mode and optimistic version per platform."""

    __tablename__ = "shop_connection_configs"
    platform: Mapped[str] = mapped_column(String(12), primary_key=True)
    mode: Mapped[str] = mapped_column(String(12), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_update_id: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("platform IN ('telegram', 'bale')", name="ck_control_platform"),
        CheckConstraint("mode IN ('webhook', 'polling')", name="ck_control_mode"),
    )


class ConnectionChange(Base):
    """Idempotent, audited receiver changes; ambiguous outcomes need review."""

    __tablename__ = "shop_connection_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("shop_staff.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(36), nullable=False)
    platform: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    previous_mode: Mapped[str] = mapped_column(String(12), nullable=False)
    requested_mode: Mapped[str] = mapped_column(String(12), nullable=False)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(80))
    verification_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("shop_staff.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("staff_id", "idempotency_key", name="uq_connection_change_key"),
        CheckConstraint("state IN ('pending','queued','applying','succeeded','failed','cancelled','needs_review')", name="ck_connection_change_state"),
    )


CONTROL_TABLE_NAMES = frozenset({
    AdminProfile.__tablename__, AdminSession.__tablename__, AdminEvent.__tablename__,
    ConnectionConfig.__tablename__, ConnectionChange.__tablename__,
})
