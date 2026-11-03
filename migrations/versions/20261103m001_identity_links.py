"""Add independent, verified Telegram/Bale identity association.

Revision ID: 20261103m001
Revises: 20261103l001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261103m001"
down_revision: str | None = "20261103l001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store only link proof receipts; never merge wallets or sales history."""
    op.create_table(
        "shop_customer_link_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("shop_identities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", sa.Integer(), sa.ForeignKey("shop_identities.id", ondelete="CASCADE")),
        sa.Column("state", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending','awaiting_confirmation','confirmed','cancelled')",
            name="ck_customer_link_request_state",
        ),
    )
    op.create_table(
        "shop_customer_identity_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("shop_identities.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("target_id", sa.Integer(), sa.ForeignKey("shop_identities.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source_id != target_id", name="ck_customer_link_distinct"),
    )


def downgrade() -> None:
    """Remove only verified links on explicit rollback; no financial effects."""
    op.drop_table("shop_customer_identity_links")
    op.drop_table("shop_customer_link_requests")
