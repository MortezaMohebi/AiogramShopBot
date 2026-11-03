"""Read or acknowledge a staged Telegram receiving-mode request.

Only the isolated Codespaces app may access this Redis key. JSON, provider
secrets and customer data are never printed. Acknowledgement happens only
after the newly started process reports the requested mode as active.
"""

from __future__ import annotations

import asyncio
import os
import sys

from redis.asyncio import Redis

import config


PENDING_KEY = "shop:pending:telegram:update_mode"
MODES = frozenset({"polling", "webhook"})


async def main() -> None:
    """Show a validated mode, or clear an already applied request."""
    if (
        os.environ.get("POSTGRES_DB") != "shop_codespace"
        or os.environ.get("CODESPACE_FRESH_SCHEMA") != "true"
    ):
        raise RuntimeError("Codespace mode command refused.")

    operation = sys.argv[1] if len(sys.argv) > 1 else "read"
    if operation not in {"read", "clear"}:
        raise RuntimeError("Unsupported mode request operation.")

    cache = Redis(
        host=config.REDIS_HOST,
        password=config.REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=2,
    )
    try:
        pending = await cache.get(PENDING_KEY)
        if pending is None:
            print("none")
            return
        if pending not in MODES:
            raise RuntimeError("Unknown pending Telegram mode.")
        if operation == "clear":
            if pending != config.TELEGRAM_UPDATE_MODE:
                raise RuntimeError("Pending mode is not active yet.")
            await cache.delete(PENDING_KEY)
            print("cleared")
        else:
            print(pending)
    finally:
        await cache.aclose()


if __name__ == "__main__":
    asyncio.run(main())
