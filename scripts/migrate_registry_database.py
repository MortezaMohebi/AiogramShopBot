"""Migrate a reviewed versioned PostgreSQL database after explicit retirement consent.

An empty or unversioned database must use the modern initializer. Replaying
historical SQLite-oriented migrations is never a fresh PostgreSQL setup path.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def require_revision(tables: set[str], revisions: list[str]) -> str:
    """Reject unversioned or ambiguous history before starting any migration."""
    if "alembic_version" not in tables or len(revisions) != 1 or not revisions[0]:
        raise RuntimeError(
            "Migration requires one existing Alembic revision. Use initialize "
            "only for a wholly empty database; review unversioned data manually."
        )
    return revisions[0]


async def verify_existing_database() -> None:
    """Read the installed PostgreSQL revision and confirm it belongs to this repo."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect, text
    from db import engine

    try:
        if engine.dialect.name != "postgresql":
            raise RuntimeError("Registry migration requires PostgreSQL.")
        async with engine.connect() as connection:
            tables = set(await connection.run_sync(
                lambda sync: inspect(sync).get_table_names(schema="public")
            ))
            revisions = []
            if "alembic_version" in tables:
                revisions = list(await connection.scalars(
                    text("SELECT version_num FROM alembic_version")
                ))
            revision = require_revision(tables, revisions)
            scripts = ScriptDirectory.from_config(
                Config(str(ROOT / "alembic.ini"))
            )
            scripts.get_revision(revision)
    finally:
        await engine.dispose()


def main() -> int:
    """Require caller acknowledgement before checking or changing a database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retire-original-schema", action="store_true", required=True,
    )
    parser.parse_args()
    asyncio.run(verify_existing_database())
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-x",
         "retire_original_schema=true", "upgrade", "head"],
        cwd=ROOT, check=False,
    ).returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        print(f"Registry migration: {error}", file=sys.stderr)
        sys.exit(1)
