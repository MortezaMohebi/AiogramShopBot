"""Bootstrap virgin Codespaces PostgreSQL and run the real shop migrations.

The legacy Alembic history is SQLite-specific and starts with PRAGMA against
pre-existing tables. Only for a completely empty Codespaces PostgreSQL DB,
build the legacy ORM baseline, stamp the last legacy revision and execute
every newer shop, wallet, media and Broadcast Alembic revision normally.

Never baseline a populated or versioned database.
"""

from __future__ import annotations

import asyncio
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text

LEGACY_BASE_REVISION = "91c3856a8aa0"
REQUIRED = {
    "POSTGRES_DB": "shop_codespace",
    "DB_NAME": "shop_codespace",
    "DB_HOST": "postgres",
    "POSTGRES_USER": "shop_codespace",
    "DB_USER": "shop_codespace",
    "SHOP_CAMPAIGN_DISPATCH_ENABLED": "false",
    "SHOP_BROADCAST_WORKER_ENABLED": "false",
    "BALE_BROADCAST_PAID_ENABLED": "false",
    "BALE_WALLET_CHECKOUT_ENABLED": "false",
    "TELEGRAM_STARS_REFUNDS_ENABLED": "false",
}


def safe_configuration() -> None:
    """Refuse schema mutations unless every Codespace safety flag matches."""
    for key, expected in REQUIRED.items():
        if os.environ.get(key) != expected:
            raise RuntimeError(f"Unsafe Codespace migration setting: {key}")
    if len(os.environ.get("LIVE_ADMIN_PASSWORD", "")) < 16:
        raise RuntimeError("Missing strong admin bootstrap password.")


def needs_legacy_baseline(
    existing_tables: set[str], revisions: set[str],
) -> bool:
    """Permit a baseline only when no application table or revision exists."""
    if revisions:
        return False

    application_tables = existing_tables - {"alembic_version"}
    if application_tables:
        raise RuntimeError(
            "Unversioned database is not empty; refusing automatic baseline. "
            "Inspect tables and Alembic history before continuing."
        )
    return True


async def is_virgin_database() -> bool:
    """Inspect existing PostgreSQL tables without changing any of them."""
    from db import engine

    async with engine.connect() as connection:
        tables = set(await connection.run_sync(
            lambda conn: inspect(conn).get_table_names(schema="public")
        ))
        revisions: set[str] = set()
        if "alembic_version" in tables:
            result = await connection.execute(
                text("SELECT version_num FROM alembic_version")
            )
            revisions = set(result.scalars().all())
        return needs_legacy_baseline(tables, revisions)


async def create_legacy_baseline() -> None:
    """Create legacy tables in one transaction, excluding all shop tables."""
    from db import engine
    from models.base import Base

    # Importing db above registers both legacy and new ORM models.
    legacy_tables = [
        table for table in Base.metadata.tables.values()
        if not table.name.startswith("shop_")
    ]
    if not legacy_tables:
        raise RuntimeError("Legacy SQLAlchemy metadata is empty.")

    # No checkfirst=True: an existing table must be an error, not overwritten.
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: Base.metadata.create_all(
                bind=conn, tables=legacy_tables, checkfirst=False
            )
        )
    print("Virgin Codespace: created PostgreSQL legacy ORM baseline.")


async def create_admin() -> None:
    """Provision one Argon2-hashed superadmin without overwriting accounts."""
    from db import session_maker
    from models.shop_staff import ShopStaff
    from utils.utils import hash_password

    async with session_maker() as session:
        account = await session.scalar(
            select(ShopStaff).where(ShopStaff.username == "shopadmin")
        )
        if account is None:
            session.add(
                ShopStaff(
                    username="shopadmin",
                    password_hash=hash_password(
                        os.environ["LIVE_ADMIN_PASSWORD"]
                    ),
                    role="superadmin",
                    is_active=True,
                    session_version=1,
                )
            )
            await session.commit()
            print("Codespace shopadmin created with private Argon2 hash.")
        else:
            print("Existing shopadmin preserved; password not overwritten.")


def main() -> None:
    """Execute all new shop migrations and verify the resulting full schema."""
    safe_configuration()
    config = Config("alembic.ini")

    if asyncio.run(is_virgin_database()):
        asyncio.run(create_legacy_baseline())
        # Last revision before the standalone PostgreSQL shop migrations.
        # Old SQLite PRAGMA revisions must never run on virgin PostgreSQL.
        command.stamp(config, LEGACY_BASE_REVISION)

    command.upgrade(config, "head")

    # Fail closed on incomplete tables or non-head schema.
    from db import create_db_and_tables

    asyncio.run(create_db_and_tables())
    asyncio.run(create_admin())
    print("Codespace schema and Alembic revision verified.")


if __name__ == "__main__":
    main()
