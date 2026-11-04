"""Private digital asset catalog and audited single-attempt delivery receipts.

Digital asset bytes/license codes are never stored in customer-visible
ProductMedia or served by the general media preview URL. A paid Order line
receives one bound asset with idempotent delivery, and no unknown send is
ever automatically replayed.
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
    """A versioned private file or encrypted license pool for one product."""

    __tablename__ = "shop_digital_assets"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("shop_products.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(80))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(80))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('file','license')", name="ck_shop_digital_asset_kind",
        ),
        CheckConstraint("version > 0", name="ck_shop_digital_asset_version"),
        CheckConstraint(
            "(kind = 'file' AND storage_key IS NOT NULL "
            "AND size_bytes BETWEEN 1 AND 50000000 "
            "AND length(checksum_sha256) = 64) OR "
            "(kind = 'license' AND storage_key IS NULL)",
            name="ck_shop_digital_asset_fields",
        ),
        Index(
            "uq_shop_active_digital_asset",
            "store_id", "product_id", unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = 1"),
        ),
    )


class ShopDigitalDelivery(Base):
    """One provider-bound delivery attempt per paid OrderLine; terminal on unknown."""

    __tablename__ = "shop_digital_deliveries"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("shop_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    order_line_id: Mapped[int] = mapped_column(
        ForeignKey("shop_order_lines.id", ondelete="RESTRICT"),
        nullable=False, unique=True,
    )
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("shop_digital_assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    asset_sha256_snapshot: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued",
    )
    provider_message_id: Mapped[int | None] = mapped_column(BigInteger)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    failure_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "platform IN ('telegram','bale')",
            name="ck_shop_digital_delivery_platform",
        ),
        CheckConstraint(
            "status IN ('queued','sending','delivered','needs_review','blocked')",
            name="ck_shop_digital_delivery_status",
        ),
        CheckConstraint(
            "quantity BETWEEN 1 AND 99",
            name="ck_shop_digital_delivery_quantity",
        ),
        Index(
            "ix_shop_digital_queue", "bot_id", "status", "id",
        ),
    )


class ShopDigitalLicenseKey(Base):
    """An encrypted, uniquely fingerprinted one-time code reserved at settlement."""

    __tablename__ = "shop_digital_license_keys"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("shop_digital_assets.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    encrypted_code: Mapped[str] = mapped_column(Text, nullable=False)
    code_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False,
    )
    delivery_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_digital_deliveries.id", ondelete="RESTRICT"),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="available",
        server_default="available",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "store_id", "code_fingerprint",
            name="uq_shop_digital_license_fingerprint",
        ),
        CheckConstraint(
            "status IN ('available','reserved','delivered')",
            name="ck_shop_digital_license_status",
        ),
        CheckConstraint(
            "(status = 'available' AND delivery_id IS NULL) OR "
            "(status != 'available' AND delivery_id IS NOT NULL)",
            name="ck_shop_digital_license_reserved",
        ),
    )


DIGITAL_DELIVERY_TABLES = frozenset({
    ShopDigitalAsset.__tablename__,
    ShopDigitalDelivery.__tablename__,
    ShopDigitalLicenseKey.__tablename__,
})
