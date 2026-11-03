"""Scope legacy commerce to deterministic bot IDs and add receiver registry.

Revision ID: 20261103s001
Revises: 20261103r001

All existing identities/carts/orders/payments are backfilled in-place. The
legacy provider/user ID uniqueness becomes bot/user uniqueness, allowing
multiple independently owned bots of the same platform. No rows are deleted,
wallet balances are unchanged and old campaign delivery receipts are retained.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa

revision: str = "20261103s001"
down_revision: str | None = "20261103r001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TELEGRAM = str(uuid5(NAMESPACE_URL, "aiogramshopbot:bot:legacy:telegram:v1"))
_BALE = str(uuid5(NAMESPACE_URL, "aiogramshopbot:bot:legacy:bale:v1"))

# Tables with a platform column: all existing rows belong to the original
# deployment bot, never to a newly registered bot of the same provider.
_PROVIDER_OWNED = (
    "shop_identities",
    "shop_carts",
    "shop_orders",
    "shop_payment_attempts",
    "shop_inbound_updates",
    "shop_remote_files",
    "shop_broadcast_rate_slots",
)

# All these have stable existing parent IDs. NULL remains transitional only
# for old cross-platform campaigns; new records will always include bot_id.
_DERIVED = (
    ("shop_wallet_accounts", "identity_id", "shop_identities", "id"),
    ("shop_wallet_entries", "account_id", "shop_wallet_accounts", "id"),
    ("shop_referral_profiles", "identity_id", "shop_identities", "id"),
    ("shop_referral_attributions", "referee_identity_id", "shop_identities", "id"),
    ("shop_referral_rewards", "referee_identity_id", "shop_identities", "id"),
    ("shop_campaign_deliveries", "identity_id", "shop_identities", "id"),
)


def _add_scoped_column(table: str) -> None:
    """Add only an optional FK column before a complete existing-data backfill."""
    op.add_column(table, sa.Column("bot_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        f"fk_{table}_bot_id", table, "shop_bots",
        ["bot_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index(f"ix_{table}_bot_id", table, ["bot_id"])


def upgrade() -> None:
    """Perform an additive, complete per-bot backfill before changing uniqueness."""
    conn = op.get_bind()
    existing = {
        item[0] for item in conn.execute(sa.text(
            "SELECT id FROM shop_bots WHERE id IN (:telegram, :bale)"
        ), {"telegram": _TELEGRAM, "bale": _BALE}).all()
    }
    if existing != {_TELEGRAM, _BALE}:
        raise RuntimeError(
            "Missing canonical legacy bot records; apply Foundation first"
        )

    for table in _PROVIDER_OWNED:
        _add_scoped_column(table)
        # Both IDs are code constants and never extracted from user payloads.
        conn.execute(sa.text(
            f"UPDATE {table} SET bot_id = CASE platform "
            "WHEN 'telegram' THEN :telegram "
            "WHEN 'bale' THEN :bale ELSE NULL END "
            "WHERE bot_id IS NULL"
        ), {"telegram": _TELEGRAM, "bale": _BALE})
        count = conn.scalar(sa.text(
            f"SELECT COUNT(*) FROM {table} WHERE bot_id IS NULL"
        ))
        if count:
            raise RuntimeError(f"Unexpected unowned {table} rows: {count}")
        op.alter_column(table, "bot_id", nullable=False)

    for table, local_column, parent, parent_id in _DERIVED:
        _add_scoped_column(table)
        conn.execute(sa.text(
            f"UPDATE {table} AS child SET bot_id = parent.bot_id "
            f"FROM {parent} AS parent "
            f"WHERE child.{local_column} = parent.{parent_id} "
            "AND child.bot_id IS NULL"
        ))
        unresolved = int(conn.scalar(sa.text(
            f"SELECT COUNT(*) FROM {table} WHERE bot_id IS NULL"
        )) or 0)
        if unresolved:
            raise RuntimeError(
                f"Cannot backfill {table}: {unresolved} missing parent owners"
            )
        # Protect all future derived financial/identity records as well.
        op.alter_column(table, "bot_id", nullable=False)

    _add_scoped_column("shop_campaigns")
    # Historical 'all' campaigns can address both providers. Their per-
    # delivery owner is recorded and never synthesized as a single bot.
    conn.execute(sa.text(
        "UPDATE shop_campaigns AS campaign SET bot_id = sub.bot_id "
        "FROM (SELECT campaign_id, MIN(bot_id) AS bot_id, "
        "COUNT(DISTINCT bot_id) AS bots "
        "FROM shop_campaign_deliveries GROUP BY campaign_id) AS sub "
        "WHERE campaign.id = sub.campaign_id AND sub.bots = 1 "
        "AND campaign.bot_id IS NULL"
    ))

    # The deduplication identity belongs to the registered bot across
    # token rotation, not to the transient token fingerprint.
    op.drop_constraint(
        "uq_shop_inbound_update",
        "shop_inbound_updates", type_="unique",
    )
    op.create_unique_constraint(
        "uq_shop_inbound_bot_update",
        "shop_inbound_updates", ["bot_id", "update_id"],
    )

    # Drop the global platform+user uniqueness only once every legacy row
    # has a non-null bot_id. This permits another Telegram bot to serve the
    # same numeric Telegram user in an entirely different identity/cart.
    op.drop_constraint("uq_shop_identity", "shop_identities", type_="unique")
    op.create_unique_constraint(
        "uq_shop_identity_bot_user", "shop_identities",
        ["bot_id", "platform_user_id"],
    )
    op.drop_constraint("uq_shop_cart_owner", "shop_carts", type_="unique")
    op.create_unique_constraint(
        "uq_shop_cart_bot_owner", "shop_carts",
        ["bot_id", "platform_user_id"],
    )

    op.create_table(
        "shop_bot_receivers",
        sa.Column(
            "bot_id", sa.String(36),
            sa.ForeignKey("shop_bots.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "binding_id", sa.String(36), nullable=False, unique=True,
        ),
        sa.Column(
            "mode", sa.String(8), nullable=False, server_default="webhook",
        ),
        sa.Column(
            "state", sa.String(16), nullable=False, server_default="staged",
        ),
        sa.Column("webhook_secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("webhook_secret_digest", sa.String(64), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("next_update_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_received_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column(
            "updated_by", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "mode IN ('webhook','polling')", name="ck_bot_receiver_mode",
        ),
        sa.CheckConstraint(
            "state IN ('staged','applying','active','paused','disabled',"
            "'needs_review')",
            name="ck_bot_receiver_state",
        ),
        sa.CheckConstraint("version >= 1", name="ck_bot_receiver_version"),
        sa.CheckConstraint(
            "credential_version >= 1",
            name="ck_bot_receiver_credential_version",
        ),
        sa.CheckConstraint("next_update_id >= 0", name="ck_bot_receiver_offset"),
    )
    op.create_table(
        "shop_bot_receiver_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "bot_id", sa.String(36),
            sa.ForeignKey("shop_bots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="SET NULL"),
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "action IN ('staged','applying','activated','paused','disabled',"
            "'needs_review','reconciled')",
            name="ck_bot_receiver_event_action",
        ),
    )
    op.create_index(
        "ix_shop_bot_receiver_events_bot_id",
        "shop_bot_receiver_events", ["bot_id"],
    )

    # Validate all active payment intents and orders retain exactly the same
    # parent bot. The migration aborts atomically if any mismatch exists.
    mismatches = int(conn.scalar(sa.text(
        "SELECT COUNT(*) FROM shop_payment_attempts AS pay "
        "JOIN shop_orders AS ord ON ord.id = pay.order_id "
        "WHERE pay.bot_id <> ord.bot_id"
    )) or 0)
    if mismatches:
        raise RuntimeError(f"Payment bot ownership mismatch: {mismatches}")


def downgrade() -> None:
    """Fail closed rather than silently re-merge user identities and balances."""
    raise RuntimeError(
        "Refusing destructive downgrade: two bots may own the same "
        "platform_user_id. Use a reviewed data-preserving cutover rollback."
    )
