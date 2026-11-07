"""Per-bot operational settings and status distinct from receiver ownership.

Registry-owned draft bots remain offline until verification and explicit
activation. Operational settings never change recorded payment ownership.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopBotOperations(Base):
    """Safe per-bot behavior preferences and requested operational state."""

    __tablename__ = "shop_bot_operations"

    bot_id: Mapped[str] = mapped_column(
        ForeignKey("shop_bots.id", ondelete="CASCADE"), primary_key=True,
    )
    desired_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="disabled",
        server_default="disabled",
    )
    welcome_message: Mapped[str | None] = mapped_column(Text)
    maintenance_message: Mapped[str | None] = mapped_column(Text)
    support_url: Mapped[str | None] = mapped_column(String(500))
    owner_staff_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    environment: Mapped[str] = mapped_column(
        String(16), nullable=False, default="staging",
        server_default="staging",
    )
    reason: Mapped[str | None] = mapped_column(String(500))
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "desired_state IN ('active','maintenance','paused','disabled')",
            name="ck_bot_operations_state",
        ),
        CheckConstraint(
            "environment IN ('codespaces','staging','production')",
            name="ck_bot_operations_environment",
        ),
        CheckConstraint(
            "maintenance_message IS NULL OR "
            "length(maintenance_message) BETWEEN 1 AND 4096",
            name="ck_bot_operations_maintenance_message",
        ),
        CheckConstraint(
            "welcome_message IS NULL OR length(welcome_message) BETWEEN 1 AND 4096",
            name="ck_bot_operations_welcome_message",
        ),
    )


class ShopBotOperationsEvent(Base):
    """Immutable before/after state change without credential material."""

    __tablename__ = "shop_bot_operations_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bot_id: Mapped[str] = mapped_column(
        ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id"), nullable=False,
    )
    previous_state: Mapped[str] = mapped_column(String(20), nullable=False)
    next_state: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "previous_state IN ('active','maintenance','paused','disabled')",
            name="ck_bot_state_audit_previous",
        ),
        CheckConstraint(
            "next_state IN ('active','maintenance','paused','disabled')",
            name="ck_bot_state_audit_next",
        ),
    )


BOT_OPERATIONS_TABLES = frozenset({
    ShopBotOperations.__tablename__,
    ShopBotOperationsEvent.__tablename__,
})
