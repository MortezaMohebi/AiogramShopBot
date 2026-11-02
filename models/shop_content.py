"""Independent, editable catalog metadata shared across messaging platforms."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqladmin import ModelView

from models.base import Base


class Product(Base):
    """A real product, independent from individual legacy stock items."""

    __tablename__ = "shop_products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_shop_product_price"),
        CheckConstraint("stock_quantity >= 0", name="ck_shop_product_stock"),
    )

    def __repr__(self) -> str:
        """Display the product name in administrative forms."""
        return self.name


class ProductMedia(Base):
    """Multiple files per product, stored independently of Telegram file IDs."""

    __tablename__ = "shop_product_media"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("shop_products.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    caption: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (
        CheckConstraint("kind IN ('photo', 'video', 'audio', 'document')", name="ck_shop_media_kind"),
    )


class Testimonial(Base):
    """Product-specific customer testimonial with publication approval."""

    __tablename__ = "shop_testimonials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("shop_products.id"), nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    media_storage_key: Mapped[str | None] = mapped_column(String(512))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (
        CheckConstraint("text IS NOT NULL OR media_storage_key IS NOT NULL", name="ck_shop_testimonial_content"),
    )


class ProductAdmin(ModelView, model=Product):
    """Provide product CRUD without changing legacy checkout tables."""

    name = "محصول"
    name_plural = "محصولات"
    category = "کاتالوگ"
    column_searchable_list = [Product.name, Product.sku]
    column_labels = {
        Product.sku: "کد محصول", Product.name: "نام محصول",
        Product.description: "توضیحات", Product.price: "قیمت",
        Product.stock_quantity: "موجودی", Product.position: "ترتیب نمایش",
        Product.is_published: "منتشر شده",
    }
    can_delete = False


class ProductMediaAdmin(ModelView, model=ProductMedia):
    """Manage original file metadata for each product."""

    name = "رسانه محصول"
    name_plural = "رسانه‌های محصول"
    category = "محتوا"
    column_labels = {
        ProductMedia.product_id: "محصول", ProductMedia.kind: "نوع رسانه",
        ProductMedia.storage_key: "مسیر فایل اصلی",
        ProductMedia.caption: "توضیح", ProductMedia.position: "ترتیب",
        ProductMedia.is_published: "منتشر شده",
    }


class TestimonialAdmin(ModelView, model=Testimonial):
    """Manage published and unpublished testimonials."""

    name = "رضایت مشتری"
    name_plural = "رضایت مشتریان"
    category = "محتوا"
    column_labels = {
        Testimonial.product_id: "محصول", Testimonial.text: "متن",
        Testimonial.media_storage_key: "مسیر رسانه",
        Testimonial.position: "ترتیب", Testimonial.is_approved: "تأیید شده",
    }
