"""Persist private wholesale forms owned by authenticated Store customers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopWholesaleApplication(Base):
    """Keep submitted application fields private and out of receipts."""

    __tablename__ = "shop_wholesale_applications"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    bot_id: Mapped[str] = mapped_column(
        ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("shop_store_customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    origin_identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
    platform_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Empty defaults retain the existing company-only v1 application contract.
    name: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        default="",
        server_default="",
    )
    phone: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="",
        server_default="",
    )
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    city: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="",
        server_default="",
    )
    estimated_monthly_amount: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    # Retain only the private evidence UUID; do not copy its provider file ID.
    document_handle: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("shop_workflow_uploads.id", ondelete="RESTRICT"),
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="submitted",
        server_default="submitted",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "platform IN ('telegram','bale')",
            name="ck_shop_wholesale_platform",
        ),
        CheckConstraint(
            "platform_user_id > 0",
            name="ck_shop_wholesale_platform_user",
        ),
        CheckConstraint("length(name) <= 160", name="ck_shop_wholesale_name"),
        CheckConstraint("length(phone) <= 32", name="ck_shop_wholesale_phone"),
        CheckConstraint(
            "length(company) BETWEEN 1 AND 200",
            name="ck_shop_wholesale_company",
        ),
        CheckConstraint("length(city) <= 120", name="ck_shop_wholesale_city"),
        CheckConstraint(
            "estimated_monthly_amount BETWEEN 0 AND 9007199254740991",
            name="ck_shop_wholesale_monthly_amount",
        ),
        CheckConstraint(
            "document_handle IS NULL OR length(document_handle) = 36",
            name="ck_shop_wholesale_document_handle",
        ),
        CheckConstraint(
            "status = 'submitted'",
            name="ck_shop_wholesale_status",
        ),
        Index("ix_shop_wholesale_store_status", "store_id", "status"),
        Index("ix_shop_wholesale_owner", "store_id", "customer_id", "bot_id"),
    )
