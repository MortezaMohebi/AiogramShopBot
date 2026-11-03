"""Additive staff lifecycle status, separate from authentication credentials.

The legacy ShopStaff.is_active remains the security source of truth for login.
This companion table explains whether a disabled account is suspended or
permanently disabled without changing the existing production staff schema.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopStaffState(Base):
    """Audited operator lifecycle status and private suspension reason."""

    __tablename__ = "shop_staff_states"

    staff_id: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="CASCADE"), primary_key=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active",
    )
    reason: Mapped[str] = mapped_column(
        String(500), nullable=False, default="",
    )
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','suspended','disabled')",
            name="ck_staff_lifecycle_status",
        ),
    )


STAFF_STATES_TABLES = frozenset({ShopStaffState.__tablename__})
