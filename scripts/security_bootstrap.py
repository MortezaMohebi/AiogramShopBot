"""Add only the known security tables to a verified Codespaces database.

No DROP/ALTER of existing business data, no reset, no old SQLite migrations.
A partial legacy schema still fails closed instead of being silently repaired.
"""
from __future__ import annotations
import asyncio
from sqlalchemy import inspect, text, select
from sqlalchemy.orm import Session


def permitted_missing(existing: set[str], expected: set[str], additions: set[str]) -> set[str]:
    """Permit an empty DB or additive control-plane tables, not unknown drift."""
    application = existing - {"alembic_version"}
    if not application:
        return expected
    unknown = application - expected
    missing = expected - application
    if unknown or missing - additions:
        raise RuntimeError("Existing business schema is incomplete or unexpected; no tables changed")
    return missing


async def main() -> None:
    """Create the additive schema transactionally under the bootstrap lock."""
    from scripts.codespace_bootstrap import safe_configuration, create_admin
    safe_configuration()
    from db import engine, verify_codespace_schema
    from models.base import Base
    from models.shop_admin_control import CONTROL_TABLE_NAMES
    from models.shop_staff_security import STAFF_SECURITY_TABLE_NAMES
    from models.shop_channel_features import SHOP_CHANNEL_FEATURE_TABLES
    from models.shop_customer_crm import CRM_TABLE_NAMES
    from models.shop_staff_preferences import STAFF_PREFERENCES_TABLES
    from models.shop_bot_profile import BOT_PROFILE_TABLES
    from models.shop_payment_rail import PAYMENT_RAIL_TABLES
    from models.shop_customer_links import CUSTOMER_LINK_TABLES
    from models.shop_staff_state import STAFF_STATES_TABLES
    from models.shop_telegram_transport import TELEGRAM_TRANSPORT_TABLES
    from models.shop_multibot import MULTIBOT_FOUNDATION_TABLES
    from models.shop_bot_operations import BOT_OPERATIONS_TABLES
    from models.shop_bot_catalog_acl import BOT_CATALOG_ACL_TABLES
    from models.shop_multibot_receiver import BOT_RUNTIME_TABLES
    from models.shop_relay_pool import RELAY_POOL_TABLES
    from models.shop_store_commerce import STORE_COMMERCE_TABLES
    from models.shop_staff_store import STAFF_STORE_TABLES
    from models.shop_uom import ShopUom, ShopUomCategory
    from models.shop_model_import import MODEL_IMPORT_TABLES
    from models.shop_customer_navigation import CUSTOMER_NAV_TABLES
    from models.shop_customer_account_data import CUSTOMER_ACCOUNT_TABLES
    from models.shop_checkout_policy import CHECKOUT_POLICY_TABLES
    from models.shop_customer_support import SUPPORT_FULFILLMENT_TABLES
    from models.shop_customer_notifications import CUSTOMER_NOTIFICATION_TABLES
    from services.shop_multibot_bootstrap import adopt_legacy_codespace
    from services.shop_bot_operations_bootstrap import upgrade_codespace_bot_operations
    from services.shop_uom import seed_store_units
    from models.shop_multibot import ShopStore
    async with engine.begin() as connection:
        if await connection.scalar(text("SELECT current_database()")) != "shop_codespace":
            raise RuntimeError("Only the Codespaces database may be bootstrapped")
        await connection.execute(text("SELECT pg_advisory_xact_lock(90211003)"))
        tables = set(await connection.run_sync(lambda sync: inspect(sync).get_table_names(schema="public")))
        if "alembic_version" in tables:
            revision = await connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            if revision.first():
                raise RuntimeError("Versioned databases must use their migrations")
        # These new tables are additive; neither existing product nor order
        # columns are changed. An existing Codespace keeps all its data.
        additions = set(CONTROL_TABLE_NAMES) | set(STAFF_SECURITY_TABLE_NAMES) | set(SHOP_CHANNEL_FEATURE_TABLES) | set(CRM_TABLE_NAMES) | set(STAFF_PREFERENCES_TABLES) | set(BOT_PROFILE_TABLES) | set(PAYMENT_RAIL_TABLES) | set(CUSTOMER_LINK_TABLES) | set(STAFF_STATES_TABLES) | set(TELEGRAM_TRANSPORT_TABLES) | set(MULTIBOT_FOUNDATION_TABLES) | set(BOT_OPERATIONS_TABLES) | set(BOT_CATALOG_ACL_TABLES) | set(BOT_RUNTIME_TABLES) | set(RELAY_POOL_TABLES) | set(STORE_COMMERCE_TABLES) | set(STAFF_STORE_TABLES) | set(MODEL_IMPORT_TABLES) | set(CUSTOMER_NAV_TABLES) | set(CUSTOMER_ACCOUNT_TABLES) | set(CHECKOUT_POLICY_TABLES) | set(SUPPORT_FULFILLMENT_TABLES) | set(CUSTOMER_NOTIFICATION_TABLES) | {ShopUom.__tablename__, ShopUomCategory.__tablename__, "shop_product_visibility"}
        missing = permitted_missing(tables, set(Base.metadata.tables), additions)
        if missing:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync,
                tables=[Base.metadata.tables[name] for name in missing], checkfirst=False))
        # Phase 1 credentials lack the four nullable Phase 2 verification
        # fields. Adopt existing bots, apply allowlisted additive SQL, and
        # verify the complete schema before committing the transaction.
        # Idempotently register the existing env-backed Telegram/Bale bots.
        # All business rows remain untouched within the same DDL transaction.
        await adopt_legacy_codespace(connection)
        # Nullable credential verification receipts and legacy status rows
        # migrate in-place; Codespace volumes and customer data are preserved.
        await upgrade_codespace_bot_operations(connection)
        # Fresh-schema mode does not run Alembic data backfills. Seed
        # deterministic Store-owned units inside the same locked transaction.
        def ensure_uoms(sync_connection) -> None:
            with Session(bind=sync_connection) as session:
                ids = session.scalars(select(ShopStore.id)).all()
                for store_id in ids:
                    seed_store_units(session, store_id)
                session.flush()
        await connection.run_sync(ensure_uoms)
        await verify_codespace_schema(connection)
    await create_admin()
    print("Security schema verified; existing accounts, orders and media preserved.")


if __name__ == "__main__":
    asyncio.run(main())
