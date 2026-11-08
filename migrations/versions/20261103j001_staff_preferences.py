"""Introduce per-staff work alerts, language and calendar preferences.

Revision ID: 20261103j001
Revises: 20261103i001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261103j001"
down_revision: str | None = "20261103i001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add optional preferences without modifying current sessions or hashes."""
    op.create_table(
        "shop_staff_preferences",
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("shop_staff.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("calendar", sa.String(16), nullable=False, server_default="auto"),
        sa.Column("language", sa.String(8), nullable=False, server_default="fa"),
        sa.Column("notify_orders", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notify_campaigns", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notify_finance", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notify_system", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("calendar IN ('auto','jalali','gregorian')", name="ck_staff_calendar"),
        sa.CheckConstraint("language IN ('fa','en')", name="ck_staff_ui_language"),
    )


def downgrade() -> None:
    """Remove only the optional preferences table on reviewed rollback."""
    op.drop_table("shop_staff_preferences")
