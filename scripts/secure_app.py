"""Registry-only ASGI entrypoint for Telegram and Bale customer bots.

No environment-owned bot, legacy dispatcher, SQLAdmin UI or historical
startup tasks are loaded. Bot credentials and receivers belong to Registry.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text

import config
from dashboard.admin_control_app import create_app
from dashboard.next_api import router as admin_router
from db import create_db_and_tables, session_maker
from services.shop_service_controls import service_enabled, watch_controls

_LOG = logging.getLogger(__name__)


async def supervise_receivers(base: FastAPI) -> None:
    """Acquire or release the shared receiver lease as the operator changes policy."""
    from services.shop_multibot_supervisor import MultiBotSupervisor

    async def release(worker: MultiBotSupervisor) -> None:
        try:
            await worker.close()
        except Exception as exc:
            _LOG.warning("Receiver cleanup failed: %s", type(exc).__name__)

    supervisor = None
    try:
        while True:
            if supervisor is not None and (
                not service_enabled("receivers") or not supervisor.owns_lease
            ):
                try:
                    await release(supervisor)
                finally:
                    supervisor = None
                    base.state.multi_bot_supervisor = None
            if supervisor is None and service_enabled("receivers"):
                candidate = MultiBotSupervisor(base)
                try:
                    await candidate.start()
                except asyncio.CancelledError:
                    await release(candidate)
                    raise
                except Exception as exc:
                    await release(candidate)
                    _LOG.warning("Receiver lease not ready: %s", type(exc).__name__)
                else:
                    if candidate.owns_lease:
                        supervisor = candidate
            await asyncio.sleep(2)
    finally:
        if supervisor is not None:
            await release(supervisor)
        base.state.multi_bot_supervisor = None


@asynccontextmanager
async def lifespan(base: FastAPI):
    """Verify the schema and own only the shared Registry receiver pool."""
    await create_db_and_tables()
    async with watch_controls(session_maker):
        monitor = asyncio.create_task(
            supervise_receivers(base), name="shop-receiver-supervisor",
        )
        try:
            yield
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)


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
