"""Create additive many-to-many outbound Telegram relay Worker registry.

Revision ID: 20261104t001
Revises: 20261103s001

The migration does not modify customer, bot, payment, credit, order,
receiver, broadcast or existing legacy relay settings.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261104t001"
down_revision: str | None = "20261103s001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add independently versioned relay/route/secret/audit tables."""
    op.create_table(
        "shop_relay_workers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("origin", sa.String(300), nullable=False, unique=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("max_rps", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "max_inflight", sa.Integer(), nullable=False, server_default="10",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_by", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('draft','active','paused','disabled')",
            name="ck_shop_relay_worker_status",
        ),
        sa.CheckConstraint(
            "max_rps BETWEEN 1 AND 20", name="ck_shop_relay_rps",
        ),
        sa.CheckConstraint(
            "max_inflight BETWEEN 1 AND 50", name="ck_shop_relay_inflight",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_shop_relay_worker_version",
        ),
    )
    op.create_table(
        "shop_bot_relay_routes",
        sa.Column(
            "bot_id", sa.String(36),
            sa.ForeignKey("shop_bots.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "worker_id", sa.String(36),
            sa.ForeignKey("shop_relay_workers.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(12), nullable=False, server_default="staged",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_by", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "bot_id", "priority", name="uq_bot_relay_route_priority",
        ),
        sa.CheckConstraint(
            "status IN ('staged','active','paused')",
            name="ck_bot_relay_route_status",
        ),
        sa.CheckConstraint(
            "priority BETWEEN 1 AND 1000", name="ck_bot_relay_priority",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_bot_relay_version",
        ),
    )
    op.create_index(
        "ix_bot_relay_routes_worker", "shop_bot_relay_routes",
        ["worker_id", "status"],
    )
    op.create_table(
        "shop_relay_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "bot_id", sa.String(36),
            sa.ForeignKey("shop_bots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "worker_id", sa.String(36),
            sa.ForeignKey("shop_relay_workers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "state", sa.String(12), nullable=False, server_default="staged",
        ),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "bot_id", "worker_id", "version",
            name="uq_shop_relay_credential_version",
        ),
        sa.CheckConstraint(
            "state IN ('staged','active','retiring','revoked')",
            name="ck_shop_relay_credential_state",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_shop_relay_cred_version",
        ),
    )
    op.create_index(
        "uq_shop_relay_active_credential", "shop_relay_credentials",
        ["bot_id", "worker_id"], unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_table(
        "shop_relay_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "worker_id", sa.String(36),
            sa.ForeignKey("shop_relay_workers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "bot_id", sa.String(36),
            sa.ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "actor_id", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="SET NULL"),
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("outcome_code", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_shop_relay_events_worker_id", "shop_relay_events", ["worker_id"],
    )


def downgrade() -> None:
    """Refuse to delete any credential or operator history by downgrade."""
    raise RuntimeError(
        "Relay pool downgrade is intentionally non-destructive. "
        "Disable its feature flag and use a reviewed data-preserving rollback."
    )
