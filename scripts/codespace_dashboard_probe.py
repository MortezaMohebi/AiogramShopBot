"""Safely verify SQL and authenticated Next-to-FastAPI API requests.

This probe is exclusively for the isolated Codespaces database. To exercise
its new server-side security middleware, it creates one transient diagnostic
session using the normal issuance API, calls read-only endpoints and revokes
the session in a ``finally`` block. It never reads a password, sends a bot
message, modifies shop records or prints session credentials.
"""

from __future__ import annotations

import asyncio
import hashlib
import os

from aiohttp import ClientSession, ClientTimeout
from sqlalchemy import func, select, text

import config
from db import session_maker
from models.shop_admin_control import AdminSession
from models.shop_staff import ShopStaff
from scripts.dashboard_probe_signing import signed_headers
from services import shop_admin_security as security


ROUTES = (
    "/auth/me",
    "/overview",
    "/settings",
    "/referral-policy",
)


def assert_isolated_codespace() -> None:
    """Refuse to issue diagnostic credentials outside the disposable lab."""
    required = {
        "POSTGRES_DB": "shop_codespace",
        "DB_NAME": "shop_codespace",
        "DB_HOST": "postgres",
        "DB_USER": "shop_codespace",
        "CODESPACE_FRESH_SCHEMA": "true",
    }
    if any(os.environ.get(key) != value for key, value in required.items()):
        raise RuntimeError("Dashboard diagnostics are restricted to Codespaces.")
    if not config.NEXT_ADMIN_BRIDGE_ENABLED or len(
        config.NEXT_ADMIN_BRIDGE_SECRET
    ) < 32:
        raise RuntimeError("Signed internal dashboard bridge is not configured.")


async def diagnostic_identity() -> tuple[int, int, str, str]:
    """Issue one transient session without evicting a real admin device."""
    async with session_maker() as session:
        value = await session.scalar(text("SELECT 1"))
        if value != 1:
            raise RuntimeError("PostgreSQL connectivity check failed.")
        db_name = await session.scalar(text("SELECT current_database()"))
        if db_name != "shop_codespace":
            raise RuntimeError("Unexpected PostgreSQL database.")
        staff = await session.scalar(
            select(ShopStaff).where(
                ShopStaff.role == "superadmin",
                ShopStaff.is_active.is_(True),
            ).order_by(ShopStaff.id).with_for_update()
        )
        if staff is None:
            raise RuntimeError("No enabled superadmin exists in Codespaces.")

        # issue_session enforces a limit of ten concurrent sessions.
        # Refuse rather than evicting an administrator's active device.
        active_count = await session.scalar(
            select(func.count()).select_from(AdminSession).where(
                AdminSession.staff_id == staff.id,
                AdminSession.revoked_at.is_(None),
            )
        )
        if int(active_count or 0) >= 10:
            raise RuntimeError(
                "Too many active admin sessions for a non-disruptive probe."
            )

        token = await session.run_sync(
            lambda sync: security.issue_session(
                sync, staff, "Codespaces diagnostic only"
            )
        )
        row = await session.scalar(
            select(AdminSession).where(
                AdminSession.token_hash == hashlib.sha256(
                    token.encode("utf-8")
                ).hexdigest()
            )
        )
        if row is None:
            raise RuntimeError("Diagnostic session was not persisted.")
        identity = (staff.id, staff.session_version, token, row.id)
        await session.commit()
        return identity


async def revoke_diagnostic_session(staff_id: int, session_id: str) -> None:
    """Invalidate the only temporary bearer regardless of test outcomes."""
    async with session_maker() as session:
        await session.run_sync(
            lambda sync: security.revoke_session(sync, staff_id, session_id)
        )
        await session.commit()


async def probe() -> int:
    """Exercise real protected FastAPI reads using a temporary valid session."""
    assert_isolated_codespace()
    staff_id, version, token, session_id = await diagnostic_identity()
    print("PASS  PostgreSQL SELECT 1 and temporary session issuance")

    status_codes: dict[str, int] = {}
    try:
        async with ClientSession(
            timeout=ClientTimeout(total=10), trust_env=False,
        ) as client:
            async with client.get(
                "http://127.0.0.1:5000/healthz",
                allow_redirects=False,
            ) as response:
                status_codes["/healthz"] = response.status
            for path in ROUTES:
                address = "http://127.0.0.1:5000/internal/admin/v1" + path
                try:
                    async with client.get(
                        address,
                        headers=signed_headers(
                            path,
                            staff_id,
                            version,
                            token,
                            config.NEXT_ADMIN_BRIDGE_SECRET,
                        ),
                        allow_redirects=False,
                    ) as response:
                        status_codes[path] = response.status
                except Exception as error:
                    print(f"FAIL  {path}: {type(error).__name__}")
                    status_codes[path] = 0
    finally:
        # A failed or timed-out API call never leaves its bearer usable.
        await revoke_diagnostic_session(staff_id, session_id)
        print("PASS  Diagnostic session revoked")

    for path, status in status_codes.items():
        print(f"{'PASS' if status == 200 else 'FAIL'}  GET {path}: HTTP {status}")
    if any(code == 428 for code in status_codes.values()):
        print("Protected dashboard reads are gated: complete MFA enrollment in the private dashboard, then retry.")
        return 1
    if any(code != 200 for code in status_codes.values()):
        print("Inspect app logs for the failing route; secrets were not printed.")
        return 1
    print("PASS  Authenticated dashboard API health and database reads")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(probe()))
    except Exception as error:
        raise SystemExit(
            "FAIL  Dashboard probe (" + type(error).__name__ + "). "
            "Inspect app logs without exposing secrets."
        ) from None
