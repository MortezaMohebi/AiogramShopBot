"""Additive CRM records for platform-scoped Telegram and Bale identities.

Never infer that matching numeric messaging IDs identify the same person.
Marketing consent is recorded only from customer-authorized bot commands.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopCustomerProfile(Base):
    """Private CRM notes, follow-up assignment and documented restrictions."""

    __tablename__ = "shop_customer_profiles"

    identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="CASCADE"), primary_key=True,
    )
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    owner_staff_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    support_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", server_default="open",
    )
    restriction_reason: Mapped[str | None] = mapped_column(String(500))
    restriction_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    restricted_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    restricted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    # Provider responses, not guessed admin flags, must establish this status.
    bot_blocked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "support_status IN ('open','pending','resolved')",
            name="ck_customer_support_status",
        ),
    )


class ShopCustomerNote(Base):
    """Immutable internal support note, never shown to a shop customer."""

    __tablename__ = "shop_customer_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id"), nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "length(content) BETWEEN 1 AND 4000", name="ck_customer_note_length",
        ),
    )


class ShopCustomerConsentEvent(Base):
    """Append-only advertising consent with source, topic, and exact time."""

    __tablename__ = "shop_customer_consent_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    topic: Mapped[str] = mapped_column(
        String(60), nullable=False, default="shop_announcements",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "source IN ('telegram_command','bale_command','customer_portal')",
            name="ck_customer_consent_source",
        ),
    )


class ShopCustomerAudit(Base):
    """Append-only operational CRM audit, with no passwords or bot tokens."""

    __tablename__ = "shop_customer_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id"), nullable=False,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "action IN ('profile_updated','note_added','restricted',"
            "'restriction_cleared','data_exported')",
            name="ck_customer_audit_action",
        ),
        Index("ix_customer_audit_actor_date", "actor_id", "created_at"),
    )


class ShopCustomerRetentionPolicy(Base):
    """Explicit review periods; never auto-delete orders or financial ledgers."""

    __tablename__ = "shop_customer_retention_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    note_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=365, server_default="365",
    )
    audit_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=730, server_default="730",
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_customer_retention_singleton"),
        CheckConstraint(
            "note_retention_days BETWEEN 30 AND 3650",
            name="ck_customer_note_retention",
        ),
        CheckConstraint(
            "audit_retention_days BETWEEN 365 AND 3650",
            name="ck_customer_audit_retention",
        ),
    )


CRM_TABLE_NAMES = frozenset({
    ShopCustomerProfile.__tablename__,
    ShopCustomerNote.__tablename__,
    ShopCustomerConsentEvent.__tablename__,
    ShopCustomerAudit.__tablename__,
    ShopCustomerRetentionPolicy.__tablename__,
})
