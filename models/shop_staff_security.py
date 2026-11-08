"""Durable, one-time staff invitations and password recovery policy.

Opaque tokens are never stored in plaintext or included in audit events.
Invitation delivery is out-of-band: the issuing administrator receives a
single-use link to share through a trusted communication channel.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopPasswordPolicy(Base):
    """Single configurable password policy shared by all staff accounts."""

    __tablename__ = "shop_password_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    min_length: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    require_upper: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    require_lower: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    require_digit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    require_symbol: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_shop_password_policy_singleton"),
        CheckConstraint("min_length BETWEEN 12 AND 64", name="ck_shop_password_policy_length"),
    )


class ShopStaffInvitation(Base):
    """Invitation with an expiring hashed bearer; acceptance is atomic."""

    __tablename__ = "shop_staff_invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "role IN ('superadmin','sales','content','finance','marketing','viewer')",
            name="ck_staff_invitation_role",
        ),
    )


class ShopStaffPasswordReset(Base):
    """One-time recovery token issued to an existing active staff account."""

    __tablename__ = "shop_staff_password_resets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    staff_id: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id"), nullable=False, index=True,
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


STAFF_SECURITY_TABLE_NAMES = frozenset({
    ShopPasswordPolicy.__tablename__,
    ShopStaffInvitation.__tablename__,
    ShopStaffPasswordReset.__tablename__,
})
