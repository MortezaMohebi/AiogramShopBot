"""Add per-bot product/category entitlements without altering legacy data.

Revision ID: 20261103r001
Revises: 20261103q001

The absence of ACL rows preserves legacy bot visibility; registry-owned bots
default to deny. No existing product, order, wallet, media or cart rows change.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261103r001"
down_revision: str | None = "20261103q001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create three additive ACL tables and lookup indexes, no data rewrite."""
    op.create_table(
        "shop_bot_product_rules",
        sa.Column(
            "bot_id", sa.String(36),
            sa.ForeignKey("shop_bots.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "product_id", sa.Integer(),
            sa.ForeignKey("shop_products.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("effect", sa.String(5), nullable=False),
        sa.Column(
            "updated_by", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "effect IN ('allow','deny')", name="ck_bot_product_effect",
        ),
    )
    op.create_index(
        "ix_shop_bot_product_rules_product_id",
        "shop_bot_product_rules", ["product_id"],
    )
    op.create_table(
        "shop_bot_category_rules",
        sa.Column(
            "bot_id", sa.String(36),
            sa.ForeignKey("shop_bots.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "category_id", sa.Integer(),
            sa.ForeignKey("shop_categories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("effect", sa.String(5), nullable=False),
        sa.Column(
            "updated_by", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "effect IN ('allow','deny')", name="ck_bot_category_effect",
        ),
    )
    op.create_index(
        "ix_shop_bot_category_rules_category_id",
        "shop_bot_category_rules", ["category_id"],
    )
    op.create_table(
        "shop_bot_catalog_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "bot_id", sa.String(36),
            sa.ForeignKey("shop_bots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("object_type", sa.String(8), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("old_effect", sa.String(7), nullable=False),
        sa.Column("new_effect", sa.String(7), nullable=False),
        sa.Column(
            "actor_id", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "object_type IN ('product','category')",
            name="ck_bot_acl_audit_object_type",
        ),
        sa.CheckConstraint(
            "old_effect IN ('allow','deny','inherit')",
            name="ck_bot_acl_audit_old",
        ),
        sa.CheckConstraint(
            "new_effect IN ('allow','deny','inherit')",
            name="ck_bot_acl_audit_new",
        ),
    )
    op.create_index(
        "ix_shop_bot_catalog_audit_bot_id",
        "shop_bot_catalog_audit", ["bot_id"],
    )


def downgrade() -> None:
    """Refuse unreviewed destructive rollback of published ACL decisions."""
    raise RuntimeError(
        "Bot catalog access history is protected. Preserve and review ACL "
        "data before any explicit downgrade."
    )
