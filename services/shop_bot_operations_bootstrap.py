"""Codespaces-only additive bot operation upgrade and idempotent legacy seed.

The production path uses Alembic revision 20261103q001. This helper has a
fixed allowlist of nullable columns, never resets a volume or alters any
pre-existing order, wallet or receiver data.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection


_ADDITIVE_COLUMNS = {
    "verified_bot_id": "BIGINT",
    "verified_username": "VARCHAR(255)",
    "verified_at": "TIMESTAMP WITH TIME ZONE",
    "token_fingerprint": "VARCHAR(64)",
}


async def upgrade_codespace_bot_operations(
    connection: AsyncConnection,
) -> None:
    """Add only missing nullable credential verification fields in Codespaces."""
    actual_database = await connection.scalar(text("SELECT current_database()"))
    if actual_database != "shop_codespace":
        raise RuntimeError("Multi-bot bootstrap is restricted to Codespaces")
    columns = set(await connection.run_sync(
        lambda conn: [
            item["name"] for item in inspect(conn).get_columns(
                "shop_bot_credentials", schema="public",
            )
        ]
    ))
    for name, column_type in _ADDITIVE_COLUMNS.items():
        if name not in columns:
            # Both identifiers and types are fixed code constants.
            await connection.execute(text(
                "ALTER TABLE shop_bot_credentials "
                f"ADD COLUMN {name} {column_type}"
            ))
    await connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_shop_bot_credential_fingerprint "
        "ON shop_bot_credentials(token_fingerprint) "
        "WHERE token_fingerprint IS NOT NULL"
    ))
    # Keep current maintenance state as the effective Bot Registry state.
    # Re-running the bootstrap never overwrites an operator decision.
    await connection.execute(text(
        "INSERT INTO shop_bot_operations "
        "(bot_id, desired_state, owner_staff_id, environment) "
        "SELECT b.id, "
        "CASE WHEN COALESCE(p.maintenance_enabled, false) "
        "THEN 'maintenance' ELSE 'active' END, "
        "p.owner_staff_id, COALESCE(p.environment, 'staging') "
        "FROM shop_bots b "
        "LEFT JOIN shop_bot_profiles p ON p.platform = b.platform "
        "WHERE b.runtime_owner = 'legacy' "
        "ON CONFLICT (bot_id) DO NOTHING"
    ))
