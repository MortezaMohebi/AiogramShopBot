"""Add per-user Store access and per-session concurrent Store selection.

Revision ID: 20261104v001
Revises: 20261104u001

All pre-existing staff retain access to the original default Store. Newly
invited staff require explicit authorization. Existing financial/customer
records and active session tokens are preserved; no Store is auto-activated.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261104v001"
down_revision: str | None = "20261104u001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Backfill only the legacy Store's explicitly authorized staff."""
    connection = op.get_bind()
    store_id = connection.scalar(sa.text(
        "SELECT id FROM shop_stores WHERE slug = 'default'"
    ))
    if not store_id:
        raise RuntimeError("Default Store is missing; refusing staff access migration")

    op.create_table(
        "shop_staff_store_access",
        sa.Column("staff_id", sa.Integer(),
                  sa.ForeignKey("shop_staff.id", ondelete="RESTRICT"),
                  primary_key=True),
        sa.Column("store_id", sa.String(36),
                  sa.ForeignKey("shop_stores.id", ondelete="RESTRICT"),
                  primary_key=True),
        sa.Column("access_level", sa.String(12), nullable=False,
                  server_default="viewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("changed_by", sa.Integer(),
                  sa.ForeignKey("shop_staff.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "access_level IN ('viewer','editor','manager')",
            name="ck_staff_store_access_level",
        ),
    )
    op.create_table(
        "shop_staff_store_preferences",
        sa.Column("staff_id", sa.Integer(),
                  sa.ForeignKey("shop_staff.id", ondelete="RESTRICT"),
                  primary_key=True),
        sa.Column("default_store_id", sa.String(36),
                  sa.ForeignKey("shop_stores.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("version", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.CheckConstraint(
            "version > 0", name="ck_staff_store_pref_version",
        ),
    )
    op.create_table(
        "shop_admin_session_stores",
        sa.Column("session_id", sa.String(36),
                  sa.ForeignKey("shop_admin_sessions.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("store_id", sa.String(36),
                  sa.ForeignKey("shop_stores.id", ondelete="RESTRICT"),
                  primary_key=True),
    )
    op.add_column("shop_admin_sessions", sa.Column(
        "current_store_id", sa.String(36), nullable=True,
    ))
    op.add_column("shop_admin_sessions", sa.Column(
        "store_context_version", sa.Integer(), nullable=False,
        server_default="1",
    ))
    op.create_foreign_key(
        "fk_admin_session_current_store", "shop_admin_sessions",
        "shop_stores", ["current_store_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_admin_session_store_context_version",
        "shop_admin_sessions", "store_context_version > 0",
    )

    connection.execute(sa.text(
        "INSERT INTO shop_staff_store_access (staff_id, store_id, access_level) "
        "SELECT id, :store_id, "
        "CASE WHEN role = 'superadmin' THEN 'manager' ELSE 'editor' END "
        "FROM shop_staff"
    ), {"store_id": store_id})
    connection.execute(sa.text(
        "INSERT INTO shop_staff_store_preferences (staff_id, default_store_id) "
        "SELECT id, :store_id FROM shop_staff"
    ), {"store_id": store_id})
    connection.execute(sa.text(
        "UPDATE shop_admin_sessions SET current_store_id = :store_id "
        "WHERE current_store_id IS NULL"
    ), {"store_id": store_id})
    connection.execute(sa.text(
        "INSERT INTO shop_admin_session_stores (session_id, store_id) "
        "SELECT id, :store_id FROM shop_admin_sessions"
    ), {"store_id": store_id})

    # Legacy global uniqueness would prohibit identical SKUs, categories and
    # coupons in independent Stores. Scope these constraints to Store.
    op.drop_constraint(
        "shop_categories_name_key", "shop_categories", type_="unique",
    )
    op.create_unique_constraint(
        "uq_shop_category_store_name", "shop_categories",
        ["store_id", "name"],
    )
    op.drop_constraint(
        "shop_products_sku_key", "shop_products", type_="unique",
    )
    op.create_unique_constraint(
        "uq_shop_product_store_sku", "shop_products",
        ["store_id", "sku"],
    )
    op.drop_constraint(
        "shop_shipping_methods_name_key", "shop_shipping_methods",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_shop_shipping_store_name", "shop_shipping_methods",
        ["store_id", "name"],
    )
    op.drop_constraint(
        "shop_coupons_code_key", "shop_coupons", type_="unique",
    )
    op.drop_index(
        "uq_shop_coupon_code_casefold", table_name="shop_coupons",
    )
    op.create_index(
        "uq_shop_coupon_store_code_casefold", "shop_coupons",
        ["store_id", sa.text("upper(code)")], unique=True,
    )

    # Require the user's desired Store and active Store set to be independently
    # checked against live membership on every authenticated API request.


def downgrade() -> None:
    """Protect granted permissions and multi-Store session history from loss."""
    raise RuntimeError(
        "Store context downgrade is non-destructive. Disable in the app and "
        "reconcile user access before an explicitly reviewed rollback."
    )
