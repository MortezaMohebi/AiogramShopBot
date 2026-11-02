"""Add shop-managed fiat credit, referral attribution and campaign outbox.

Revision ID: 20261102d002
Revises: 20261102d001

The legacy Telegram cryptocurrency wallet and payment tables are untouched.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261102d002"
down_revision: Union[str, None] = "20261102d001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Build nonnegative wallet and opt-in engagement tables."""
    op.create_table(
        "shop_wallet_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "identity_id", sa.Integer(),
            sa.ForeignKey("shop_identities.id", ondelete="RESTRICT"),
            nullable=False, unique=True,
        ),
        sa.Column(
            "balance_irr", sa.BigInteger(), nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "balance_irr >= 0", name="ck_shop_wallet_balance"
        ),
    )
    op.create_table(
        "shop_wallet_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id", sa.Integer(),
            sa.ForeignKey("shop_wallet_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "operation_key", sa.String(128), nullable=False, unique=True
        ),
        sa.Column("delta_irr", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_irr", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "delta_irr <> 0", name="ck_shop_wallet_entry_nonzero"
        ),
        sa.CheckConstraint(
            "balance_after_irr >= 0", name="ck_shop_wallet_entry_balance"
        ),
    )
    op.create_table(
        "shop_referral_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "identity_id", sa.Integer(),
            sa.ForeignKey("shop_identities.id", ondelete="RESTRICT"),
            nullable=False, unique=True,
        ),
        sa.Column("code", sa.String(24), nullable=False, unique=True),
    )
    op.create_table(
        "shop_referral_attributions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "referee_identity_id", sa.Integer(),
            sa.ForeignKey("shop_identities.id", ondelete="RESTRICT"),
            nullable=False, unique=True,
        ),
        sa.Column(
            "inviter_identity_id", sa.Integer(),
            sa.ForeignKey("shop_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code_snapshot", sa.String(24), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "referee_identity_id != inviter_identity_id",
            name="ck_shop_referral_no_self",
        ),
    )
    op.create_table(
        "shop_referral_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "percent", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "min_order_irr", sa.BigInteger(), nullable=False,
            server_default="0",
        ),
        sa.Column(
            "max_bonus_irr", sa.BigInteger(), nullable=False,
            server_default="0",
        ),
        sa.CheckConstraint(
            "id = 1", name="ck_shop_referral_policy_singleton"
        ),
        sa.CheckConstraint(
            "percent BETWEEN 0 AND 30", name="ck_shop_referral_percent"
        ),
        sa.CheckConstraint(
            "min_order_irr >= 0", name="ck_shop_referral_minimum"
        ),
        sa.CheckConstraint(
            "max_bonus_irr >= 0", name="ck_shop_referral_cap"
        ),
    )
    op.create_table(
        "shop_referral_rewards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "referee_identity_id", sa.Integer(),
            sa.ForeignKey("shop_identities.id", ondelete="RESTRICT"),
            nullable=False, unique=True,
        ),
        sa.Column(
            "inviter_identity_id", sa.Integer(),
            sa.ForeignKey("shop_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "order_id", sa.BigInteger(),
            sa.ForeignKey("shop_orders.id", ondelete="RESTRICT"),
            nullable=False, unique=True,
        ),
        sa.Column("bonus_irr", sa.BigInteger(), nullable=False),
        sa.Column(
            "wallet_entry_id", sa.Integer(),
            sa.ForeignKey("shop_wallet_entries.id", ondelete="RESTRICT"),
            nullable=False, unique=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint("bonus_irr > 0", name="ck_shop_referral_bonus"),
    )
    op.create_table(
        "shop_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "audience", sa.String(12), nullable=False,
            server_default="all",
        ),
        sa.Column(
            "status", sa.String(20), nullable=False,
            server_default="draft",
        ),
        sa.Column("approved_by", sa.String(120)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "audience IN ('all','telegram','bale')",
            name="ck_shop_campaign_audience",
        ),
        sa.CheckConstraint(
            "status IN ('draft','approved','sending','completed')",
            name="ck_shop_campaign_status",
        ),
    )
    op.create_table(
        "shop_campaign_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "campaign_id", sa.Integer(),
            sa.ForeignKey("shop_campaigns.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "identity_id", sa.Integer(),
            sa.ForeignKey("shop_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(16), nullable=False,
            server_default="queued",
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "campaign_id", "identity_id",
            name="uq_shop_campaign_recipient",
        ),
        sa.CheckConstraint(
            "status IN ('queued','sending','sent','unknown','skipped')",
            name="ck_shop_campaign_delivery_status",
        ),
    )
    op.create_index(
        "ix_shop_campaign_delivery_status",
        "shop_campaign_deliveries",
        ["campaign_id", "status", "id"],
    )

    # Store credit is not a Telegram Bot API provider; payments are
    # settled entirely within the merchant's own immutable wallet ledger.
    op.drop_constraint(
        "ck_shop_payment_provider", "shop_payment_attempts", type_="check"
    )
    op.create_check_constraint(
        "ck_shop_payment_provider", "shop_payment_attempts",
        "provider IN ('bale_wallet','telegram_fiat',"
        "'telegram_stars','store_credit')",
    )


def downgrade() -> None:
    """Drop this phase's new tables after verifying no live ledger exists."""
    op.drop_constraint(
        "ck_shop_payment_provider", "shop_payment_attempts", type_="check"
    )
    op.create_check_constraint(
        "ck_shop_payment_provider", "shop_payment_attempts",
        "provider IN ('bale_wallet','telegram_fiat','telegram_stars')",
    )
    op.drop_index(
        "ix_shop_campaign_delivery_status",
        table_name="shop_campaign_deliveries",
    )
    op.drop_table("shop_campaign_deliveries")
    op.drop_table("shop_campaigns")
    op.drop_table("shop_referral_rewards")
    op.drop_table("shop_referral_policy")
    op.drop_table("shop_referral_attributions")
    op.drop_table("shop_referral_profiles")
    op.drop_table("shop_wallet_entries")
    op.drop_table("shop_wallet_accounts")
