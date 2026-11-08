"""Platform-independent shopping cart, discounts, shipping and order lines."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer,
    Index, String, UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base
from models.shop_multibot import DEFAULT_STORE_ID


class ShopShippingMethod(Base):
    """Configurable delivery option with exact integer-rial price."""

    __tablename__ = "shop_shipping_methods"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, default=DEFAULT_STORE_ID, index=True,
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint(
            "store_id", "name", name="uq_shop_shipping_store_name",
        ),
        CheckConstraint("price_irr >= 0", name="ck_shop_shipping_price"),
    )

    def __repr__(self) -> str:
        """Return a suitable dashboard label."""
        return self.name


class ShopCoupon(Base):
    """Percentage or fixed-amount discount rule, without crypto credit."""

    __tablename__ = "shop_coupons"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, default=DEFAULT_STORE_ID, index=True,
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    discount_type: Mapped[str] = mapped_column(String(12), nullable=False)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    minimum_subtotal_irr: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    max_uses: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint(
            "discount_type IN ('percent','fixed')", name="ck_shop_coupon_type"
        ),
        CheckConstraint("value > 0", name="ck_shop_coupon_value"),
        CheckConstraint(
            "discount_type != 'percent' OR value <= 100",
            name="ck_shop_coupon_percent",
        ),
        CheckConstraint(
            "minimum_subtotal_irr >= 0", name="ck_shop_coupon_minimum"
        ),
        CheckConstraint("used_count >= 0", name="ck_shop_coupon_usage"),
        Index(
            "uq_shop_coupon_store_code_casefold",
            "store_id", func.upper(code), unique=True,
        ),
        CheckConstraint(
            "max_uses IS NULL OR max_uses > 0", name="ck_shop_coupon_max_uses"
        ),
    )

    def __repr__(self) -> str:
        """Display the discount code."""
        return self.code


class ShopCart(Base):
    """One basket for one platform-specific user identity."""

    __tablename__ = "shop_carts"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, default=DEFAULT_STORE_ID, index=True,
    )
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("shop_store_customers.id", ondelete="RESTRICT"),
        index=True,
    )
    is_shared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    platform_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shipping_address: Mapped[str | None] = mapped_column(String(500))
    shipping_method_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_shipping_methods.id", ondelete="SET NULL")
    )
    coupon_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_coupons.id", ondelete="SET NULL")
    )
    awaiting_input: Mapped[str | None] = mapped_column(String(12))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now()
    )
    shipping_method: Mapped[ShopShippingMethod | None] = relationship()
    coupon: Mapped[ShopCoupon | None] = relationship()
    items: Mapped[list["ShopCartItem"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "uq_shop_cart_private_owner", "bot_id", "platform_user_id",
            unique=True, postgresql_where=text("is_shared = false"),
            sqlite_where=text("is_shared = false"),
        ),
        Index(
            "uq_shop_cart_shared_customer", "store_id", "customer_id",
            unique=True, postgresql_where=text("is_shared = true"),
            sqlite_where=text("is_shared = true"),
        ),
        CheckConstraint(
            "NOT is_shared OR customer_id IS NOT NULL",
            name="ck_shop_cart_shared_identity",
        ),
        CheckConstraint(
            "platform IN ('telegram','bale')", name="ck_shop_cart_platform"
        ),
        CheckConstraint(
            "awaiting_input IS NULL OR awaiting_input IN ('address','coupon')",
            name="ck_shop_cart_input",
        ),
        CheckConstraint("revision > 0", name="ck_shop_cart_revision"),
    )


class ShopCartInputSession(Base):
    """Independent chat-form state for a Customer-shared Cart per bot/user."""

    __tablename__ = "shop_cart_input_sessions"

    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    platform_user_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True,
    )
    cart_id: Mapped[int] = mapped_column(
        ForeignKey("shop_carts.id", ondelete="CASCADE"), nullable=False,
    )
    awaiting_input: Mapped[str | None] = mapped_column(String(12))
    __table_args__ = (
        CheckConstraint(
            "awaiting_input IS NULL OR awaiting_input IN ('address','coupon')",
            name="ck_shop_cart_session_input",
        ),
    )


class ShopCartItem(Base):
    """A quantity of an editable product in a customer's basket."""

    __tablename__ = "shop_cart_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cart_id: Mapped[int] = mapped_column(
        ForeignKey("shop_carts.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("shop_products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cart: Mapped[ShopCart] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship("Product")

    __table_args__ = (
        UniqueConstraint("cart_id", "product_id", name="uq_shop_cart_product"),
        CheckConstraint(
            "quantity BETWEEN 1 AND 99", name="ck_shop_cart_item_quantity"
        ),
    )


class ShopCheckoutGroup(Base):
    """One atomic split checkout with two independently payable Orders.

    Its immutable checkout key binds one Bot/customer/cart revision so a
    duplicated callback never constructs two additional payment obligations.
    """

    __tablename__ = "shop_checkout_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform_user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False,
    )
    cart_id: Mapped[int] = mapped_column(
        ForeignKey("shop_carts.id", ondelete="RESTRICT"), nullable=False,
    )
    checkout_key: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True,
    )
    quote_fingerprint: Mapped[str] = mapped_column(
        String(12), nullable=False,
    )
    terms_version_snapshot: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "length(checkout_key) = 64",
            name="ck_shop_checkout_group_key",
        ),
        CheckConstraint(
            "length(quote_fingerprint) = 12",
            name="ck_shop_checkout_group_proof",
        ),
        Index(
            "ix_shop_checkout_group_owner",
            "store_id", "bot_id", "platform_user_id",
        ),
    )


class ShopOrderLine(Base):
    """Immutable product/price snapshots belonging to an order."""

    __tablename__ = "shop_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("shop_orders.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("shop_products.id", ondelete="RESTRICT"), nullable=False
    )
    product_name_snapshot: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    sku_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    uom_code_snapshot: Mapped[str] = mapped_column(
        String(32), nullable=False, default="piece", server_default="piece",
    )
    unit_price_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_price_stars_snapshot: Mapped[int | None] = mapped_column(BigInteger)
    # Never swap a customer's purchased file for a later Product upload.
    # NULL for physical Products and one-time license SKUs.
    digital_asset_id_snapshot: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_digital_assets.id", ondelete="RESTRICT"),
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    total_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    order: Mapped["ShopOrder"] = relationship(
        "ShopOrder", back_populates="lines"
    )

    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="uq_shop_order_product"),
        CheckConstraint("quantity > 0", name="ck_shop_order_line_qty"),
        CheckConstraint(
            "unit_price_irr >= 0", name="ck_shop_order_line_unit_price"
        ),
        CheckConstraint("total_irr >= 0", name="ck_shop_order_line_total"),
        CheckConstraint(
            "unit_price_stars_snapshot IS NULL OR "
            "unit_price_stars_snapshot > 0",
            name="ck_shop_order_line_stars",
        ),
    )


class ShopOrderReviewAudit(Base):
    """Append-only administrative decisions on unpaid order requests."""

    __tablename__ = "shop_order_review_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("shop_orders.id", ondelete="RESTRICT"), nullable=False
    )
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    old_status: Mapped[str] = mapped_column(String(24), nullable=False)
    new_status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "action IN ('accept','reject')",
            name="ck_shop_order_review_action",
        ),
    )
