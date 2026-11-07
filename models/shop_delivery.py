"""Platform-specific file identifier cache and webhook receipt ledger.

Telegram and Bale file IDs belong to the issuing bot, even when the original
uploaded file is shared. Never transfer a remote ID between bot tokens.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopRemoteFile(Base):
    """One verified file_id for one bot, platform, asset and delivery kind."""

    __tablename__ = "shop_remote_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    bot_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(80), nullable=False)
    delivery_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    remote_file_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "platform", "bot_fingerprint", "storage_key", "delivery_kind",
            name="uq_shop_remote_file_bot_asset",
        ),
        CheckConstraint(
            "platform IN ('telegram','bale')", name="ck_shop_remote_platform"
        ),
        CheckConstraint(
            "delivery_kind IN ('photo','video','audio','voice','document','animation')",
            name="ck_shop_remote_kind",
        ),
    )


class ShopInboundUpdate(Base):
    """At-most-once dispatch receipt for a platform-specific webhook update."""

    __tablename__ = "shop_inbound_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    bot_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    update_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="processing"
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    __table_args__ = (
        # A bot's update offset survives token rotation without allowing
        # a duplicate callback to re-run under a new token fingerprint.
        UniqueConstraint(
            "bot_id", "update_id",
            name="uq_shop_inbound_bot_update",
        ),
        CheckConstraint(
            "status IN ('processing','processed','needs_review')",
            name="ck_shop_inbound_status",
        ),
        CheckConstraint("update_id >= 0", name="ck_shop_inbound_id"),
    )
