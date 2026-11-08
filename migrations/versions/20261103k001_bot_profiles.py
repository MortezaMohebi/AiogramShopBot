"""Add verified bot profiles and independent maintenance/receiver policy.

Revision ID: 20261103k001
Revises: 20261103j001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261103k001"
down_revision: str | None = "20261103j001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add non-secret provider settings, preserving configured webhook state."""
    op.create_table(
        "shop_bot_profiles",
        sa.Column("platform", sa.String(12), primary_key=True),
        sa.Column("provider_bot_id", sa.BigInteger()),
        sa.Column("provider_username", sa.String(255)),
        sa.Column("display_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("owner_staff_id", sa.Integer(), sa.ForeignKey("shop_staff.id", ondelete="SET NULL")),
        sa.Column("environment", sa.String(16), nullable=False, server_default="staging"),
        sa.Column("maintenance_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("request_timeout_seconds", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("poll_timeout_seconds", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("allowed_updates_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("platform IN ('telegram','bale')", name="ck_bot_profile_platform"),
        sa.CheckConstraint(
            "environment IN ('codespaces','staging','production')",
            name="ck_bot_profile_environment",
        ),
        sa.CheckConstraint(
            "request_timeout_seconds BETWEEN 5 AND 60",
            name="ck_bot_profile_request_timeout",
        ),
        sa.CheckConstraint(
            "poll_timeout_seconds BETWEEN 0 AND 30",
            name="ck_bot_profile_poll_timeout",
        ),
    )


def downgrade() -> None:
    """Remove only metadata, never active credentials or receiver state."""
    op.drop_table("shop_bot_profiles")
