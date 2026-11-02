"""Replace draft-only catalogue tables with integral-rial structures.

Revision ID: 20261102a001
Revises: 91c3856a8aa0

This migration was introduced in an unmerged, unexecuted draft branch. Keep
all existing legacy Item/Buy/Payment records untouched when applying it.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261102a001"
down_revision: Union[str, None] = "91c3856a8aa0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the independent product, media, testimonial and order tables."""
    op.create_table(
        "shop_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("brand_name", sa.String(255)),
        sa.Column("welcome_message", sa.Text),
        sa.Column("faq_text", sa.Text),
        sa.Column("support_url", sa.String(500)),
        sa.CheckConstraint("id = 1", name="ck_shop_settings_singleton"),
    )
    op.create_table(
        "shop_categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_published", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "shop_products",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sku", sa.String(64), nullable=False, unique=True),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("shop_categories.id", ondelete="SET NULL")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("price", sa.BigInteger, nullable=False),
        sa.Column("stock_quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_published", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint("price >= 0", name="ck_shop_product_price"),
        sa.CheckConstraint("stock_quantity >= 0", name="ck_shop_product_stock"),
    )
    op.create_table(
        "shop_product_media",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("shop_products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("storage_key", sa.String(80), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("caption", sa.Text),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_published", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint("kind IN ('photo', 'video', 'audio', 'document')", name="ck_shop_media_kind"),
        sa.CheckConstraint("size_bytes > 0", name="ck_shop_media_nonempty"),
        sa.UniqueConstraint("storage_key", name="uq_shop_media_storage_key"),
    )
    op.create_table(
        "shop_testimonials",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("shop_products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("text", sa.Text),
        sa.Column("media_storage_key", sa.String(80)),
        sa.Column("media_kind", sa.String(16)),
        sa.Column("media_mime_type", sa.String(80)),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_approved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint("text IS NOT NULL OR media_storage_key IS NOT NULL", name="ck_shop_testimonial_content"),
    )
    op.create_table(
        "shop_orders",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("platform", sa.String(12), nullable=False),
        sa.Column("platform_user_id", sa.BigInteger, nullable=False),
        sa.Column("chat_id", sa.BigInteger, nullable=False),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("shop_products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_name_snapshot", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price_irr", sa.BigInteger, nullable=False),
        sa.Column("total_irr", sa.BigInteger, nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("invoice_payload", sa.String(128), nullable=False, unique=True),
        sa.Column("telegram_payment_charge_id", sa.String(128), unique=True),
        sa.Column("provider_payment_charge_id", sa.String(128), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("platform IN ('telegram', 'bale')", name="ck_shop_order_platform"),
        sa.CheckConstraint("quantity > 0", name="ck_shop_order_qty_positive"),
        sa.CheckConstraint("unit_price_irr >= 0", name="ck_shop_order_price_positive"),
        sa.CheckConstraint("total_irr > 0", name="ck_shop_order_total_positive"),
        sa.CheckConstraint("status IN ('pending_payment','paid','paid_unfulfilled','cancelled')", name="ck_shop_order_status"),
    )
    op.create_index(
        "ix_shop_orders_customer", "shop_orders",
        ["platform", "platform_user_id", "created_at"],
    )


def downgrade() -> None:
    """Drop only new tables, not the pre-existing sales and payment records."""
    op.drop_index("ix_shop_orders_customer", table_name="shop_orders")
    op.drop_table("shop_orders")
    op.drop_table("shop_testimonials")
    op.drop_table("shop_product_media")
    op.drop_table("shop_products")
    op.drop_table("shop_categories")
    op.drop_table("shop_settings")
