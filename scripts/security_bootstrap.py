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
        additions = set(CONTROL_TABLE_NAMES) | set(STAFF_SECURITY_TABLE_NAMES) | set(SHOP_CHANNEL_FEATURE_TABLES) | {"shop_product_visibility"}
        missing = permitted_missing(tables, set(Base.metadata.tables), additions)
        if missing:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync,
                tables=[Base.metadata.tables[name] for name in missing], checkfirst=False))
        await verify_codespace_schema(connection)
    await create_admin()
    print("Security schema verified; existing accounts, orders and media preserved.")


if __name__ == "__main__":
    asyncio.run(main())
