"""Database-backed, revocable staff accounts for the Persian shop dashboard.

No account has a default password. Staff are provisioned explicitly with the
bootstrap command; legacy shared `admin` credentials are no longer accepted.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopStaff(Base):
    """A uniquely named dashboard operator with a restricted role."""

    __tablename__ = "shop_staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="viewer"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    session_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('superadmin','sales','content','finance','marketing','viewer')",
            name="ck_shop_staff_role",
        ),
        CheckConstraint(
            "session_version > 0", name="ck_shop_staff_session_version"
        ),
    )

    def __repr__(self) -> str:
        """Use the login name for staff autocomplete."""
        return self.username
