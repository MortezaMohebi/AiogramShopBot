"""Registry-only ASGI entrypoint for Telegram and Bale customer bots.

No environment-owned bot, legacy dispatcher, SQLAdmin UI or historical
startup tasks are loaded. Bot credentials and receivers belong to Registry.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text

import config
from dashboard.admin_control_app import create_app
from dashboard.next_api import router as admin_router
from db import create_db_and_tables, session_maker


@asynccontextmanager
async def lifespan(base: FastAPI):
    """Verify the schema and own only the shared Registry receiver pool."""
    await create_db_and_tables()
    supervisor = None
    try:
        if config.MULTIBOT_V2_RUNTIME_ENABLED:
            from services.shop_multibot_supervisor import MultiBotSupervisor

            supervisor = MultiBotSupervisor(base)
            await supervisor.start()
        yield
    finally:
        if supervisor is not None:
            await supervisor.close()


base = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
base.include_router(admin_router)


@base.get("/healthz", include_in_schema=False)
async def health() -> dict:
    """Check PostgreSQL and Redis without contacting either messenger."""
    async with session_maker() as session:
        await session.execute(text("SELECT 1"))
    redis = Redis(host=config.REDIS_HOST, password=config.REDIS_PASSWORD,
                  socket_connect_timeout=2, socket_timeout=2)
    try:
        if not await redis.ping():
            raise RuntimeError("Redis unavailable")
    finally:
        await redis.aclose()
    return {"ok": True, "runtime": "registry"}


app = create_app(base, live_receivers=False)
