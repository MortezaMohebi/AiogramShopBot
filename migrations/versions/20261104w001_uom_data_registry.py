"""Add reusable units and idempotent external references for data exchange.

Revision ID: 20261104w001
Revises: 20261104v001

Backfill old products to the reference 'piece' unit of their existing Store.
Existing product prices, stock, carts, invoices and wallet balances are not
converted, edited or rounded by this migration.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa

revision: str = "20261104w001"
down_revision: str | None = "20261104v001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNITS = (
    ("count", "تعداد", "piece", "عدد", "عدد", 1, 1, True),
    ("count", "تعداد", "dozen", "دوجین", "دوجین", 12, 1, False),
    ("mass", "جرم", "kg", "کیلوگرم", "kg", 1, 1, True),
    ("mass", "جرم", "g", "گرم", "g", 1, 1000, False),
    ("volume", "حجم", "l", "لیتر", "L", 1, 1, True),
    ("volume", "حجم", "ml", "میلی‌لیتر", "mL", 1, 1000, False),
    ("length", "طول", "m", "متر", "m", 1, 1, True),
    ("length", "طول", "cm", "سانتی‌متر", "cm", 1, 100, False),
)


def _id(store_id: str, key: str) -> str:
    """Build stable Store-specific identifiers without depending on sequences."""
    return str(uuid5(NAMESPACE_URL, f"aiogramshopbot:uom:{store_id}:{key}"))


def upgrade() -> None:
    """Create UoM and import identifiers in a non-destructive transaction."""
    op.create_table(
        "shop_uom_categories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "store_id", sa.String(36),
            sa.ForeignKey("shop_stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.UniqueConstraint(
            "store_id", "code", name="uq_shop_uom_category_store_code",
        ),
    )
    op.create_index(
        "ix_shop_uom_categories_store_id", "shop_uom_categories",
        ["store_id"],
    )
    op.create_table(
        "shop_uoms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "store_id", sa.String(36),
            sa.ForeignKey("shop_stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "category_id", sa.String(36),
            sa.ForeignKey("shop_uom_categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("symbol", sa.String(24), nullable=False),
        sa.Column("ratio_num", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("ratio_den", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rounding", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("is_reference", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.UniqueConstraint("store_id", "code", name="uq_shop_uom_store_code"),
        sa.CheckConstraint(
            "ratio_num BETWEEN 1 AND 1000000000",
            name="ck_shop_uom_ratio_num",
        ),
        sa.CheckConstraint(
            "ratio_den BETWEEN 1 AND 1000000000",
            name="ck_shop_uom_ratio_den",
        ),
        sa.CheckConstraint("rounding > 0", name="ck_shop_uom_rounding"),
        sa.CheckConstraint(
            "NOT is_reference OR (ratio_num = 1 AND ratio_den = 1)",
            name="ck_shop_uom_reference_ratio",
        ),
    )
    op.create_index("ix_shop_uoms_store_id", "shop_uoms", ["store_id"])
    op.create_index("ix_shop_uoms_category_id", "shop_uoms", ["category_id"])
    op.create_index(
        "uq_shop_uom_reference_category", "shop_uoms", ["category_id"],
        unique=True, postgresql_where=sa.text("is_reference = true"),
    )

    connection = op.get_bind()
    for (store_id,) in connection.execute(
        sa.text("SELECT id FROM shop_stores")
    ).all():
        for category_code, category_name, unit, name, symbol, numerator, denominator, is_ref in _UNITS:
            category_id = _id(store_id, f"category:{category_code}")
            connection.execute(sa.text(
                "INSERT INTO shop_uom_categories (id, store_id, code, name) "
                "VALUES (:id, :store_id, :code, :name) "
                "ON CONFLICT (id) DO NOTHING"
            ), {
                "id": category_id, "store_id": store_id,
                "code": category_code, "name": category_name,
            })
            connection.execute(sa.text(
                "INSERT INTO shop_uoms (id, store_id, category_id, code, "
                "name, symbol, ratio_num, ratio_den, rounding, is_reference) "
                "VALUES (:id, :store_id, :category_id, :code, :name, :symbol, "
                ":num, :den, 1, :is_reference) "
                "ON CONFLICT (id) DO NOTHING"
            ), {
                "id": _id(store_id, "piece" if unit == "piece" else f"unit:{unit}"),
                "store_id": store_id, "category_id": category_id,
                "code": unit, "name": name, "symbol": symbol,
                "num": numerator, "den": denominator, "is_reference": is_ref,
            })

    op.add_column("shop_products", sa.Column(
        "uom_id", sa.String(36), nullable=True,
    ))
    op.add_column("shop_products", sa.Column(
        "purchase_uom_id", sa.String(36), nullable=True,
    ))
    op.create_foreign_key(
        "fk_shop_product_uom", "shop_products", "shop_uoms",
        ["uom_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_shop_product_purchase_uom", "shop_products", "shop_uoms",
        ["purchase_uom_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("ix_shop_products_uom_id", "shop_products", ["uom_id"])
    connection.execute(sa.text(
        "UPDATE shop_products AS p SET "
        "uom_id = units.id "
        "FROM shop_uoms AS units "
        "WHERE units.store_id = p.store_id AND units.code = 'piece'"
    ))
    if connection.scalar(sa.text(
        "SELECT COUNT(*) FROM shop_products WHERE uom_id IS NULL"
    )):
        raise RuntimeError("Unresolved product UoM ownership; rollback transaction")
    op.alter_column("shop_products", "uom_id", nullable=False)

    # Legacy paid order lines were quantified as integral individual pieces.
    # Preserve their historical unit, independently of future UoM changes.
    op.add_column("shop_order_lines", sa.Column(
        "uom_code_snapshot", sa.String(32), nullable=False,
        server_default="piece",
    ))

    op.add_column("shop_products", sa.Column("external_ref", sa.String(80)))
    op.add_column(
        "shop_store_customers", sa.Column("external_ref", sa.String(80)),
    )
    connection.execute(sa.text(
        "UPDATE shop_products SET external_ref = 'legacy-product-' || id "
        "WHERE external_ref IS NULL"
    ))
    connection.execute(sa.text(
        "UPDATE shop_store_customers "
        "SET external_ref = 'legacy-customer-' || id "
        "WHERE external_ref IS NULL"
    ))
    op.create_index(
        "uq_shop_product_store_external_ref", "shop_products",
        ["store_id", "external_ref"], unique=True,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )
    op.create_index(
        "uq_shop_customer_store_external_ref", "shop_store_customers",
        ["store_id", "external_ref"], unique=True,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )


def downgrade() -> None:
    """Refuse to strip UoM assignments or external record references."""
    raise RuntimeError(
        "UoM/data exchange migration is data preserving and "
        "cannot be reverted with a destructive downgrade."
    )
