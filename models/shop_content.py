"""Independent product, media, testimonial and sales data for both bots.

All new catalogue prices are stored as integral Iranian rials (IRR).
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
    ForeignKeyConstraint, Integer, String, Text, UniqueConstraint,
    func, Index, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base
from models.shop_multibot import DEFAULT_STORE_ID
from models.shop_uom import default_unit_id


class ShopCategory(Base):
    """Dynamic Store-owned product category."""

    __tablename__ = "shop_categories"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, default=DEFAULT_STORE_ID, index=True,
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "store_id", "name", name="uq_shop_category_store_name",
        ),
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    products: Mapped[list["Product"]] = relationship(back_populates="category")

    def __repr__(self) -> str:
        """Display the category name in the admin."""
        return self.name


class Product(Base):
    """One editable product, not one database record per unit of stock."""

    __tablename__ = "shop_products"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, default=DEFAULT_STORE_ID, index=True,
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(80))
    uom_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_uoms.id", ondelete="RESTRICT"),
        nullable=False, default=lambda: default_unit_id(DEFAULT_STORE_ID),
        index=True,
    )
    purchase_uom_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_uoms.id", ondelete="RESTRICT"),
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_categories.id", ondelete="SET NULL")
    )
    category: Mapped[ShopCategory | None] = relationship(back_populates="products")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requires_shipping: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    product_type: Mapped[str] = mapped_column(
        String(12), nullable=False, default="physical"
    )
    price_stars: Mapped[int | None] = mapped_column(Integer)
    # File vs one-time license supply is configured only in signed Admin.
    digital_delivery_mode: Mapped[str] = mapped_column(
        String(8), nullable=False, default="none", server_default="none",
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    media: Mapped[list["ProductMedia"]] = relationship(
        back_populates="product", passive_deletes=True
    )
    testimonials: Mapped[list["Testimonial"]] = relationship(
        back_populates="product", passive_deletes=True
    )
    orders: Mapped[list["ShopOrder"]] = relationship(back_populates="product")

    __table_args__ = (
        UniqueConstraint(
            "store_id", "sku", name="uq_shop_product_store_sku",
        ),
        ForeignKeyConstraint(
            ["store_id", "uom_id"],
            ["shop_uoms.store_id", "shop_uoms.id"],
            name="fk_shop_product_unit_store", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["store_id", "purchase_uom_id"],
            ["shop_uoms.store_id", "shop_uoms.id"],
            name="fk_shop_product_purchase_unit_store", ondelete="RESTRICT",
        ),
        Index(
            "uq_shop_product_store_external_ref",
            "store_id", "external_ref", unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
            sqlite_where=text("external_ref IS NOT NULL"),
        ),
        CheckConstraint("price >= 0", name="ck_shop_product_price"),
        CheckConstraint("stock_quantity >= 0", name="ck_shop_product_stock"),
        CheckConstraint(
            "product_type IN ('physical','digital')",
            name="ck_shop_product_type",
        ),
        CheckConstraint(
            "digital_delivery_mode IN ('none','file','license')",
            name="ck_shop_product_digital_mode",
        ),
        CheckConstraint(
            "product_type = 'digital' OR digital_delivery_mode = 'none'",
            name="ck_shop_product_physical_no_delivery",
        ),
        CheckConstraint(
            "price_stars IS NULL OR price_stars > 0",
            name="ck_shop_product_price_stars",
        ),
        CheckConstraint(
            "product_type != 'digital' OR requires_shipping = false",
            name="ck_shop_digital_no_shipping",
        ),
    )

    def __repr__(self) -> str:
        """Return the product display name."""
        return self.name


class ProductMedia(Base):
    """Original private file and visible metadata, irrespective of platform."""

    __tablename__ = "shop_product_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("shop_products.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(80), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    product: Mapped[Product] = relationship(back_populates="media")

    __table_args__ = (
        CheckConstraint(
            "kind IN ('photo', 'video', 'audio', 'document')",
            name="ck_shop_media_kind",
        ),
        CheckConstraint("size_bytes > 0", name="ck_shop_media_nonempty"),
        UniqueConstraint("storage_key", name="uq_shop_media_storage_key"),
    )


class Testimonial(Base):
    """A product-specific customer story, not automatically published."""

    __tablename__ = "shop_testimonials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("shop_products.id", ondelete="RESTRICT"), nullable=False
    )
    text: Mapped[str | None] = mapped_column(Text)
    media_storage_key: Mapped[str | None] = mapped_column(String(80))
    media_kind: Mapped[str | None] = mapped_column(String(16))
    media_mime_type: Mapped[str | None] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    product: Mapped[Product] = relationship(back_populates="testimonials")

    __table_args__ = (
        CheckConstraint(
            "text IS NOT NULL OR media_storage_key IS NOT NULL",
            name="ck_shop_testimonial_content",
        ),
    )


class ShopIdentity(Base):
    """A platform-scoped customer identity with explicit notification opt-in."""

    __tablename__ = "shop_identities"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, default=DEFAULT_STORE_ID, index=True,
    )
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("shop_store_customers.id", ondelete="RESTRICT"),
        index=True,
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    platform_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    is_blocked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    allow_announcements: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("bot_id", "platform_user_id", name="uq_shop_identity_bot_user"),
        CheckConstraint(
            "platform IN ('telegram', 'bale')", name="ck_shop_identity_platform"
        ),
    )

    def __repr__(self) -> str:
        """Show a scoped identifier instead of an ambiguous user ID."""
        return f"{self.platform}:{self.platform_user_id}"


class ShopOrder(Base):
    """Cross-platform order paid via a platform-native payment provider.

    The customer's identity is `(bot_id, platform_user_id)`; identifiers
    from Telegram and Bale must never be assumed globally interchangeable.
    """

    __tablename__ = "shop_orders"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, default=DEFAULT_STORE_ID, index=True,
    )
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("shop_store_customers.id", ondelete="RESTRICT"),
        index=True,
    )
    # PostgreSQL uses BIGINT IDENTITY; SQLite tests use INTEGER PRIMARY KEY.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    platform_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("shop_products.id", ondelete="RESTRICT"), nullable=False
    )
    product: Mapped[Product] = relationship(back_populates="orders")
    product_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Exact customer-approved Telegram Stars total; never derive again
    # from a mutable Product.price_stars at invoice dispatch time.
    total_stars_snapshot: Mapped[int | None] = mapped_column(BigInteger)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending_payment"
    )
    invoice_payload: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )
    telegram_payment_charge_id: Mapped[str | None] = mapped_column(
        String(128), unique=True
    )
    provider_payment_charge_id: Mapped[str | None] = mapped_column(
        String(128), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Proof of the exact Store sales terms accepted at order creation.
    terms_version_snapshot: Mapped[str | None] = mapped_column(String(32))
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    checkout_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    # Null for ordinary Orders; one split group owns exactly one part of
    # each required currency. The part's Bot/provider never changes.
    checkout_group_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_checkout_groups.id", ondelete="RESTRICT"),
        index=True,
    )
    checkout_part_kind: Mapped[str | None] = mapped_column(String(10))
    subtotal_irr: Mapped[int | None] = mapped_column(BigInteger)
    discount_irr: Mapped[int | None] = mapped_column(BigInteger)
    shipping_irr: Mapped[int | None] = mapped_column(BigInteger)
    shipping_address: Mapped[str | None] = mapped_column(String(500))
    shipping_method_snapshot: Mapped[str | None] = mapped_column(String(120))
    coupon_code_snapshot: Mapped[str | None] = mapped_column(String(32))
    coupon_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_coupons.id", ondelete="SET NULL")
    )
    payment_currency: Mapped[str | None] = mapped_column(String(3))
    payment_amount: Mapped[int | None] = mapped_column(BigInteger)
    lines: Mapped[list["ShopOrderLine"]] = relationship(
        "ShopOrderLine", back_populates="order"
    )

    __table_args__ = (
        CheckConstraint(
            "platform IN ('telegram', 'bale')", name="ck_shop_order_platform"
        ),
        CheckConstraint("quantity > 0", name="ck_shop_order_qty_positive"),
        CheckConstraint("unit_price_irr >= 0", name="ck_shop_order_price_positive"),
        CheckConstraint(
            "total_irr > 0 OR (platform = 'telegram' AND "
            "total_irr = 0 AND total_stars_snapshot > 0)",
            name="ck_shop_order_total_positive",
        ),
        UniqueConstraint(
            "checkout_group_id", "checkout_part_kind",
            name="uq_shop_order_split_part",
        ),
        CheckConstraint(
            "(checkout_group_id IS NULL AND checkout_part_kind IS NULL) OR "
            "(checkout_group_id IS NOT NULL AND "
            "checkout_part_kind IN ('physical','digital'))",
            name="ck_shop_order_split_part_kind",
        ),
        CheckConstraint(
            "status IN ('pending_review','approved_unpaid','pending_payment','paid','paid_unfulfilled','cancelled','refunded')",
            name="ck_shop_order_status",
        ),
    )

    def __repr__(self) -> str:
        """Identify the order in administrative forms."""
        return f"Order #{self.id}"


# Resolve string-based SQLAlchemy relationships even when callers import only
# models.shop_content (e.g., isolated catalogue unit tests).
from models import shop_checkout as _shop_checkout  # noqa: F401,E402
