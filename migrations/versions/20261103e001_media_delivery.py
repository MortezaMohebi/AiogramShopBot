"""Create per-bot media cache, webhook receipts and campaign media.

Revision ID: 20261103e001
Revises: 20261102d002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261103e001"
down_revision: Union[str, None] = "20261102d002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add non-destructive delivery infrastructure for both messaging apps."""
    op.create_table(
        "shop_remote_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(12), nullable=False),
        sa.Column("bot_fingerprint", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(80), nullable=False),
        sa.Column("delivery_kind", sa.String(16), nullable=False),
        sa.Column("remote_file_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "platform", "bot_fingerprint", "storage_key", "delivery_kind",
            name="uq_shop_remote_file_bot_asset",
        ),
        sa.CheckConstraint(
            "platform IN ('telegram','bale')",
            name="ck_shop_remote_platform",
        ),
        sa.CheckConstraint(
            "delivery_kind IN ('photo','video','audio','voice','document')",
            name="ck_shop_remote_kind",
        ),
    )
    op.create_table(
        "shop_inbound_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(12), nullable=False),
        sa.Column("bot_fingerprint", sa.String(64), nullable=False),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status", sa.String(24), nullable=False,
            server_default="processing",
        ),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "platform", "bot_fingerprint", "update_id",
            name="uq_shop_inbound_update",
        ),
        sa.CheckConstraint(
            "status IN ('processing','processed','needs_review')",
            name="ck_shop_inbound_status",
        ),
        sa.CheckConstraint(
            "update_id >= 0", name="ck_shop_inbound_id"
        ),
    )
    op.create_table(
        "shop_campaign_media",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "campaign_id", sa.Integer(),
            sa.ForeignKey("shop_campaigns.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(80), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("mime_type", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("caption", sa.Text()),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.CheckConstraint(
            "kind IN ('photo','video','audio','document')",
            name="ck_shop_campaign_media_kind",
        ),
        sa.CheckConstraint(
            "size_bytes > 0", name="ck_shop_campaign_media_size"
        ),
    )
    op.create_index(
        "ix_shop_campaign_media_order",
        "shop_campaign_media",
        ["campaign_id", "position", "id"],
    )


def downgrade() -> None:
    """Remove only the new delivery tables, preserving the old sales schema."""
    op.drop_index(
        "ix_shop_campaign_media_order", table_name="shop_campaign_media"
    )
    op.drop_table("shop_campaign_media")
    op.drop_table("shop_inbound_updates")
    op.drop_table("shop_remote_files")
