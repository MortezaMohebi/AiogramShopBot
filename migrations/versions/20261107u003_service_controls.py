"""Persist operator overrides for shared service activation.

Revision ID: 20261107u003
Revises: 20261107u002
"""

from alembic import op
import sqlalchemy as sa

revision = "20261107u003"
down_revision = "20261107u002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add an empty control table without enabling any service."""
    op.create_table(
        "shop_service_controls",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_shop_service_control_version"),
    )


def downgrade() -> None:
    """Return to deployment defaults only after operators clear overrides."""
    connection = op.get_bind()
    if connection.scalar(sa.text(
        "SELECT count(*) FROM shop_service_controls WHERE enabled IS NOT NULL"
    )):
        raise RuntimeError("Clear active service overrides before downgrade.")
    op.drop_table("shop_service_controls")
