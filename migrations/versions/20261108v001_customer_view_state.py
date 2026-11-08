"""Add optional view metadata to existing customer chat state.

Revision ID: 20261108v001
Revises: 20261107u004
"""

import sqlalchemy as sa
from alembic import op

revision = "20261108v001"
down_revision = "20261107u004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve existing views and forms with a nullable metadata column."""
    op.add_column(
        "shop_customer_chat_states",
        sa.Column("view_state", sa.JSON(none_as_null=True), nullable=True),
    )


def downgrade() -> None:
    """Remove only the new navigation metadata."""
    op.drop_column("shop_customer_chat_states", "view_state")
