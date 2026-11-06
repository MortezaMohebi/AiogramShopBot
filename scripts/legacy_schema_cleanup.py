"""Inspect or explicitly retire legacy schema in the isolated Beta database.

Dry-run: ``python -m scripts.legacy_schema_cleanup``.
Apply after backup: ``python -m scripts.legacy_schema_cleanup --apply``.
Versioned databases must use the guarded Alembic cleanup revision instead.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
from pathlib import Path

from sqlalchemy import inspect, text


def _load_cleanup_revision():
    """Reuse the self-contained reviewed revision without a runtime import."""
    path = (
        Path(__file__).resolve().parents[1] / "migrations" / "versions"
        / "20261107z001_retire_original_schema.py"
    )
    specification = importlib.util.spec_from_file_location(
        "original_schema_retirement", path,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("Original schema retirement revision is unavailable")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


async def cleanup(*, apply: bool = False) -> list[str]:
    """Inspect or retire schema under exact Beta environment guards."""
    from scripts.codespace_bootstrap import safe_configuration

    safe_configuration()
    from db import engine

    revision = _load_cleanup_revision()
    async with engine.begin() as connection:
        database = await connection.scalar(text("SELECT current_database()"))
        if database != "shop_codespace":
            raise RuntimeError("Original cleanup is restricted to Codespaces")
        await connection.execute(text("SELECT pg_advisory_xact_lock(90211003)"))
        tables = await connection.run_sync(
            lambda sync: inspect(sync).get_table_names(schema="public")
        )
        if "alembic_version" in tables and await connection.scalar(
            text("SELECT version_num FROM alembic_version LIMIT 1")
        ):
            raise RuntimeError(
                "Versioned databases must use the cleanup migration"
            )
        names = await connection.run_sync(revision.existing_original_tables)
        workflow_counts = await connection.run_sync(
            revision.retire_workflow_bindings
        )
        if apply:
            names = await connection.run_sync(revision.drop_original_tables)
        else:
            await connection.run_sync(
                lambda sync: revision.validate_original_table_dependencies(
                    sync, names,
                )
            )
            await connection.run_sync(revision.transfer_singleton_settings)
            await connection.run_sync(revision.validate_retired_identity_links)
        action = "Retired" if apply else "Would retire"
        table_names = ", ".join(names) or "(none)"
        print(f"{action} {len(names)} legacy tables: {table_names}")
        print(
            f"{action} workflow fallbacks: {workflow_counts['fallbacks']}; "
            f"bridge entries: {workflow_counts['bridges']}"
        )
        return names


def main() -> None:
    """Default to read-only inspection; require --apply for retirement."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Retire only allowlisted legacy tables and workflow entry pointers",
    )
    arguments = parser.parse_args()
    asyncio.run(cleanup(apply=arguments.apply))


if __name__ == "__main__":
    main()
