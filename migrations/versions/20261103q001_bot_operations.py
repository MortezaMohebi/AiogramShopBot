"""Add per-bot management policy and credential verification receipts.

Revision ID: 20261103q001
Revises: 20261103p001

No existing order, wallet, customer, cart or provider receiver table changes.
Legacy bot maintenance preferences are copied without modifying originals.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261103q001"
down_revision: str | None = "20261103p001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create per-bot policies and optional staging-verification metadata."""
    op.create_table(
        "shop_bot_operations",
        sa.Column(
            "bot_id", sa.String(36),
            sa.ForeignKey("shop_bots.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "desired_state", sa.String(20), nullable=False,
            server_default="disabled",
        ),
        sa.Column("welcome_message", sa.Text()),
        sa.Column("maintenance_message", sa.Text()),
        sa.Column("support_url", sa.String(500)),
        sa.Column(
            "owner_staff_id", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "environment", sa.String(16), nullable=False,
            server_default="staging",
        ),
        sa.Column("reason", sa.String(500)),
        sa.Column(
            "updated_by", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "desired_state IN ('active','maintenance','paused','disabled')",
            name="ck_bot_operations_state",
        ),
        sa.CheckConstraint(
            "environment IN ('codespaces','staging','production')",
            name="ck_bot_operations_environment",
        ),
        sa.CheckConstraint(
            "maintenance_message IS NULL OR "
            "length(maintenance_message) BETWEEN 1 AND 4096",
            name="ck_bot_operations_maintenance_message",
        ),
        sa.CheckConstraint(
            "welcome_message IS NULL OR length(welcome_message) BETWEEN 1 AND 4096",
            name="ck_bot_operations_welcome_message",
        ),
    )
    op.add_column(
        "shop_bot_credentials",
        sa.Column("verified_bot_id", sa.BigInteger()),
    )
    op.add_column(
        "shop_bot_credentials",
        sa.Column("verified_username", sa.String(255)),
    )
    op.add_column(
        "shop_bot_credentials",
        sa.Column("verified_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "shop_bot_credentials",
        sa.Column("token_fingerprint", sa.String(64)),
    )
    op.create_index(
        "uq_shop_bot_credential_fingerprint",
        "shop_bot_credentials", ["token_fingerprint"], unique=True,
        postgresql_where=sa.text("token_fingerprint IS NOT NULL"),
    )
    # Keep old deployments running: match legacy maintenance state without
    # changing any live receiver or ShopBotProfile record.
    op.execute(sa.text(
        "INSERT INTO shop_bot_operations "
        "(bot_id, desired_state, owner_staff_id, environment) "
        "SELECT b.id, "
        "CASE WHEN COALESCE(p.maintenance_enabled, false) "
        "THEN 'maintenance' ELSE 'active' END, "
        "p.owner_staff_id, COALESCE(p.environment, 'staging') "
        "FROM shop_bots b "
        "LEFT JOIN shop_bot_profiles p ON p.platform = b.platform "
        "WHERE b.runtime_owner = 'legacy' "
        "ON CONFLICT (bot_id) DO NOTHING"
    ))


def downgrade() -> None:
    """Refuse to silently erase bot policies or verification history."""
    raise RuntimeError(
        "Multi-bot operation and credential verification data is protected. "
        "Use a reviewed, data-preserving rollback instead."
    )
