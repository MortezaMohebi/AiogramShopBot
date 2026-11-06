"""Retire the original commerce and obsolete global control schema explicitly.

Revision ID: 20261107z001
Revises: 20261104y001

Existing modern Store, staff/MFA, catalog, customer, order and Bot Registry
records are preserved. Historical bot IDs remain valid owners of modern rows.
Singleton merchant settings are transferred to the default Store before drop.
Run with ``alembic -x retire_original_schema=true upgrade head`` after a backup
when original tables are present. A fresh schema has nothing to retire.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.engine import Connection

revision: str = "20261107z001"
down_revision: str | None = "20261104y001"
branch_labels = None
depends_on = None

# Fixed retirement allowlist: never derive destructive identifiers from input.
RETIRED_TABLE_NAMES = (
    "reviews", "buyItem", "cart_items", "items", "buys", "deposits",
    "payments", "referral_bonus", "carts", "users", "coupons",
    "shipping_options", "buttons_media", "categories", "subcategories",
    "shop_bot_profiles", "shop_payment_rails", "shop_channel_features",
    "shop_telegram_transport_changes", "shop_telegram_transport",
    "shop_connection_changes", "shop_connection_configs", "shop_settings",
    "shop_customer_identity_links",
)


def existing_original_tables(connection: Connection) -> list[str]:
    """Return only retired table names from the application's public schema."""
    schema = "public" if connection.dialect.name == "postgresql" else None
    actual = set(sa.inspect(connection).get_table_names(schema=schema))
    return [name for name in RETIRED_TABLE_NAMES if name in actual]


def validate_original_table_dependencies(
    connection: Connection, names: list[str],
) -> None:
    """Reject external FK dependencies before making any destructive change."""
    inspector = sa.inspect(connection)
    application_schema = (
        "public" if connection.dialect.name == "postgresql" else None
    )
    schemas = (
        [name for name in inspector.get_schema_names()
         if name not in {"information_schema", "pg_catalog"}
         and not name.startswith("pg_")]
        if application_schema else [None]
    )
    targets = set(names)
    for schema in schemas:
        for name in inspector.get_table_names(schema=schema):
            if schema == application_schema and name in targets:
                continue
            for foreign_key in inspector.get_foreign_keys(name, schema=schema):
                target_schema = (
                    foreign_key.get("referred_schema") or application_schema
                )
                if (
                    target_schema == application_schema
                    and foreign_key["referred_table"] in targets
                ):
                    raise RuntimeError(
                        "Retired schema has external foreign keys; "
                        "no tables were dropped"
                    )


_SETTINGS_FIELDS = (
    "brand_name", "welcome_message", "faq_text", "support_url",
)
_DEFAULT_STORE_ID = str(uuid5(NAMESPACE_URL, "aiogramshopbot:store:default:v1"))


def transfer_singleton_settings(
    connection: Connection, *, apply: bool = False,
) -> None:
    """Preserve singleton merchant text in the default Store before retirement.

    Existing non-NULL Store values remain authoritative. Conflicting text is a
    hard failure requiring deliberate reconciliation before any table drops.
    Read-only inspection runs the same preservation checks without writes.
    """
    schema = "public" if connection.dialect.name == "postgresql" else None
    tables = set(sa.inspect(connection).get_table_names(schema=schema))
    if "shop_settings" not in tables:
        return
    prefix = "public." if schema else ""
    settings = connection.execute(sa.text(
        f"SELECT brand_name, welcome_message, faq_text, support_url "
        f"FROM {prefix}shop_settings WHERE id = 1"
    )).mappings().first()
    if settings is None:
        return
    if not {"shop_stores", "shop_store_settings"} <= tables:
        raise RuntimeError(
            "Store settings migration requires the modern Store schema"
        )
    store = connection.scalar(sa.text(
        f"SELECT id FROM {prefix}shop_stores WHERE id = :store_id"
    ), {"store_id": _DEFAULT_STORE_ID})
    if store is None:
        raise RuntimeError("Store settings migration requires the default Store")
    current = connection.execute(sa.text(
        f"SELECT brand_name, welcome_message, faq_text, support_url "
        f"FROM {prefix}shop_store_settings WHERE store_id = :store_id"
    ), {"store_id": _DEFAULT_STORE_ID}).mappings().first()
    if current is not None and any(
        current[field] is not None and settings[field] is not None
        and current[field] != settings[field]
        for field in _SETTINGS_FIELDS
    ):
        raise RuntimeError(
            "Store settings conflict with singleton content; "
            "reconcile merchant text before retirement"
        )
    if not apply:
        return
    values = {"store_id": _DEFAULT_STORE_ID, **dict(settings)}
    if current is None:
        connection.execute(sa.text(
            f"INSERT INTO {prefix}shop_store_settings "
            "(store_id, brand_name, welcome_message, faq_text, support_url) "
            "VALUES (:store_id, :brand_name, :welcome_message, :faq_text, :support_url)"
        ), values)
    else:
        # Fill NULLs only after the locked comparison proved no conflicts.
        assignments = ", ".join(
            f"{field} = COALESCE({field}, :{field})" for field in _SETTINGS_FIELDS
        )
        connection.execute(sa.text(
            f"UPDATE {prefix}shop_store_settings SET {assignments} "
            "WHERE store_id = :store_id"
        ), values)


