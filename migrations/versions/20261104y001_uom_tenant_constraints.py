"""Enforce Store ownership of UoM assignment at the database boundary.

Revision ID: 20261104y001
Revises: 20261104x001

The composite foreign keys prevent cross-Store unit/category references
even when a future admin, import service or raw SQL caller bypasses the
Python validation layer. Existing data is checked before adding constraints.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261104y001"
down_revision: str | None = "20261104x001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add non-destructive tenant constraints after verifying legacy rows."""
    conn = op.get_bind()
    bad_categories = int(conn.scalar(sa.text(
        "SELECT count(*) FROM shop_uoms AS u "
        "LEFT JOIN shop_uom_categories AS c ON c.id = u.category_id "
        "AND c.store_id = u.store_id "
        "WHERE c.id IS NULL"
    )) or 0)
    bad_sales = int(conn.scalar(sa.text(
        "SELECT count(*) FROM shop_products AS p "
        "LEFT JOIN shop_uoms AS u ON u.id = p.uom_id "
        "AND u.store_id = p.store_id "
        "WHERE u.id IS NULL"
    )) or 0)
    bad_purchase = int(conn.scalar(sa.text(
        "SELECT count(*) FROM shop_products AS p "
        "LEFT JOIN shop_uoms AS u ON u.id = p.purchase_uom_id "
        "AND u.store_id = p.store_id "
        "WHERE p.purchase_uom_id IS NOT NULL AND u.id IS NULL"
    )) or 0)
    if bad_categories or bad_sales or bad_purchase:
        raise RuntimeError(
            "Cross-Store unit data detected; refusing UoM tenant migration "
            f"({bad_categories}/{bad_sales}/{bad_purchase})."
        )
    op.create_unique_constraint(
        "uq_shop_uom_category_store_id", "shop_uom_categories",
        ["store_id", "id"],
    )
    op.create_unique_constraint(
        "uq_shop_uom_store_id", "shop_uoms", ["store_id", "id"],
    )
    op.create_foreign_key(
        "fk_shop_uom_category_store",
        "shop_uoms", "shop_uom_categories",
        ["store_id", "category_id"], ["store_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_shop_product_unit_store",
        "shop_products", "shop_uoms",
        ["store_id", "uom_id"], ["store_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_shop_product_purchase_unit_store",
        "shop_products", "shop_uoms",
        ["store_id", "purchase_uom_id"], ["store_id", "id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Never remove validated tenant boundaries in a destructive rollback."""
    raise RuntimeError(
        "UoM Store foreign keys must be preserved during code rollback."
    )
