"""Add store/customer ownership and explicit bot commerce policy.

Revision ID: 20261104u001
Revises: 20261104t001

Existing customers remain distinct, all balances and ledger entries remain
unchanged, and no provider credential or payment method is activated.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261104u001"
down_revision: str | None = "20261104t001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GLOBAL_TABLES = (
    "shop_categories", "shop_products", "shop_shipping_methods",
    "shop_coupons", "shop_campaigns",
)
_BOT_TABLES = ("shop_identities", "shop_carts", "shop_orders")


def _store_fk(table: str, expression: str) -> None:
    """Add and backfill a Store FK without deleting historical rows."""
    op.add_column(table, sa.Column("store_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        f"fk_{table}_store", table, "shop_stores",
        ["store_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index(f"ix_{table}_store_id", table, ["store_id"])
    connection = op.get_bind()
    connection.execute(sa.text(
        f"UPDATE {table} SET store_id = {expression} WHERE store_id IS NULL"
    ))
    missing = int(connection.scalar(sa.text(
        f"SELECT COUNT(*) FROM {table} WHERE store_id IS NULL"
    )) or 0)
    if missing:
        raise RuntimeError(f"Missing Store owners in {table}: {missing}")
    op.alter_column(table, "store_id", nullable=False)


def upgrade() -> None:
    """Backfill isolated customers and Store keys, then add opt-in policies."""
    conn = op.get_bind()
    default_store = conn.scalar(sa.text(
        "SELECT id FROM shop_stores WHERE slug = 'default'"
    ))
    if default_store is None:
        raise RuntimeError("Default Store has not been adopted")
    # Only a deterministic registered default may own old global content.
    for table in _GLOBAL_TABLES:
        op.add_column(table, sa.Column(
            "store_id", sa.String(36), nullable=True,
        ))
        op.create_foreign_key(
            f"fk_{table}_store", table, "shop_stores",
            ["store_id"], ["id"], ondelete="RESTRICT",
        )
        op.create_index(f"ix_{table}_store_id", table, ["store_id"])
        conn.execute(sa.text(
            f"UPDATE {table} SET store_id = :store "
            "WHERE store_id IS NULL"
        ), {"store": default_store})
        op.alter_column(table, "store_id", nullable=False)

    for table in _BOT_TABLES:
        _store_fk(
            table,
            f"(SELECT bot.store_id FROM shop_bots AS bot "
            f"WHERE bot.id = {table}.bot_id)",
        )

    op.create_table(
        "shop_store_customers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey(
            "shop_stores.id", ondelete="RESTRICT",
        ), nullable=False),
        sa.Column("display_name", sa.String(255)),
        sa.Column("phone", sa.String(32)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_shop_store_customers_store_id", "shop_store_customers", ["store_id"],
    )
    # Preserving each old identity's numeric ID ensures deterministic
    # first-pass backfill without merging equal Telegram/Bale user IDs.
    conn.execute(sa.text(
        "INSERT INTO shop_store_customers (id, store_id, display_name) "
        "SELECT identity.id, identity.store_id, identity.first_name "
        "FROM shop_identities AS identity"
    ))
    conn.execute(sa.text(
        "SELECT setval("
        "pg_get_serial_sequence('shop_store_customers', 'id'), "
        "GREATEST((SELECT COALESCE(MAX(id), 0) FROM shop_store_customers), 1), "
        "(SELECT COUNT(*) > 0 FROM shop_store_customers))"
    ))

    op.add_column("shop_identities", sa.Column(
        "customer_id", sa.BigInteger(), nullable=True,
    ))
    op.create_foreign_key(
        "fk_shop_identities_customer", "shop_identities",
        "shop_store_customers", ["customer_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_shop_identities_customer_id", "shop_identities", ["customer_id"],
    )
    conn.execute(sa.text(
        "UPDATE shop_identities SET customer_id = id"
    ))
    # Keep this nullable for a transitional rollout and old offline fixtures;
    # the application always creates a Customer for new real identities.

    # Earlier cross-provider links already contain independent mutual proof.
    # Reconcile only links with two identities in this same Store, preserving
    # every historical order/wallet reference and every consent record.
    conn.execute(sa.text(
        "UPDATE shop_identities AS target SET customer_id = source.customer_id "
        "FROM shop_customer_identity_links AS links "
        "JOIN shop_identities AS source ON source.id = links.source_id "
        "WHERE target.id = links.target_id "
        "AND target.store_id = source.store_id"
    ))

    for table in ("shop_carts", "shop_orders"):
        op.add_column(table, sa.Column(
            "customer_id", sa.BigInteger(), nullable=True,
        ))
        op.create_foreign_key(
            f"fk_{table}_customer", table,
            "shop_store_customers", ["customer_id"], ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(f"ix_{table}_customer_id", table, ["customer_id"])
        # Older orders may predate identity registration. Preserve them
        # unlinked instead of inventing a verified customer identity.
        conn.execute(sa.text(
            f"UPDATE {table} AS t SET customer_id = i.customer_id "
            "FROM shop_identities AS i "
            "WHERE t.bot_id = i.bot_id "
            "AND t.platform_user_id = i.platform_user_id"
        ))

    op.add_column("shop_carts", sa.Column(
        "is_shared", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.drop_constraint(
        "uq_shop_cart_bot_owner", "shop_carts", type_="unique",
    )
    op.create_index(
        "uq_shop_cart_private_owner", "shop_carts",
        ["bot_id", "platform_user_id"], unique=True,
        postgresql_where=sa.text("is_shared = false"),
    )
    op.create_index(
        "uq_shop_cart_shared_customer", "shop_carts",
        ["store_id", "customer_id"], unique=True,
        postgresql_where=sa.text("is_shared = true"),
    )
    op.create_check_constraint(
        "ck_shop_cart_shared_identity", "shop_carts",
        "NOT is_shared OR customer_id IS NOT NULL",
    )

    op.create_table(
        "shop_cart_input_sessions",
        sa.Column("bot_id", sa.String(36), sa.ForeignKey(
            "shop_bots.id", ondelete="RESTRICT",
        ), primary_key=True),
        sa.Column("platform_user_id", sa.BigInteger(), primary_key=True),
        sa.Column("cart_id", sa.Integer(), sa.ForeignKey(
            "shop_carts.id", ondelete="CASCADE",
        ), nullable=False),
        sa.Column("awaiting_input", sa.String(12)),
        sa.CheckConstraint(
            "awaiting_input IS NULL OR awaiting_input IN ('address','coupon')",
            name="ck_shop_cart_session_input",
        ),
    )

    # Payment attempts have an immutable Store inherited from their order.
    _store_fk(
        "shop_payment_attempts",
        "(SELECT orders.store_id FROM shop_orders AS orders "
        "WHERE orders.id = shop_payment_attempts.order_id)",
    )
    op.add_column("shop_payment_attempts", sa.Column(
        "payment_account_id", sa.String(36), nullable=True,
    ))

    # Existing financial balances remain attached to their original
    # identity. A separate customer wallet is created only by opt-in code.
    _store_fk(
        "shop_wallet_accounts",
        "(SELECT i.store_id FROM shop_identities AS i "
        "WHERE i.id = shop_wallet_accounts.identity_id)",
    )
    op.add_column("shop_wallet_accounts", sa.Column(
        "customer_id", sa.BigInteger(), nullable=True,
    ))
    op.create_foreign_key(
        "fk_shop_wallet_customer", "shop_wallet_accounts",
        "shop_store_customers", ["customer_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_shop_wallet_accounts_customer", "shop_wallet_accounts",
        ["customer_id"],
    )
    conn.execute(sa.text(
        "UPDATE shop_wallet_accounts AS w SET customer_id = i.customer_id "
        "FROM shop_identities AS i WHERE w.identity_id = i.id"
    ))
    op.alter_column("shop_wallet_accounts", "customer_id", nullable=False)
    op.add_column("shop_wallet_accounts", sa.Column(
        "scope", sa.String(12), nullable=False, server_default="identity",
    ))
    op.alter_column(
        "shop_wallet_accounts", "identity_id", nullable=True,
    )
    op.create_check_constraint(
        "ck_shop_wallet_scope", "shop_wallet_accounts",
        "(scope = 'identity' AND identity_id IS NOT NULL "
        "AND bot_id IS NOT NULL) OR "
        "(scope = 'customer' AND identity_id IS NULL AND bot_id IS NULL)",
    )
    op.create_index(
        "uq_shop_wallet_shared_customer", "shop_wallet_accounts",
        ["store_id", "customer_id"], unique=True,
        postgresql_where=sa.text("scope = 'customer'"),
    )
    op.add_column("shop_wallet_entries", sa.Column(
        "source_identity_id", sa.Integer(), nullable=True,
    ))
    op.create_foreign_key(
        "fk_shop_wallet_entry_source_identity", "shop_wallet_entries",
        "shop_identities", ["source_identity_id"], ["id"],
        ondelete="RESTRICT",
    )
    conn.execute(sa.text(
        "UPDATE shop_wallet_entries AS e SET source_identity_id = a.identity_id "
        "FROM shop_wallet_accounts AS a WHERE e.account_id = a.id"
    ))

    op.create_table(
        "shop_store_customer_link_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey(
            "shop_stores.id", ondelete="RESTRICT",
        ), nullable=False),
        sa.Column("request_id", sa.String(36), sa.ForeignKey(
            "shop_customer_link_requests.id", ondelete="RESTRICT",
        ), nullable=False, unique=True),
        sa.Column("source_identity_id", sa.Integer(), sa.ForeignKey(
            "shop_identities.id", ondelete="RESTRICT",
        ), nullable=False),
        sa.Column("target_identity_id", sa.Integer(), sa.ForeignKey(
            "shop_identities.id", ondelete="RESTRICT",
        ), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), sa.ForeignKey(
            "shop_store_customers.id", ondelete="RESTRICT",
        ), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index(
        "ix_shop_store_customer_link_events_store_id",
        "shop_store_customer_link_events", ["store_id"],
    )
    op.create_table(
        "shop_store_commerce_policies",
        sa.Column("store_id", sa.String(36), sa.ForeignKey(
            "shop_stores.id", ondelete="RESTRICT",
        ), primary_key=True),
        sa.Column(
            "cart_scope", sa.String(12), nullable=False, server_default="bot",
        ),
        sa.Column(
            "credit_scope", sa.String(12), nullable=False,
            server_default="identity",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey(
            "shop_staff.id", ondelete="SET NULL",
        )),
        sa.CheckConstraint(
            "cart_scope IN ('bot','customer')",
            name="ck_store_commerce_cart_scope",
        ),
        sa.CheckConstraint(
            "credit_scope IN ('identity','customer')",
            name="ck_store_commerce_credit_scope",
        ),
        sa.CheckConstraint("version > 0", name="ck_store_commerce_version"),
    )
    conn.execute(sa.text(
        "INSERT INTO shop_store_commerce_policies "
        "(store_id, cart_scope, credit_scope) "
        "SELECT id, 'bot', 'identity' FROM shop_stores"
    ))
    op.create_table(
        "shop_bot_commerce_policies",
        sa.Column("bot_id", sa.String(36), sa.ForeignKey(
            "shop_bots.id", ondelete="RESTRICT",
        ), primary_key=True),
        sa.Column("cart_enabled", sa.Boolean()),
        sa.Column("credit_enabled", sa.Boolean()),
        sa.Column("credit_label", sa.String(80)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey(
            "shop_staff.id", ondelete="SET NULL",
        )),
        sa.CheckConstraint(
            "credit_label IS NULL OR length(credit_label) BETWEEN 1 AND 80",
            name="ck_bot_commerce_credit_label",
        ),
        sa.CheckConstraint("version > 0", name="ck_bot_commerce_version"),
    )
    op.create_table(
        "shop_payment_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey(
            "shop_stores.id", ondelete="RESTRICT",
        ), nullable=False),
        sa.Column("platform", sa.String(12), nullable=False),
        sa.Column("rail_type", sa.String(24), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("state", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("credential_ciphertext", sa.Text()),
        sa.Column("credential_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey(
            "shop_staff.id", ondelete="SET NULL",
        )),
        sa.CheckConstraint(
            "((platform = 'telegram' AND rail_type = 'telegram_stars' "
            "AND currency = 'XTR') OR "
            "(platform = 'telegram' AND rail_type = 'telegram_fiat' "
            "AND currency = 'IRR') OR "
            "(platform = 'bale' AND rail_type = 'bale_wallet' "
            "AND currency = 'IRR'))",
            name="ck_shop_payment_account_provider",
        ),
        sa.CheckConstraint(
            "state IN ('draft','active','disabled')",
            name="ck_shop_payment_account_state",
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_shop_payment_account_version",
        ),
        sa.CheckConstraint(
            "credential_version > 0", name="ck_shop_payment_secret_version",
        ),
        sa.CheckConstraint(
            "(rail_type = 'telegram_stars' AND credential_ciphertext IS NULL) "
            "OR (rail_type != 'telegram_stars' AND "
            "credential_ciphertext IS NOT NULL)",
            name="ck_shop_payment_account_material",
        ),
    )
    op.create_index(
        "ix_shop_payment_accounts_store_id",
        "shop_payment_accounts", ["store_id"],
    )
    op.create_table(
        "shop_bot_payment_access",
        sa.Column("bot_id", sa.String(36), sa.ForeignKey(
            "shop_bots.id", ondelete="RESTRICT",
        ), primary_key=True),
        sa.Column("payment_account_id", sa.String(36), sa.ForeignKey(
            "shop_payment_accounts.id", ondelete="RESTRICT",
        ), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.CheckConstraint(
            "priority BETWEEN 1 AND 1000",
            name="ck_shop_payment_access_priority",
        ),
    )
    op.create_index(
        "ix_shop_payment_access_account", "shop_bot_payment_access",
        ["payment_account_id"],
    )
    op.create_foreign_key(
        "fk_shop_payment_attempt_account",
        "shop_payment_attempts", "shop_payment_accounts",
        ["payment_account_id"], ["id"], ondelete="RESTRICT",
    )
    # Ensure historical credit balances and payments have not been touched.
    mismatches = int(conn.scalar(sa.text(
        "SELECT COUNT(*) FROM shop_wallet_accounts AS w "
        "JOIN shop_identities AS i ON i.id = w.identity_id "
        "WHERE w.store_id <> i.store_id OR w.customer_id <> i.customer_id"
    )) or 0)
    if mismatches:
        raise RuntimeError(f"Wallet ownership mismatches: {mismatches}")


def downgrade() -> None:
    """Never drop verified customer links, scoped orders or wallet ownership."""
    raise RuntimeError(
        "Store/customer commerce migration is not destructively reversible. "
        "Roll back code only after reviewed data-preserving reconciliation."
    )
