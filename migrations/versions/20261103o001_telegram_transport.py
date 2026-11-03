"""Add encrypted Telegram transport switch receipts and active version.

Revision ID: 20261103o001
Revises: 20261103n001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261103o001"
down_revision: str | None = "20261103n001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create additive encrypted transport tables; never alter live tokens."""
    op.create_table(
        "shop_telegram_transport",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("config_ciphertext", sa.Text(), nullable=False),
        sa.Column("verified_bot_id", sa.Integer(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("shop_staff.id"), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_shop_telegram_transport_singleton"),
        sa.CheckConstraint("version > 0", name="ck_shop_telegram_transport_version"),
    )
    op.create_table(
        "shop_telegram_transport_changes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("shop_staff.id"), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("proposed_ciphertext", sa.Text(), nullable=False),
        sa.Column("previous_ciphertext", sa.Text()),
        sa.Column("operation", sa.String(16), nullable=False, server_default="switch"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.String(64)),
        sa.Column("verified_bot_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "operation IN ('switch', 'rollback')",
            name="ck_shop_transport_operation",
        ),
        sa.CheckConstraint(
            "status IN ('pending','applying','succeeded','failed','cancelled','needs_review')",
            name="ck_shop_transport_change_status",
        ),
        sa.CheckConstraint(
            "expected_version > 0",
            name="ck_shop_transport_expected_version",
        ),
    )
    op.create_index(
        "ix_transport_change_created",
        "shop_telegram_transport_changes",
        ["created_at"],
    )


def downgrade() -> None:
    """Drop only transport configuration on an explicit reviewed rollback."""
    op.drop_index(
        "ix_transport_change_created",
        table_name="shop_telegram_transport_changes",
    )
    op.drop_table("shop_telegram_transport_changes")
    op.drop_table("shop_telegram_transport")
