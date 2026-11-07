"""Initialize a completely empty PostgreSQL database with the Registry schema.

Run explicitly with ``python -m scripts.initialize_registry_database``. Existing
installations must use their reviewed Alembic upgrade path. Historical revision
upgrade functions are never executed by this initializer.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session


_BOOTSTRAP_LOCK = 90211003


def _current_migration_head() -> tuple[ScriptDirectory, str]:
    """Resolve the single installed revision head without running its code."""
    root = Path(__file__).resolve().parents[1]
    configuration = Config(str(root / "alembic.ini"))
    configuration.set_main_option("script_location", str(root / "migrations"))
    scripts = ScriptDirectory.from_config(configuration)
    heads = scripts.get_heads()
    if len(heads) != 1:
        raise RuntimeError("Initialization requires exactly one migration head")
    return scripts, heads[0]


def _require_empty_database(connection: Connection) -> None:
    """Reject every existing application table, including Alembic state."""
    inspector = inspect(connection)
    schemas = (
        [name for name in inspector.get_schema_names()
         if name not in {"information_schema", "pg_catalog"}
         and not name.startswith("pg_")]
        if connection.dialect.name == "postgresql" else [None]
    )
    for schema in schemas:
        if inspector.get_table_names(schema=schema):
            raise RuntimeError(
                "Fresh initialization requires a completely empty database; "
                "existing installations must use a reviewed Alembic upgrade"
            )


def _stamp_current_head(
    connection: Connection, scripts: ScriptDirectory, head: str,
) -> None:
    """Record the installed head on the existing DDL/seed transaction."""
    MigrationContext.configure(connection).stamp(scripts, head)


def initialize_registry_schema(connection: Connection) -> str:
    """Create and stamp modern schema in the caller's atomic transaction.

    PostgreSQL callers share the bootstrap advisory lock with Codespaces and
    security initialization. SQLite is supported here solely for disposable
    transactional unit tests; the command-line entry point requires PostgreSQL.
    """
    if not connection.in_transaction():
        raise RuntimeError("Initialization requires an explicit transaction")
    if connection.dialect.name == "postgresql":
        connection.execute(text(
            f"SELECT pg_advisory_xact_lock({_BOOTSTRAP_LOCK})"
        ))
    _require_empty_database(connection)
    scripts, head = _current_migration_head()

    # Import the production registry without connecting its configured engine.
    # Every current model must be registered before create_all resolves FKs.
    import db  # noqa: F401
    from models.base import Base
    from models.shop_multibot import DEFAULT_STORE_ID
    from services.shop_multibot_bootstrap import _ensure_default_store
    from services.shop_uom import seed_store_units

    if not Base.metadata.tables or any(
        not name.startswith("shop_") for name in Base.metadata.tables
    ):
        raise RuntimeError("Current Registry model metadata is invalid")
    Base.metadata.create_all(bind=connection, checkfirst=False)
    _ensure_default_store(connection)
    with Session(bind=connection) as session:
        seed_store_units(session, DEFAULT_STORE_ID)
        session.flush()
    _stamp_current_head(connection, scripts, head)
    return head


async def initialize_database() -> str:
    """Create an empty PostgreSQL deployment atomically, without any bot seed."""
    from db import engine

    try:
        if engine.dialect.name != "postgresql":
            raise RuntimeError("Registry initialization requires PostgreSQL")
        async with engine.begin() as connection:
            head = await connection.run_sync(initialize_registry_schema)
    finally:
        await engine.dispose()
    print(
        f"Initialized Registry database at {head}; "
        "no bots or credentials created. Provision staff explicitly."
    )
    return head


def main() -> None:
    """Initialize only when the operator invokes the dedicated command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    asyncio.run(initialize_database())


if __name__ == "__main__":
    main()
