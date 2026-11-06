"""Initialize the default Store without creating bots or provider credentials."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection

from models.shop_multibot import DEFAULT_STORE_ID, ShopStore


async def ensure_default_store(connection: AsyncConnection) -> None:
    """Ensure the initial Store exists within the caller's locked transaction."""
    await connection.run_sync(_ensure_default_store)


def _ensure_default_store(connection: Connection) -> None:
    """Create only the Store, preserving existing names and operator state."""
    connection.execute(
        pg_insert(ShopStore.__table__)
        .values(
            id=DEFAULT_STORE_ID,
            slug="default",
            name="فروشگاه اصلی",
            state="active",
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    slug = connection.scalar(
        select(ShopStore.slug).where(ShopStore.id == DEFAULT_STORE_ID)
    )
    if slug != "default":
        raise RuntimeError("Default Store registry identity is inconsistent")
