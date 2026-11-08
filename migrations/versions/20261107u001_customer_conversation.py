"""Persist resumable address drafts, verified contact separation and UI receipts.

Revision ID: 20261107u001
Revises: 20261107z001
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261107u001"
down_revision = "20261107z001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable fields without changing existing customer records."""
    op.add_column(
        "shop_store_customers", sa.Column("contact_phone", sa.String(32)),
    )
    op.add_column(
        "shop_customer_chat_states", sa.Column("address_draft", sa.Text()),
    )
    op.add_column(
        "shop_customer_chat_states", sa.Column("ui_message_id", sa.BigInteger()),
    )
    op.create_table(
        "shop_customer_media_receipts",
        sa.Column("bot_id", sa.String(36), sa.ForeignKey(
            "shop_bots.id", ondelete="RESTRICT",
        ), primary_key=True),
        sa.Column("platform_user_id", sa.BigInteger(), primary_key=True),
        sa.Column("storage_key", sa.String(80), primary_key=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey(
            "shop_stores.id", ondelete="RESTRICT",
        ), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
    )
    op.drop_constraint("ck_shop_media_kind", "shop_product_media", type_="check")
    op.create_check_constraint(
        "ck_shop_media_kind", "shop_product_media",
        "kind IN ('photo', 'video', 'audio', 'document', 'animation')",
    )


def downgrade() -> None:
    """Remove conversation state fields without touching address records."""
    # Existing animation rows must be handled explicitly before downgrade.
    op.drop_constraint("ck_shop_media_kind", "shop_product_media", type_="check")
    op.create_check_constraint(
        "ck_shop_media_kind", "shop_product_media",
        "kind IN ('photo', 'video', 'audio', 'document')",
    )
    op.drop_table("shop_customer_media_receipts")
    op.drop_column("shop_customer_chat_states", "ui_message_id")
    op.drop_column("shop_customer_chat_states", "address_draft")
    op.drop_column("shop_store_customers", "contact_phone")
