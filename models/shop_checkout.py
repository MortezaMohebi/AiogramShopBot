"""Platform-independent shopping cart, discounts, shipping and order lines."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer,
    String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqladmin import ModelView

from models.base import Base


class ShopShippingMethod(Base):
    """Configurable delivery option with exact integer-rial price."""

    __tablename__ = "shop_shipping_methods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    price_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("price_irr >= 0", name="ck_shop_shipping_price"),
    )

    def __repr__(self) -> str:
        """Return a suitable dashboard label."""
        return self.name


class ShopCoupon(Base):
    """Percentage or fixed-amount discount rule, without crypto credit."""

    __tablename__ = "shop_coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
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
        UniqueConstraint("platform", "platform_user_id", name="uq_shop_cart_owner"),
        CheckConstraint(
            "platform IN ('telegram','bale')", name="ck_shop_cart_platform"
        ),
        CheckConstraint(
            "awaiting_input IS NULL OR awaiting_input IN ('address','coupon')",
            name="ck_shop_cart_input",
        ),
        CheckConstraint("revision > 0", name="ck_shop_cart_revision"),
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
    unit_price_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
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
    )


class ShopShippingMethodAdmin(ModelView, model=ShopShippingMethod):
    """Manage the delivery methods available to both messaging platforms."""

    name = "روش ارسال"
    name_plural = "روش‌های ارسال فروشگاه"
    category = "فروش"
    icon = "fa-solid fa-truck"
    column_labels = {
        ShopShippingMethod.name: "عنوان",
        ShopShippingMethod.price_irr: "هزینه (ریال)",
        ShopShippingMethod.position: "ترتیب نمایش",
        ShopShippingMethod.is_active: "فعال",
    }


class ShopCouponAdmin(ModelView, model=ShopCoupon):
    """Edit discount rules without modifying existing purchase history."""

    name = "کد تخفیف"
    name_plural = "کدهای تخفیف فروشگاه"
    category = "بازاریابی"
    icon = "fa-solid fa-tags"
    column_labels = {
        ShopCoupon.code: "کد تخفیف",
        ShopCoupon.discount_type: "نوع: percent یا fixed",
        ShopCoupon.value: "مقدار (درصد یا ریال)",
        ShopCoupon.minimum_subtotal_irr: "حداقل مبلغ (ریال)",
        ShopCoupon.max_uses: "سقف استفاده",
        ShopCoupon.used_count: "تعداد مصرف",
        ShopCoupon.expires_at: "انقضا",
        ShopCoupon.is_active: "فعال",
    }
    form_columns = [
        ShopCoupon.code, ShopCoupon.discount_type, ShopCoupon.value,
        ShopCoupon.minimum_subtotal_irr, ShopCoupon.max_uses,
        ShopCoupon.expires_at, ShopCoupon.is_active,
    ]


class ShopCartAdmin(ModelView, model=ShopCart):
    """Display scoped baskets without allowing staff to alter quantities."""

    name = "سبد خرید"
    name_plural = "سبدهای کاربران"
    category = "فروش"
    can_create = False
    can_edit = False
    can_delete = False


class ShopCartItemAdmin(ModelView, model=ShopCartItem):
    """Show stored basket lines as read-only admin data."""

    name = "قلم سبد"
    name_plural = "اقلام سبد خرید"
    category = "فروش"
    can_create = False
    can_edit = False
    can_delete = False


class ShopOrderLineAdmin(ModelView, model=ShopOrderLine):
    """Show audited line snapshots without allowing price edits."""

    name = "قلم سفارش"
    name_plural = "اقلام سفارش‌های مشترک"
    category = "فروش"
    can_create = False
    can_edit = False
    can_delete = False
