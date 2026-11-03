"""Run a read-only HMAC/HTTP/database diagnosis inside the Codespace app.

The probe uses an existing staff record, never the account password. It
exercises the exact API paths used by the Next.js dashboard and reports
HTTP status codes without displaying tokens or customer data.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time

from aiohttp import ClientSession, ClientTimeout
from sqlalchemy import select, text

import config
from db import session_maker
from models.shop_staff import ShopStaff


ROUTES = (
    "/auth/me",
    "/overview",
    "/settings",
    "/referral-policy",
)


def assert_isolated_codespace() -> None:
    """Forbid probing a live customer database or unapproved environment."""
    if not (
        os.environ.get("POSTGRES_DB") == "shop_codespace"
        and os.environ.get("DB_HOST") == "postgres"
        and os.environ.get("CODESPACE_FRESH_SCHEMA") == "true"
    ):
        raise RuntimeError("Dashboard probe is only for an isolated Codespace.")
    if not config.NEXT_ADMIN_BRIDGE_ENABLED:
        raise RuntimeError("Next.js bridge is disabled.")
    if not config.NEXT_ADMIN_BRIDGE_SECRET:
        raise RuntimeError("Next.js bridge secret is missing.")


def signed_headers(path: str, staff_id: int, version: int) -> dict[str, str]:
    """Sign an empty GET body using the production Next.js HMAC format."""
    timestamp = str(int(time.time()))
    target = "/internal/admin/v1" + path
    digest = hashlib.sha256(b"").hexdigest()
    message = "\n".join((
        timestamp, "GET", target, digest, str(staff_id), str(version),
    ))
    signature = hmac.new(
        config.NEXT_ADMIN_BRIDGE_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "x-shop-time": timestamp,
        "x-shop-signature": signature,
        "x-shop-staff": str(staff_id),
        "x-shop-version": str(version),
    }


async def probe() -> int:
    """Check SQLAlchemy and four protected backend endpoints without writes."""
    assert_isolated_codespace()

    async with session_maker() as session:
        result = await session.scalar(text("SELECT 1"))
        if result != 1:
            raise RuntimeError("Direct PostgreSQL SELECT 1 returned no result.")
        staff = await session.scalar(
            select(ShopStaff)
            .where(ShopStaff.role == "superadmin", ShopStaff.is_active.is_(True))
            .order_by(ShopStaff.id)
            .limit(1)
        )
        if staff is None:
            raise RuntimeError("No active superadmin exists in the database.")
        staff_id, version = staff.id, staff.session_version

    print("PASS  PostgreSQL SELECT 1")
    status_codes: dict[str, int] = {}
    async with ClientSession(
        timeout=ClientTimeout(total=10), trust_env=False,
    ) as client:
        for path in ROUTES:
            address = "http://127.0.0.1:5000/internal/admin/v1" + path
            try:
                async with client.get(
                    address,
                    headers=signed_headers(path, staff_id, version),
                    allow_redirects=False,
                ) as response:
                    status_codes[path] = response.status
            except Exception as error:
                print(f"FAIL  {path}: {type(error).__name__}")
                status_codes[path] = 0

    for path, status in status_codes.items():
        label = "PASS" if status == 200 else "FAIL"
        print(f"{label}  GET {path}: HTTP {status}")

    if any(code != 200 for code in status_codes.values()):
        print(
            "Inspect the app container logs for the failing endpoint. "
            "A database SELECT 1 success does not imply API/analytics success."
        )
        return 1

    print("PASS  All signed dashboard backend API reads.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(probe()))
    except Exception as error:
        raise SystemExit(
            "FAIL  Dashboard probe (" + type(error).__name__ + "). "
            "Inspect app logs without exposing secrets."
        ) from None
