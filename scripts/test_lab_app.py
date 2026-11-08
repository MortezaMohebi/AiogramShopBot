"""FastAPI application for isolated dashboard integration tests only.

Receivers stay disabled. The lab exposes the actual signed Next.js
administration router without contacting messaging providers.
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

@app.get("/healthz", include_in_schema=False)
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


from dashboard.admin_control_app import create_app  # noqa: E402

# Keep lab health routes before the production root fallback.
# Exercise production session and StoreContext with receivers disabled.
app = create_app(app, live_receivers=False)
