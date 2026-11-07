"""Add editable installation appearance without changing existing records.

Revision ID: 20261107u004
Revises: 20261107u003
"""

from alembic import op
import sqlalchemy as sa

revision = "20261107u004"
down_revision = "20261107u003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the optional deployment-wide settings table."""
    op.create_table(
        "shop_pwa_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("short_name", sa.String(24), nullable=False),
        sa.Column("theme_color", sa.String(7), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    """Remove the optional installation settings."""
    op.drop_table("shop_pwa_settings")
