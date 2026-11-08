"""Store-owned customer address, wishlist and optional personal preferences.

An address or wishlist belongs to one verified StoreCustomer. A bare
Telegram/Bale numeric user ID cannot resolve another customer's records.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index,
    Integer, String, UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopCustomerAddress(Base):
    """One validated delivery address; financial orders retain snapshots."""

    __tablename__ = "shop_customer_addresses"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shop_store_customers.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    label: Mapped[str] = mapped_column(String(40), nullable=False)
    recipient: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    province: Mapped[str] = mapped_column(String(80), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    full_address: Mapped[str] = mapped_column(String(500), nullable=False)
    postal_code: Mapped[str | None] = mapped_column(String(20))
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        UniqueConstraint(
            "store_id", "customer_id", "label",
            name="uq_customer_address_label",
        ),
        Index(
            "uq_customer_default_address", "store_id", "customer_id",
            unique=True, postgresql_where=text("is_default = true"),
            sqlite_where=text("is_default = true"),
        ),
        CheckConstraint(
            "length(full_address) BETWEEN 10 AND 500",
            name="ck_customer_address_length",
        ),
    )


class ShopCustomerWishlist(Base):
    """A StoreCustomer's explicit bookmark for one Store-owned Product."""

    __tablename__ = "shop_customer_wishlist"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shop_store_customers.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("shop_products.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class ShopCustomerPreference(Base):
    """Customer language preference within one Store, never globally."""

    __tablename__ = "shop_customer_preferences"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shop_store_customers.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="fa", server_default="fa",
    )
    __table_args__ = (
        CheckConstraint(
            "language IN ('fa','en')",
            name="ck_customer_language",
        ),
    )


CUSTOMER_ACCOUNT_TABLES = frozenset({
    ShopCustomerAddress.__tablename__,
    ShopCustomerWishlist.__tablename__,
    ShopCustomerPreference.__tablename__,
})
