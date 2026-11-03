"""Optional staff date, language and work-alert preferences.

The underlying security and authorization settings do not depend on these
display preferences. Security alerts cannot be silenced by a staff member.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, String, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopStaffPreferences(Base):
    """A private per-staff UI locale and non-security work notification policy."""

    __tablename__ = "shop_staff_preferences"

    staff_id: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="CASCADE"), primary_key=True,
    )
    calendar: Mapped[str] = mapped_column(
        String(16), nullable=False, default="auto", server_default="auto",
    )
    language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="fa", server_default="fa",
    )
    notify_orders: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    notify_campaigns: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    notify_finance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    notify_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "calendar IN ('auto','jalali','gregorian')",
            name="ck_staff_calendar",
        ),
        CheckConstraint(
            "language IN ('fa','en')", name="ck_staff_ui_language",
        ),
    )


STAFF_PREFERENCES_TABLES = frozenset({ShopStaffPreferences.__tablename__})
