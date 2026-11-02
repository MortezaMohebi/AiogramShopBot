"""Create shared checkout tables alongside the preserved legacy shop.

Revision ID: 20261102b001
Revises: 20261102a001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261102b001"
down_revision: Union[str, None] = "20261102a001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the independent cart, coupon, shipping and snapshot tables."""
    op.add_column(
        "shop_products",
        sa.Column(
            "requires_shipping", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column("shop_orders", sa.Column("checkout_key", sa.String(80)))
    op.create_unique_constraint(
        "uq_shop_order_checkout_key", "shop_orders", ["checkout_key"]
    )
    for column in ("subtotal_irr", "discount_irr", "shipping_irr"):
        op.add_column("shop_orders", sa.Column(column, sa.BigInteger()))
    op.add_column("shop_orders", sa.Column("shipping_address", sa.String(500)))
    op.add_column(
        "shop_orders", sa.Column("shipping_method_snapshot", sa.String(120))
    )
    op.add_column(
        "shop_orders", sa.Column("coupon_code_snapshot", sa.String(32))
    )
    op.drop_constraint("ck_shop_order_status", "shop_orders", type_="check")
    op.create_check_constraint(
        "ck_shop_order_status", "shop_orders",
        "status IN ('pending_review','pending_payment','paid',"
        "'paid_unfulfilled','cancelled')",
    )

    op.create_table(
        "shop_shipping_methods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("price_irr", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
        sa.CheckConstraint("price_irr >= 0", name="ck_shop_shipping_price"),
    )
    op.create_table(
        "shop_coupons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("discount_type", sa.String(12), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column(
            "minimum_subtotal_irr", sa.BigInteger(), nullable=False,
            server_default="0",
        ),
        sa.Column("max_uses", sa.Integer()),
        sa.Column(
            "used_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
        sa.CheckConstraint(
            "discount_type IN ('percent','fixed')",
            name="ck_shop_coupon_type",
        ),
        sa.CheckConstraint("value > 0", name="ck_shop_coupon_value"),
        sa.CheckConstraint(
            "discount_type != 'percent' OR value <= 100",
            name="ck_shop_coupon_percent",
        ),
        sa.CheckConstraint(
            "minimum_subtotal_irr >= 0", name="ck_shop_coupon_minimum"
        ),
        sa.CheckConstraint("used_count >= 0", name="ck_shop_coupon_usage"),
        sa.CheckConstraint(
            "max_uses IS NULL OR max_uses > 0", name="ck_shop_coupon_max_uses"
        ),
    )
    op.create_index(
        "uq_shop_coupon_code_casefold",
        "shop_coupons",
        [sa.text("upper(code)")],
        unique=True,
    )
    op.create_table(
        "shop_carts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(12), nullable=False),
        sa.Column("platform_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("shipping_address", sa.String(500)),
        sa.Column(
            "shipping_method_id", sa.Integer(),
            sa.ForeignKey("shop_shipping_methods.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "coupon_id", sa.Integer(),
            sa.ForeignKey("shop_coupons.id", ondelete="SET NULL"),
        ),
        sa.Column("awaiting_input", sa.String(12)),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "platform", "platform_user_id", name="uq_shop_cart_owner"
        ),
        sa.CheckConstraint(
            "platform IN ('telegram','bale')", name="ck_shop_cart_platform"
        ),
        sa.CheckConstraint(
            "awaiting_input IS NULL OR awaiting_input IN ('address','coupon')",
            name="ck_shop_cart_input",
        ),
        sa.CheckConstraint("revision > 0", name="ck_shop_cart_revision"),
    )
    op.create_table(
        "shop_cart_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "cart_id", sa.Integer(),
            sa.ForeignKey("shop_carts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id", sa.Integer(),
            sa.ForeignKey("shop_products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "cart_id", "product_id", name="uq_shop_cart_product"
        ),
        sa.CheckConstraint(
            "quantity BETWEEN 1 AND 99", name="ck_shop_cart_item_quantity"
        ),
    )
    op.create_table(
        "shop_order_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "order_id", sa.BigInteger(),
            sa.ForeignKey("shop_orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "product_id", sa.Integer(),
            sa.ForeignKey("shop_products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("product_name_snapshot", sa.String(255), nullable=False),
        sa.Column("sku_snapshot", sa.String(64), nullable=False),
        sa.Column("unit_price_irr", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("total_irr", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint(
            "order_id", "product_id", name="uq_shop_order_product"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_shop_order_line_qty"),
        sa.CheckConstraint(
            "unit_price_irr >= 0", name="ck_shop_order_line_unit_price"
        ),
        sa.CheckConstraint("total_irr >= 0", name="ck_shop_order_line_total"),
    )


def downgrade() -> None:
    """Remove only this phase's checkout schema."""
    op.drop_table("shop_order_lines")
    op.drop_table("shop_cart_items")
    op.drop_table("shop_carts")
    op.drop_index("uq_shop_coupon_code_casefold", table_name="shop_coupons")
    op.drop_table("shop_coupons")
    op.drop_table("shop_shipping_methods")
    op.drop_constraint("ck_shop_order_status", "shop_orders", type_="check")
    op.create_check_constraint(
        "ck_shop_order_status", "shop_orders",
        "status IN ('pending_payment','paid','paid_unfulfilled','cancelled')",
    )
    for column in ("coupon_code_snapshot", "shipping_method_snapshot",
                   "shipping_address", "shipping_irr", "discount_irr",
                   "subtotal_irr"):
        op.drop_column("shop_orders", column)
    op.drop_constraint(
        "uq_shop_order_checkout_key", "shop_orders", type_="unique"
    )
    op.drop_column("shop_orders", "checkout_key")
    op.drop_column("shop_products", "requires_shipping")
