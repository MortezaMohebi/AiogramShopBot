"""Bot-scoped remote file-id lookup and persistence after verified uploads.

The original file always remains on private shop storage. The digest is used
only to distinguish bot-token namespaces; raw tokens must not enter SQL/logs.
"""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from models.shop_delivery import ShopRemoteFile
from models.shop_scope import legacy_id


def bot_fingerprint(token: str) -> str:
    """Return a stable opaque namespace for one Telegram or Bale bot token."""
    if not isinstance(token, str) or len(token) < 12:
        raise ValueError("Invalid bot token.")
    return sha256(token.encode("utf-8")).hexdigest()


async def cached_file_id(
    *, platform: str, bot_key: str, storage_key: str, kind: str,
    bot_id: str | None = None,
) -> str | None:
    """Read a remote file id belonging only to the specified bot namespace."""
    from db import session_maker

    async with session_maker() as session:
        result = await session.scalar(
            select(ShopRemoteFile.remote_file_id).where(
                ShopRemoteFile.bot_id == (bot_id or legacy_id(platform)),
                ShopRemoteFile.platform == platform,
                ShopRemoteFile.bot_fingerprint == bot_key,
                ShopRemoteFile.storage_key == storage_key,
                ShopRemoteFile.delivery_kind == kind,
            )
        )
        return result


async def remember_file_id(
    *,
    platform: str,
    bot_key: str,
    storage_key: str,
    kind: str,
    file_id: str,
    bot_id: str | None = None,
) -> None:
    """Cache only a confirmed provider file id with PostgreSQL conflict safety."""
    if not isinstance(file_id, str) or not 1 <= len(file_id) <= 4096:
        raise ValueError("Bot API did not return a usable file_id.")
    from db import session_maker

    values = {
        "platform": platform,
        "bot_id": bot_id or legacy_id(platform),
        "bot_fingerprint": bot_key,
        "storage_key": storage_key,
        "delivery_kind": kind,
        "remote_file_id": file_id,
    }
    statement = insert(ShopRemoteFile).values(**values)
    statement = statement.on_conflict_do_update(
        constraint="uq_shop_remote_file_bot_asset",
        set_={"remote_file_id": file_id},
    )
    async with session_maker() as session:
        await session.execute(statement)
        await session.commit()
