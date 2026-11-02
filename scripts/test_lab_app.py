"""FastAPI application for isolated dashboard integration tests only.

Do not import bot.py: its lifespan contacts Telegram, configures webhooks,
sends staff notifications and may launch polling. This app has none of those
side effects. It exposes the actual signed Next.js administration router.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from redis.asyncio import Redis
from sqlalchemy import text


def require_isolated_lab() -> None:
    """Fail before importing any application modules if safety gates differ."""
    required = {
        "SHOP_TEST_LAB": "1",
        "POSTGRES_DB": "shop_lab_test",
        "POSTGRES_USER": "shop_lab",
        "DB_HOST": "postgres",
        "WEBHOOK_HOST": "https://disabled.invalid",
        "NEXT_ADMIN_BRIDGE_ENABLED": "true",
        "SHOP_CAMPAIGN_DISPATCH_ENABLED": "false",
        "SHOP_BROADCAST_WORKER_ENABLED": "false",
        "BALE_BROADCAST_PAID_ENABLED": "false",
        "TELEGRAM_STARS_REFUNDS_ENABLED": "false",
        "TELEGRAM_STARS_CHECKOUT_ENABLED": "false",
        "TELEGRAM_FIAT_CHECKOUT_ENABLED": "false",
        "BALE_WALLET_CHECKOUT_ENABLED": "false",
        "CRYPTO_FORWARDING_MODE": "false",
        "SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR": "0",
        "BALE_BROADCAST_PREPARE_CHAT_ID": "0",
    }
    for name, expected in required.items():
        if os.environ.get(name) != expected:
            raise RuntimeError(
                f"Unsafe test lab configuration: {name} must be {expected!r}."
            )

    forbidden = (
        "TOKEN",
        "BALE_BOT_TOKEN",
        "BALE_WALLET_PROVIDER_TOKEN",
        "TELEGRAM_FIAT_PROVIDER_TOKEN",
        "TELEGRAM_WORKER_SECRET",
        "BALE_WEBHOOK_SECRET",
        "KRYPTO_EXPRESS_API_KEY",
    )
    for name in forbidden:
        if os.environ.get(name, "").strip():
            raise RuntimeError(
                f"Unsafe test lab: provider credential {name} is populated."
            )

    if len(os.environ.get("NEXT_ADMIN_BRIDGE_SECRET", "")) < 32:
        raise RuntimeError("The test bridge must use a strong unique key.")

    if len(os.environ.get("JWT_SECRET_KEY", "")) < 32:
        raise RuntimeError("The admin test secret is missing.")


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
        if database_name != "shop_lab_test":
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
