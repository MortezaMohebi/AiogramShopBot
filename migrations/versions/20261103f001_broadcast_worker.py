"""Durable campaign runs, audit receipts and cross-worker rate slots.

Revision ID: 20261103f001
Revises: 20261103e001
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261103f001"
down_revision: Union[str, None] = "20261103e001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Extend existing marketing tables without discarding recipient history."""
    op.add_column(
        "shop_campaigns",
        sa.Column(
            "bale_mode", sa.String(12), nullable=False,
            server_default="standard",
        ),
    )
    for column in ("max_paid_calls", "paid_calls_reserved"):
        op.add_column(
            "shop_campaigns",
            sa.Column(column, sa.Integer(), nullable=False, server_default="0"),
        )
    for column in ("started_at", "paused_at", "finished_at"):
        op.add_column(
            "shop_campaigns", sa.Column(column, sa.DateTime(timezone=True))
        )
    op.add_column(
        "shop_campaigns", sa.Column("last_error_code", sa.String(80))
    )
    op.drop_constraint(
        "ck_shop_campaign_status", "shop_campaigns", type_="check"
    )
    op.create_check_constraint(
        "ck_shop_campaign_status", "shop_campaigns",
        "status IN ('draft','approved','sending','paused',"
        "'needs_review','completed','cancelled')",
    )
    op.create_check_constraint(
        "ck_shop_campaign_mode", "shop_campaigns",
        "bale_mode IN ('standard','business')",
    )
    op.create_check_constraint(
        "ck_shop_campaign_budget", "shop_campaigns",
        "max_paid_calls >= 0 AND paid_calls_reserved >= 0 "
        "AND paid_calls_reserved <= max_paid_calls",
    )

    op.add_column(
        "shop_campaign_deliveries",
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "shop_campaign_deliveries",
        sa.Column(
            "completed_steps", sa.Integer(), nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "shop_campaign_deliveries", sa.Column("last_error_code", sa.String(80))
    )
    op.add_column(
        "shop_campaign_deliveries", sa.Column("worker_id", sa.String(48))
    )
    op.create_check_constraint(
        "ck_shop_completed_steps", "shop_campaign_deliveries",
        "completed_steps >= 0",
    )
    op.create_index(
        "ix_shop_campaign_worker_pick", "shop_campaign_deliveries",
        ["status", "campaign_id", "id"],
    )
    op.create_table(
        "shop_broadcast_rate_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(12), nullable=False),
        sa.Column("bot_fingerprint", sa.String(64), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("next_send_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "platform", "bot_fingerprint", "recipient_id",
            name="uq_shop_broadcast_rate_slot",
        ),
        sa.CheckConstraint(
            "platform IN ('telegram','bale')",
            name="ck_shop_broadcast_rate_platform",
        ),
        sa.CheckConstraint(
            "recipient_id >= 0", name="ck_shop_broadcast_recipient_id"
        ),
    )
    op.create_table(
        "shop_campaign_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "campaign_id", sa.Integer(),
            sa.ForeignKey("shop_campaigns.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "delivery_id", sa.Integer(),
            sa.ForeignKey("shop_campaign_deliveries.id", ondelete="RESTRICT"),
        ),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("previous_status", sa.String(24), nullable=False),
        sa.Column("new_status", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(255)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    """Remove only phase-seven scheduling additions."""
    op.drop_table("shop_campaign_audit")
    op.drop_table("shop_broadcast_rate_slots")
    op.drop_index(
        "ix_shop_campaign_worker_pick", table_name="shop_campaign_deliveries"
    )
    op.drop_constraint(
        "ck_shop_completed_steps",
        "shop_campaign_deliveries", type_="check",
    )
    for column in (
        "worker_id", "last_error_code", "completed_steps", "claimed_at"
    ):
        op.drop_column("shop_campaign_deliveries", column)
    for name in ("ck_shop_campaign_budget", "ck_shop_campaign_mode"):
        op.drop_constraint(name, "shop_campaigns", type_="check")
    op.drop_constraint(
        "ck_shop_campaign_status", "shop_campaigns", type_="check"
    )
    op.create_check_constraint(
        "ck_shop_campaign_status", "shop_campaigns",
        "status IN ('draft','approved','sending','completed')",
    )
    for column in (
        "last_error_code", "finished_at", "paused_at", "started_at",
        "paid_calls_reserved", "max_paid_calls", "bale_mode",
    ):
        op.drop_column("shop_campaigns", column)
