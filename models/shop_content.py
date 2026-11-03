"""Independent product, media, testimonial and sales data for both bots.

Legacy cryptocurrency transactions and Telegram-only inventory remain intact.
All new catalogue prices are stored as integral Iranian rials (IRR).
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer,
    String, Text, UniqueConstraint, func, Index, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqladmin import ModelView
from markupsafe import Markup, escape

from models.base import Base
from models.shop_scope import legacy_bot_default
from models.shop_multibot import DEFAULT_STORE_ID
from models.shop_uom import default_unit_id


class ShopSettings(Base):
    """Editable brand and help texts, avoiding hardcoded shop information."""

    __tablename__ = "shop_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    brand_name: Mapped[str | None] = mapped_column(String(255))
    welcome_message: Mapped[str | None] = mapped_column(Text)
    faq_text: Mapped[str | None] = mapped_column(Text)
    support_url: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_shop_settings_singleton"),
    )

    def __repr__(self) -> str:
        """Show the current shop brand in SQLAdmin."""
        return self.brand_name or "تنظیمات فروشگاه"


class ShopCategory(Base):
    """Dynamic category configured entirely through SQLAdmin."""

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
            "price_stars IS NULL OR price_stars > 0",
            name="ck_shop_product_price_stars",
        ),
        CheckConstraint(
            "product_type != 'digital' OR requires_shipping = false",
            name="ck_shop_digital_no_shipping",
        ),
    )

    def __repr__(self) -> str:
        """Display the product name in SQLAdmin."""
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
        nullable=False, default=legacy_bot_default, index=True,
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

    The customer's identity is `(platform, platform_user_id)`; identifiers
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
        nullable=False, default=legacy_bot_default, index=True,
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
    checkout_key: Mapped[str | None] = mapped_column(String(80), unique=True)
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
        CheckConstraint("total_irr > 0", name="ck_shop_order_total_positive"),
        CheckConstraint(
            "status IN ('pending_review','approved_unpaid','pending_payment','paid','paid_unfulfilled','cancelled','refunded')",
            name="ck_shop_order_status",
        ),
    )

    def __repr__(self) -> str:
        """Identify the order in administrative forms."""
        return f"Order #{self.id}"


class ShopSettingsAdmin(ModelView, model=ShopSettings):
    """Manage customer-facing welcome, help and FAQ copy."""

    name = "تنظیم فروشگاه"
    name_plural = "اطلاعات و پشتیبانی"
    category = "تنظیمات"
    icon = "fa-solid fa-gear"
    column_labels = {
        ShopSettings.brand_name: "نام فروشگاه",
        ShopSettings.welcome_message: "پیام خوش‌آمد",
        ShopSettings.faq_text: "پرسش‌های متداول",
        ShopSettings.support_url: "لینک پشتیبانی",
    }
    can_delete = False


class ShopCategoryAdmin(ModelView, model=ShopCategory):
    """CRUD for user-defined categories; never a static Enum."""

    name = "دسته‌بندی"
    name_plural = "دسته‌بندی‌های فروشگاه"
    category = "کاتالوگ"
    icon = "fa-solid fa-layer-group"
    column_list = [
        ShopCategory.id, ShopCategory.name, ShopCategory.position,
        ShopCategory.is_published,
    ]
    column_searchable_list = [ShopCategory.name]
    column_sortable_list = [ShopCategory.position, ShopCategory.name]
    column_labels = {
        ShopCategory.name: "نام دسته‌بندی",
        ShopCategory.position: "ترتیب نمایش",
        ShopCategory.is_published: "انتشار",
    }
    can_delete = False


class ProductAdmin(ModelView, model=Product):
    """Manage the product catalogue without modifying old sales data."""

    name = "محصول"
    name_plural = "محصولات"
    category = "کاتالوگ"
    icon = "fa-solid fa-box"
    column_list = [
        Product.id, Product.name, Product.sku, Product.category_id, Product.price,
        Product.stock_quantity, Product.position, Product.is_published,
    ]
    column_searchable_list = [Product.name, Product.sku]
    column_sortable_list = [Product.position, Product.price, Product.id]
    column_labels = {
        Product.sku: "کد محصول",
        Product.category_id: "دسته‌بندی",
        Product.name: "نام محصول",
        Product.description: "توضیحات",
        Product.price: "قیمت (ریال)",
        Product.stock_quantity: "موجودی",
        Product.requires_shipping: "نیازمند نشانی و ارسال",
        Product.product_type: "نوع محصول (physical/digital)",
        Product.price_stars: "قیمت Telegram Stars",
        Product.position: "ترتیب",
        Product.is_published: "انتشار",
    }
    # Orders retain snapshots; hide products instead of physical deletion.
    can_delete = False


def _media_link(record: ProductMedia, attribute: str) -> Markup:
    """Link a trusted upload record to its authenticated preview route."""
    title = escape(record.original_filename)
    return Markup(
        f'<a href="/admin/media-preview/product/{record.id}">{title}</a>'
    )


def _testimonial_media_link(record: Testimonial, attribute: str) -> Markup | str:
    """Show a protected preview only for uploaded testimonial files."""
    if not record.media_storage_key:
        return "—"
    return Markup(
        f'<a href="/admin/media-preview/testimonial/{record.id}">'
        "مشاهده فایل</a>"
    )


class ProductMediaAdmin(ModelView, model=ProductMedia):
    """Read-only metadata; upload only through the validated manager form."""

    name = "رسانه محصول"
    name_plural = "رسانه‌های محصول"
    category = "محتوا"
    icon = "fa-solid fa-images"
    column_list = [
        ProductMedia.id, ProductMedia.product_id, ProductMedia.kind,
        ProductMedia.original_filename, ProductMedia.position,
        ProductMedia.is_published,
    ]
    column_formatters = {
        ProductMedia.original_filename: _media_link,
    }
    column_labels = {
        ProductMedia.product_id: "محصول",
        ProductMedia.kind: "نوع رسانه",
        ProductMedia.original_filename: "فایل",
        ProductMedia.storage_key: "شناسه داخلی فایل",
        ProductMedia.mime_type: "نوع فایل",
        ProductMedia.caption: "توضیح",
        ProductMedia.position: "ترتیب",
        ProductMedia.is_published: "انتشار",
    }
    # Prevent arbitrary filesystem paths from being entered in generic CRUD.
    can_create = False
    can_edit = True
    can_delete = False
    form_columns = [
        ProductMedia.caption, ProductMedia.position, ProductMedia.is_published,
    ]


class TestimonialAdmin(ModelView, model=Testimonial):
    """Moderate customer content; file paths are never directly editable."""

    name = "رضایت مشتری"
    name_plural = "رضایت مشتریان"
    category = "محتوا"
    icon = "fa-solid fa-comment"
    column_list = [
        Testimonial.id, Testimonial.product_id, Testimonial.text,
        Testimonial.media_storage_key, Testimonial.position,
        Testimonial.is_approved,
    ]
    column_formatters = {
        Testimonial.media_storage_key: _testimonial_media_link,
    }
    column_labels = {
        Testimonial.product_id: "محصول",
        Testimonial.text: "متن",
        Testimonial.media_storage_key: "شناسه داخلی رسانه",
        Testimonial.position: "ترتیب",
        Testimonial.is_approved: "تأیید انتشار",
    }
    can_create = False
    can_edit = True
    can_delete = False
    form_columns = [
        Testimonial.text, Testimonial.position, Testimonial.is_approved,
    ]


class ShopIdentityAdmin(ModelView, model=ShopIdentity):
    """Manage Telegram and Bale customers without conflating their IDs."""

    name = "مشتری"
    name_plural = "مشتریان پیام‌رسان‌ها"
    category = "مشتریان"
    icon = "fa-solid fa-users"
    column_list = [
        ShopIdentity.id, ShopIdentity.platform, ShopIdentity.platform_user_id,
        ShopIdentity.username, ShopIdentity.is_blocked,
        ShopIdentity.allow_announcements,
    ]
    column_labels = {
        ShopIdentity.platform: "پیام‌رسان",
        ShopIdentity.platform_user_id: "شناسه کاربر",
        ShopIdentity.username: "نام کاربری",
        ShopIdentity.first_name: "نام",
        ShopIdentity.is_blocked: "مسدود",
        ShopIdentity.allow_announcements: "رضایت دریافت اعلان",
        ShopIdentity.registered_at: "تاریخ عضویت",
    }
    form_columns = [
        ShopIdentity.is_blocked,
    ]
    can_create = False
    can_delete = False


class ShopOrderAdmin(ModelView, model=ShopOrder):
    """Review payment status; never override provider-confirmed transactions."""

    name = "سفارش"
    name_plural = "سفارش‌های دو پیام‌رسان"
    category = "فروش"
    icon = "fa-solid fa-receipt"
    column_list = [
        ShopOrder.id, ShopOrder.platform, ShopOrder.product_name_snapshot,
        ShopOrder.total_irr, ShopOrder.status, ShopOrder.created_at,
    ]
    column_labels = {
        ShopOrder.platform: "پیام‌رسان",
        ShopOrder.platform_user_id: "شناسه خریدار",
        ShopOrder.product_name_snapshot: "نام محصول",
        ShopOrder.quantity: "تعداد",
        ShopOrder.subtotal_irr: "جمع کالاها (ریال)",
        ShopOrder.discount_irr: "تخفیف (ریال)",
        ShopOrder.shipping_irr: "هزینه ارسال (ریال)",
        ShopOrder.shipping_address: "نشانی ارسال",
        ShopOrder.shipping_method_snapshot: "روش ارسال",
        ShopOrder.coupon_code_snapshot: "کد تخفیف",
        ShopOrder.payment_currency: "ارز پرداخت",
        ShopOrder.payment_amount: "مبلغ در واحد API",
        ShopOrder.total_irr: "مبلغ (ریال)",
        ShopOrder.provider: "روش پرداخت",
        ShopOrder.status: "وضعیت",
        ShopOrder.created_at: "تاریخ ثبت",
    }
    can_create = False
    can_edit = False
    can_delete = False

# Resolve string-based SQLAlchemy relationships even when callers import only
# models.shop_content (e.g., isolated catalogue unit tests).
from models import shop_checkout as _shop_checkout  # noqa: F401,E402
