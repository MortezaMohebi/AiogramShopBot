"""Record explicit staff suspended/disabled states without altering ShopStaff.

Revision ID: 20261103n001
Revises: 20261103m001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261103n001"
down_revision: str | None = "20261103m001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add lifecycle metadata, preserving login and historic staff accounts."""
    op.create_table(
        "shop_staff_states",
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("shop_staff.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("shop_staff.id", ondelete="SET NULL")),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('active','suspended','disabled')",
            name="ck_staff_lifecycle_status",
        ),
    )


def downgrade() -> None:
    """Remove only metadata on explicit rollback, leaving account flags intact."""
    op.drop_table("shop_staff_states")
