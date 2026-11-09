"""Keep Relay audit references when a Worker is removed from the registry."""

import sqlalchemy as sa
from alembic import op

revision = "20261109w006"
down_revision = "20261109w005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shop_relay_workers", sa.Column("archived_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("shop_relay_workers", "archived_at")
