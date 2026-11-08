"""Durable, per-bot Telegram and Bale receiver ownership metadata.

All webhook secrets are encrypted at rest. The public binding ID is opaque,
and a route is never trusted without a matching secret and an active
authenticated bot identity from the database.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopBotReceiver(Base):
    """One explicit webhook/polling receiver per verified registered bot."""

    __tablename__ = "shop_bot_receivers"

    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    binding_id: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True,
    )
    mode: Mapped[str] = mapped_column(
        String(8), nullable=False, default="webhook", server_default="webhook",
    )
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="staged",
        server_default="staged",
    )
    webhook_secret_ciphertext: Mapped[str] = mapped_column(
        Text, nullable=False,
    )
    webhook_secret_digest: Mapped[str] = mapped_column(
        String(64), nullable=False,
    )
    credential_version: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    next_update_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0",
    )
    last_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "mode IN ('webhook','polling')", name="ck_bot_receiver_mode",
        ),
        CheckConstraint(
            "state IN ('staged','applying','active','paused','disabled',"
            "'needs_review')",
            name="ck_bot_receiver_state",
        ),
        CheckConstraint(
            "version >= 1", name="ck_bot_receiver_version",
        ),
        CheckConstraint(
            "credential_version >= 1",
            name="ck_bot_receiver_credential_version",
        ),
        CheckConstraint(
            "next_update_id >= 0", name="ck_bot_receiver_offset",
        ),
    )


class ShopBotReceiverEvent(Base):
    """Append-only no-token receiver activation and reconciliation events."""

    __tablename__ = "shop_bot_receiver_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "action IN ('staged','applying','activated','paused',"
            "'disabled','needs_review','reconciled')",
            name="ck_bot_receiver_event_action",
        ),
    )


BOT_RUNTIME_TABLES = frozenset({
    ShopBotReceiver.__tablename__,
    ShopBotReceiverEvent.__tablename__,
})
