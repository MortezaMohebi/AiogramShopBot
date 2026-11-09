"""Add structured attributes to existing products.

Revision ID: 20261109w001
Revises: 20261108v001
"""

import sqlalchemy as sa
from alembic import op

revision = "20261109w001"
down_revision = "20261108v001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep existing products without requiring an attribute backfill."""
    op.add_column("shop_products", sa.Column("attributes", sa.JSON(none_as_null=True)))


def downgrade() -> None:
    """Remove the structured attributes column."""
    op.drop_column("shop_products", "attributes")
