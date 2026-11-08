"""Introduce payment intents, currency snapshots and refund audit records.

Revision ID: 20261102c001
Revises: 20261102b001

Only additive money schema changes are made, except expanding the new shop
order status constraint. Legacy `buy`, `payment` and wallet tables are untouched.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261102c001"
down_revision: Union[str, None] = "20261102b001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the separate Stars price, invoicing and refund ledgers."""
    op.add_column(
        "shop_products",
        sa.Column(
            "product_type", sa.String(12), nullable=False,
            server_default="physical",
        ),
    )
    op.add_column("shop_products", sa.Column("price_stars", sa.Integer()))
    op.create_check_constraint(
        "ck_shop_product_type", "shop_products",
        "product_type IN ('physical','digital')",
    )
    op.create_check_constraint(
        "ck_shop_product_price_stars", "shop_products",
        "price_stars IS NULL OR price_stars > 0",
    )
    op.create_check_constraint(
        "ck_shop_digital_no_shipping", "shop_products",
        "product_type != 'digital' OR requires_shipping = false",
    )

    op.add_column("shop_orders", sa.Column("coupon_id", sa.Integer()))
    op.create_foreign_key(
        "fk_shop_orders_coupon_id", "shop_orders", "shop_coupons",
        ["coupon_id"], ["id"], ondelete="SET NULL",
    )
    op.add_column(
        "shop_orders", sa.Column("payment_currency", sa.String(3))
    )
    op.add_column(
        "shop_orders", sa.Column("payment_amount", sa.BigInteger())
    )
    op.create_check_constraint(
        "ck_shop_order_payment_currency", "shop_orders",
        "payment_currency IS NULL OR payment_currency IN ('IRR','XTR')",
    )
    op.create_check_constraint(
        "ck_shop_order_payment_amount", "shop_orders",
        "payment_amount IS NULL OR payment_amount > 0",
    )
    op.drop_constraint("ck_shop_order_status", "shop_orders", type_="check")
    op.create_check_constraint(
        "ck_shop_order_status", "shop_orders",
        "status IN ('pending_review','approved_unpaid','pending_payment',"
        "'paid','paid_unfulfilled','cancelled','refunded')",
    )

    op.create_table(
        "shop_payment_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "order_id", sa.BigInteger(),
            sa.ForeignKey("shop_orders.id", ondelete="RESTRICT"),
            unique=True, nullable=False,
        ),
        sa.Column("platform", sa.String(12), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "status", sa.String(20), nullable=False,
            server_default="dispatching",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount > 0", name="ck_shop_payment_positive"),
        sa.CheckConstraint(
            "platform IN ('telegram','bale')",
            name="ck_shop_payment_platform",
        ),
        sa.CheckConstraint(
            "provider IN ('bale_wallet','telegram_fiat','telegram_stars')",
            name="ck_shop_payment_provider",
        ),
        sa.CheckConstraint(
            "currency IN ('IRR','XTR')",
            name="ck_shop_payment_currency",
        ),
        sa.CheckConstraint(
            "status IN ('dispatching','invoice_sent','dispatch_unknown',"
            "'paid','refunded')",
            name="ck_shop_payment_status",
        ),
    )
    op.create_table(
        "shop_refund_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "order_id", sa.BigInteger(),
            sa.ForeignKey("shop_orders.id", ondelete="RESTRICT"),
            unique=True, nullable=False,
        ),
        sa.Column(
            "status", sa.String(20), nullable=False,
            server_default="requested",
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("provider_reference", sa.String(128)),
        sa.Column("resolution_note", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('requested','provider_pending','confirmed','rejected')",
            name="ck_shop_refund_case_status",
        ),
    )


def downgrade() -> None:
    """Reverse only the payment schema additions for a fresh draft database."""
    op.drop_table("shop_refund_cases")
    op.drop_table("shop_payment_attempts")
    op.drop_constraint("ck_shop_order_status", "shop_orders", type_="check")
    op.create_check_constraint(
        "ck_shop_order_status", "shop_orders",
        "status IN ('pending_review','approved_unpaid','pending_payment',"
        "'paid','paid_unfulfilled','cancelled')",
    )
    op.drop_constraint(
        "ck_shop_order_payment_amount", "shop_orders", type_="check"
    )
    op.drop_constraint(
        "ck_shop_order_payment_currency", "shop_orders", type_="check"
    )
    op.drop_column("shop_orders", "payment_amount")
    op.drop_column("shop_orders", "payment_currency")
    op.drop_constraint("fk_shop_orders_coupon_id", "shop_orders", type_="foreignkey")
    op.drop_column("shop_orders", "coupon_id")

    for name in (
        "ck_shop_digital_no_shipping",
        "ck_shop_product_price_stars",
        "ck_shop_product_type",
    ):
        op.drop_constraint(name, "shop_products", type_="check")
    op.drop_column("shop_products", "price_stars")
    op.drop_column("shop_products", "product_type")
