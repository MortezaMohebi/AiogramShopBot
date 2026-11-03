"""Encrypted, versioned Telegram API transport settings and change receipts.

Bot tokens are never stored here. One active, verified configuration survives
restart; proposed changes require explicit apply after a Telegram getMe probe.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopTelegramTransport(Base):
    """Singleton, last-successfully-applied Telegram outbound transport."""

    __tablename__ = "shop_telegram_transport"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    verified_bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id"), nullable=False,
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_shop_telegram_transport_singleton"),
        CheckConstraint("version > 0", name="ck_shop_telegram_transport_version"),
    )


class ShopTelegramTransportChange(Base):
    """Audit-safe pending and completed transport changes, including rollback."""

    __tablename__ = "shop_telegram_transport_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id"), nullable=False,
    )
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    proposed_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    previous_ciphertext: Mapped[str | None] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(
        String(16), nullable=False, default="switch",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    verified_bot_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "operation IN ('switch', 'rollback')",
            name="ck_shop_transport_operation",
        ),
        CheckConstraint(
            "status IN ('pending','applying','succeeded','failed',"
            "'cancelled','needs_review')",
            name="ck_shop_transport_change_status",
        ),
        CheckConstraint(
            "expected_version > 0",
            name="ck_shop_transport_expected_version",
        ),
    )


TELEGRAM_TRANSPORT_TABLES = frozenset({
    ShopTelegramTransport.__tablename__,
    ShopTelegramTransportChange.__tablename__,
})
