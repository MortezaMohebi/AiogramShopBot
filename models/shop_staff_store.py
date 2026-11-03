"""Staff authorization and device-session Store selection.

The membership relation is the only authority for a user's Store access.
The preferred default belongs to the user; active Store selection belongs
to the individual authenticated browser session, preventing cross-device
context races when one operator works with multiple Stores simultaneously.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopStaffStoreAccess(Base):
    """One independently revocable, explicitly granted Store membership."""

    __tablename__ = "shop_staff_store_access"

    staff_id: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="RESTRICT"), primary_key=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    access_level: Mapped[str] = mapped_column(
        String(12), nullable=False, default="viewer",
        server_default="viewer",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "access_level IN ('viewer','editor','manager')",
            name="ck_staff_store_access_level",
        ),
    )


class ShopStaffStorePreference(Base):
    """User-level default Store and versioned preference state."""

    __tablename__ = "shop_staff_store_preferences"

    staff_id: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="RESTRICT"), primary_key=True,
    )
    default_store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_staff_store_pref_version"),
    )


class ShopAdminSessionStore(Base):
    """One active Store inside one revocable admin session."""

    __tablename__ = "shop_admin_session_stores"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_admin_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        primary_key=True,
    )


STAFF_STORE_TABLES = frozenset({
    ShopStaffStoreAccess.__tablename__,
    ShopStaffStorePreference.__tablename__,
    ShopAdminSessionStore.__tablename__,
})
