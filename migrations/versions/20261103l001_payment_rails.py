"""Add merchant-editable, fail-closed payment rail activation policy.

Revision ID: 20261103l001
Revises: 20261103k001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261103l001"
down_revision: str | None = "20261103k001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a payment policy registry without changing existing balances."""
    op.create_table(
        "shop_payment_rails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(12), nullable=False),
        sa.Column("rail_type", sa.String(24), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("shop_staff.id", ondelete="SET NULL")),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("platform", "rail_type", name="uq_shop_payment_rail"),
        sa.CheckConstraint(
            "(platform = 'telegram' AND rail_type IN ('store_credit','telegram_fiat','telegram_stars')) "
            "OR (platform = 'bale' AND rail_type IN ('store_credit','bale_wallet'))",
            name="ck_shop_payment_rail_supported",
        ),
        sa.CheckConstraint("length(display_name) BETWEEN 1 AND 80", name="ck_shop_payment_rail_label"),
    )


def downgrade() -> None:
    """Drop only the new policy table; keep financial records intact."""
    op.drop_table("shop_payment_rails")
