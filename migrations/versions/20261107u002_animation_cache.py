"""Permit cached animation file IDs for both messaging providers.

Revision ID: 20261107u002
Revises: 20261107u001
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261107u002"
down_revision = "20261107u001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Allow the delivery kind used by sendAnimation in the remote cache."""
    op.drop_constraint("ck_shop_remote_kind", "shop_remote_files", type_="check")
    op.create_check_constraint(
        "ck_shop_remote_kind",
        "shop_remote_files",
        "delivery_kind IN ('photo','video','audio','voice','document','animation')",
    )


def downgrade() -> None:
    """Restore the former constraint only when no animation IDs exist."""
    connection = op.get_bind()
    count = connection.scalar(sa.text(
        "SELECT count(*) FROM shop_remote_files WHERE delivery_kind = 'animation'"
    ))
    if count:
        raise RuntimeError("Remove cached animation IDs before downgrade.")
    op.drop_constraint("ck_shop_remote_kind", "shop_remote_files", type_="check")
    op.create_check_constraint(
        "ck_shop_remote_kind",
        "shop_remote_files",
        "delivery_kind IN ('photo','video','audio','voice','document')",
    )
