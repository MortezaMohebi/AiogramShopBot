"""Store-owned private digital goods and immutable delivery receipts.

Digital files never use the public ProductMedia catalog or public URLs.
License values are encrypted under a separate Store/product purpose key.
Per OrderLine units have unique delivery rows and cannot be retried after
a provider-unknown result.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopDigitalAsset(Base):
    """One private downloadable file version tied to its Store and Product."""

    __tablename__ = "shop_digital_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("shop_products.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    storage_key: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True,
    )
    original_filename: Mapped[str] = mapped_column(
        String(255), nullable=False,
    )
    mime_type: Mapped[str] = mapped_column(String(90), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        Index(
            "uq_shop_digital_active_file", "store_id", "product_id",
            unique=True, postgresql_where=text("active = true"),
            sqlite_where=text("active = true"),
        ),
        CheckConstraint(
            "size_bytes BETWEEN 1 AND 50000000",
            name="ck_shop_digital_file_size",
        ),
        CheckConstraint(
            "length(sha256) = 64",
            name="ck_shop_digital_file_sha",
        ),
    )


class ShopDigitalLicense(Base):
    """A sealed, never-returned-to-admin license reserved for one paid unit."""

    __tablename__ = "shop_digital_licenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("shop_products.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    code_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False,
    )
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="available",
        server_default="available",
    )
    claimed_order_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_order_lines.id", ondelete="RESTRICT"),
    )
    claimed_unit_index: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        UniqueConstraint(
            "store_id", "product_id", "code_fingerprint",
            name="uq_shop_digital_license_fingerprint",
        ),
        CheckConstraint(
            "state IN ('available','claimed','delivered','needs_review')",
            name="ck_shop_digital_license_state",
        ),
        CheckConstraint(
            "(state = 'available' AND claimed_order_line_id IS NULL "
            "AND claimed_unit_index IS NULL) OR "
            "(state != 'available' AND claimed_order_line_id IS NOT NULL "
            "AND claimed_unit_index >= 0)",
            name="ck_shop_digital_license_claim",
        ),
    )


class ShopDigitalDelivery(Base):
    """A single durable, idempotent paid-only outbound document/license."""

    __tablename__ = "shop_digital_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("shop_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    order_line_id: Mapped[int] = mapped_column(
        ForeignKey("shop_order_lines.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("shop_products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform_user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_digital_assets.id", ondelete="RESTRICT"),
    )
    license_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_digital_licenses.id", ondelete="RESTRICT"),
    )
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued",
        server_default="queued",
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(80))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        UniqueConstraint(
            "order_line_id", "unit_index",
            name="uq_shop_digital_one_delivery_per_unit",
        ),
        CheckConstraint(
            "(kind = 'file' AND asset_id IS NOT NULL AND license_id IS NULL) "
            "OR (kind = 'license' AND license_id IS NOT NULL "
            "AND asset_id IS NULL)",
            name="ck_shop_digital_delivery_source",
        ),
        CheckConstraint(
            "state IN ('queued','sending','delivered','needs_review','blocked')",
            name="ck_shop_digital_delivery_state",
        ),
        CheckConstraint(
            "unit_index >= 0", name="ck_shop_digital_delivery_unit",
        ),
        Index("ix_shop_digital_delivery_bot_state", "bot_id", "state"),
    )


DIGITAL_DELIVERY_TABLES = frozenset({
    ShopDigitalAsset.__tablename__,
    ShopDigitalLicense.__tablename__,
    ShopDigitalDelivery.__tablename__,
})
