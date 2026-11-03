"""Add provider-specific cart and merchant store-credit feature controls.

Revision ID: 20261103h001
Revises: 20261103g001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261103h001"
down_revision: str | None = "20261103g001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add an independent toggle table; keep all existing money and cart rows."""
    op.create_table(
        "shop_channel_features",
        sa.Column("platform", sa.String(12), primary_key=True),
        sa.Column("cart_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("store_credit_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("store_credit_label", sa.String(80), nullable=False, server_default="اعتبار فروشگاه"),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("shop_staff.id", ondelete="SET NULL")),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("platform IN ('telegram','bale')", name="ck_shop_feature_provider"),
        sa.CheckConstraint(
            "char_length(store_credit_label) BETWEEN 1 AND 80",
            name="ck_shop_feature_credit_label",
        ),
    )


def downgrade() -> None:
    """Remove the configuration only during an explicit rollback."""
    op.drop_table("shop_channel_features")