def validate_retired_identity_links(
    connection: Connection, *, lock: bool = False,
) -> None:
    """Require old link relations to exist in modern Store Customer ownership."""
    schema = "public" if connection.dialect.name == "postgresql" else None
    tables = set(sa.inspect(connection).get_table_names(schema=schema))
    if "shop_customer_identity_links" not in tables:
        return
    prefix = "public." if schema else ""
    count = connection.scalar(sa.text(
        f"SELECT COUNT(*) FROM {prefix}shop_customer_identity_links"
    ))
    if not count:
        return
    if "shop_identities" not in tables:
        raise RuntimeError("Historical identity links require modern ownership")
    if lock and schema:
        connection.execute(sa.text(
            "LOCK TABLE public.shop_identities IN SHARE MODE"
        ))
    unresolved = connection.scalar(sa.text(
        f"SELECT COUNT(*) FROM {prefix}shop_customer_identity_links AS old "
        f"LEFT JOIN {prefix}shop_identities AS source ON source.id = old.source_id "
        f"LEFT JOIN {prefix}shop_identities AS target ON target.id = old.target_id "
        "WHERE source.id IS NULL OR target.id IS NULL "
        "OR source.store_id <> target.store_id "
        "OR source.customer_id IS NULL OR target.customer_id IS NULL "
        "OR source.customer_id <> target.customer_id"
    ))
    if unresolved:
        raise RuntimeError(
            "Historical identity links lack modern shared Customer ownership; "
            "reconcile ownership before retirement"
        )


def retire_workflow_bindings(
    connection: Connection, *, apply: bool = False,
) -> dict[str, int]:
    """Disable retired entry pointers and normalize fallback, preserving Runs."""
    schema = "public" if connection.dialect.name == "postgresql" else None
    counts = {"fallbacks": 0, "bridges": 0}
    if "shop_workflow_bindings" not in sa.inspect(connection).get_table_names(
        schema=schema
    ):
        return counts
    prefix = "public." if schema else ""
    if apply and schema:
        connection.execute(sa.text(
            "LOCK TABLE public.shop_workflow_bindings IN SHARE ROW EXCLUSIVE MODE"
        ))
    counts["fallbacks"] = int(connection.scalar(sa.text(
        f"SELECT COUNT(*) FROM {prefix}shop_workflow_bindings "
        "WHERE fallback = 'legacy'"
    )) or 0)
    counts["bridges"] = int(connection.scalar(sa.text(
        f"SELECT COUNT(*) FROM {prefix}shop_workflow_bindings "
        "WHERE kind = 'legacy_bridge' AND enabled = true"
    )) or 0)
    if apply and counts["fallbacks"]:
        connection.execute(sa.text(
            f"UPDATE {prefix}shop_workflow_bindings SET fallback = 'ignore' "
            "WHERE fallback = 'legacy'"
        ))
    if apply and counts["bridges"]:
        # Existing Runs reference these IDs; retaining disabled pointers keeps
        # their historical ownership valid without admitting new executions.
        connection.execute(sa.text(
            f"UPDATE {prefix}shop_workflow_bindings SET enabled = false "
            "WHERE kind = 'legacy_bridge' AND enabled = true"
        ))
    return counts

def drop_original_tables(connection: Connection) -> list[str]:
    """Retire allowlisted tables and entry pointers, preserving modern records.

    PostgreSQL executes transactional DDL. An exclusive lock prevents changes
    to the selected tables or their FK dependencies between preflight and DROP.
    DROP uses its default RESTRICT behavior; no CASCADE is ever requested.
    """
    names = existing_original_tables(connection)
    if not names:
        retire_workflow_bindings(connection, apply=True)
        return []
    quote = connection.dialect.identifier_preparer.quote
    if connection.dialect.name == "postgresql":
        identifiers = ", ".join(f"public.{quote(name)}" for name in names)
        connection.execute(sa.text(
            f"LOCK TABLE {identifiers} IN ACCESS EXCLUSIVE MODE"
        ))
    validate_original_table_dependencies(connection, names)
    if (
        connection.dialect.name == "postgresql" and "shop_settings" in names
        and "shop_store_settings" in sa.inspect(connection).get_table_names(
            schema="public"
        )
    ):
        # Serialize against settings edits while comparing and copying values.
        connection.execute(sa.text(
            "LOCK TABLE public.shop_store_settings IN SHARE ROW EXCLUSIVE MODE"
        ))
    validate_retired_identity_links(connection, lock=True)
    transfer_singleton_settings(connection, apply=True)
    retire_workflow_bindings(connection, apply=True)
    if connection.dialect.name == "postgresql":
        # One statement permits dependencies within the retired table set.
        connection.execute(sa.text(f"DROP TABLE {identifiers} RESTRICT"))
    else:
        # Disposable SQLite tests exercise the same bounded preflight logic.
        for name in names:
            connection.execute(sa.text(f"DROP TABLE {quote(name)}"))
    return names


def upgrade() -> None:
    """Require an explicit operator flag before retiring existing old tables."""
    connection = op.get_bind()
    if (
        not existing_original_tables(connection)
        and not any(retire_workflow_bindings(connection).values())
    ):
        return
    if context.get_x_argument(as_dictionary=True).get(
        "retire_original_schema"
    ) != "true":
        raise RuntimeError(
            "Back up the database and explicitly pass "
            "-x retire_original_schema=true to retire original tables"
        )
    drop_original_tables(connection)


def downgrade() -> None:
    """Refuse to invent historical customer or transaction records."""
    raise RuntimeError(
        "Original schema retirement is irreversible; restore a verified backup"
    )
