"""FastAPI application for isolated dashboard integration tests only.

Do not import bot.py: its lifespan contacts Telegram, configures webhooks,
sends staff notifications and may launch polling. This app has none of those
side effects. It exposes the actual signed Next.js administration router.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from redis.asyncio import Redis
from sqlalchemy import text


from scripts.test_lab_safety import lab_database_identity, require_isolated_lab


require_isolated_lab()

from db import session_maker  # noqa: E402
from dashboard.next_api import router as admin_router  # noqa: E402
from config import REDIS_HOST, REDIS_PASSWORD  # noqa: E402

app = FastAPI(
    title="Telegram + Bale isolated admin lab",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(admin_router)


@app.get("/__lab/health", include_in_schema=False)
async def health() -> dict[str, object]:
    """Check the actual test PostgreSQL and Redis without contacting bots."""
    async with session_maker() as session:
        database_name = await session.scalar(text("SELECT current_database()"))
        if database_name != lab_database_identity()[0]:
            raise HTTPException(
                status_code=503, detail="Not an isolated test database."
            )
        await session.execute(text("SELECT 1"))
    redis = Redis(
        host=REDIS_HOST,
        password=REDIS_PASSWORD,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        if not await redis.ping():
            raise HTTPException(status_code=503, detail="Redis unavailable.")
    finally:
        await redis.aclose()
    return {
        "ok": True,
        "mode": "isolated_test",
        "provider_dispatch_enabled": False,
    }
