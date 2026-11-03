"""Add only the known security tables to a verified Codespaces database.

No DROP/ALTER of existing business data, no reset, no old SQLite migrations.
A partial legacy schema still fails closed instead of being silently repaired.
"""
from __future__ import annotations
import asyncio
from sqlalchemy import inspect, text


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
    from services.shop_multibot_bootstrap import adopt_legacy_codespace
    from services.shop_bot_operations_bootstrap import upgrade_codespace_bot_operations
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
        additions = set(CONTROL_TABLE_NAMES) | set(STAFF_SECURITY_TABLE_NAMES) | set(SHOP_CHANNEL_FEATURE_TABLES) | set(CRM_TABLE_NAMES) | set(STAFF_PREFERENCES_TABLES) | set(BOT_PROFILE_TABLES) | set(PAYMENT_RAIL_TABLES) | set(CUSTOMER_LINK_TABLES) | set(STAFF_STATES_TABLES) | set(TELEGRAM_TRANSPORT_TABLES) | set(MULTIBOT_FOUNDATION_TABLES) | set(BOT_OPERATIONS_TABLES) | {"shop_product_visibility"}
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
        await verify_codespace_schema(connection)
    await create_admin()
    print("Security schema verified; existing accounts, orders and media preserved.")


if __name__ == "__main__":
    asyncio.run(main())
