"""Create a fresh Codespaces PostgreSQL schema directly from SQLAlchemy.

This is a deliberately disposable development database with no historical
records to migrate. It does not run, stamp, replay, or emulate Alembic
revisions. Schema creation is allowed only on an empty, isolated Codespaces
database; reruns validate the existing schema without overwriting records.

A populated or partially initialized schema is a hard failure.
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import inspect, select, text

# Require an exact database identity, not merely a user-controlled flag.
REQUIRED = {
    "CODESPACE_FRESH_SCHEMA": "true",
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
    """Reject schema operations outside the named Codespaces environment."""
    for name, expected in REQUIRED.items():
        if os.environ.get(name) != expected:
            raise RuntimeError(
                f"Unsafe Codespace bootstrap setting: {name}."
            )
    if len(os.environ.get("LIVE_ADMIN_PASSWORD", "")) < 16:
        raise RuntimeError("A strong admin bootstrap password is required.")


def classify_schema(
    existing_tables: set[str], expected_tables: set[str],
    *, old_revisions_present: bool = False,
) -> str:
    """Choose initialization only for an empty schema, never for partial data.

    A leftover, empty Alembic version table from an earlier failed attempt
    is harmless. A versioned database with an unknown history is not.
    """
    if not expected_tables:
        raise RuntimeError("SQLAlchemy model metadata is empty.")

    user_tables = existing_tables - {"alembic_version"}

    if old_revisions_present:
        raise RuntimeError(
            "Existing Alembic revision state detected. The Codespaces "
            "fresh-schema bootstrap cannot rewrite versioned data."
        )

    if not user_tables:
        return "create"

    if user_tables == expected_tables:
        return "verify"

    raise RuntimeError(
        "Partial or unexpected database tables detected; no changes made. "
        "Inspect your Codespaces database before an explicit reset."
    )


async def bootstrap_schema() -> None:
    """Create all model tables atomically, or verify an existing complete set."""
    # db.py imports every legacy and shared-shop model into Base.metadata.
    from db import engine, verify_codespace_schema
    from models.base import Base
    from services.shop_multibot_bootstrap import adopt_legacy_codespace

    expected_tables = set(Base.metadata.tables)

    async with engine.begin() as connection:
        actual_database = await connection.scalar(
            text("SELECT current_database()")
        )
        if actual_database != "shop_codespace":
            raise RuntimeError("Refusing a non-Codespaces database.")

        # Transaction-scoped lock prevents concurrent bootstrap runs.
        await connection.execute(
            text("SELECT pg_advisory_xact_lock(90211003)")
        )

        tables = set(await connection.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names(
                schema="public"
            )
        ))
        old_revisions_present = False
        if "alembic_version" in tables:
            revisions = await connection.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            old_revisions_present = revisions.first() is not None

        action = classify_schema(
            tables,
            expected_tables,
            old_revisions_present=old_revisions_present,
        )

        if action == "create":
            await connection.run_sync(
                lambda sync_conn: Base.metadata.create_all(
                    bind=sync_conn,
                    checkfirst=False,
                )
            )
            print(
                "Created all fresh PostgreSQL tables directly from "
                "SQLAlchemy metadata; no Alembic revisions applied."
            )
        else:
            print(
                "Existing complete Codespaces schema found. "
                "Preserving database tables and records."
            )

        # Verify every expected ORM table and column before committing DDL.
        await verify_codespace_schema(connection)
        # The compatibility entrypoint performs the same append-only adoption
        # as scripts.security_bootstrap; neither requires a fresh/reset DB.
        await adopt_legacy_codespace(connection)


async def create_admin() -> None:
    """Provision a hashed administrator only when the account is absent."""
    from db import session_maker
    from models.shop_staff import ShopStaff
    from utils.utils import hash_password

    async with session_maker() as session:
        # Only a completely empty staff register permits bootstrap. This
        # prevents re-provisioning a deliberately disabled or renamed admin.
        account = await session.scalar(
            select(ShopStaff.id).order_by(ShopStaff.id).limit(1)
        )
        if account is not None:
            print("Existing administrator preserved; password not changed.")
            return

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
        print("Created Codespaces shopadmin (Argon2 hash only).")


async def main() -> None:
    """Bootstrap and validate the schema before creating the admin user."""
    safe_configuration()
    await bootstrap_schema()
    await create_admin()
    print("Codespaces fresh-schema bootstrap completed.")


if __name__ == "__main__":
    asyncio.run(main())
