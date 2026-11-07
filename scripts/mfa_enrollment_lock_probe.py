"""Exercise enrollment/session lock competition in an owned PostgreSQL schema.

Only run inside the dedicated Fake Provider QA environment. Every account,
session and schema belongs to this probe and is removed in its finally block.
No owner account, configured credential, bot or payment is read or changed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import uuid4


def sqlstate(error: BaseException) -> str | None:
    """Find a controlled PostgreSQL error code without exposing SQL or values."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        value = getattr(error, "sqlstate", None)
        if value:
            return value
        error = getattr(error, "orig", None) or error.__cause__
    return None


async def run(expect_deadlock: bool) -> None:
    """Race real route proof/staging against real receiver session validation."""
    assert os.environ.get("SHOP_MCP_QA") == "1"
    assert os.environ.get("SHOP_BETA_QA") == "1"
    for name in ("TOKEN", "BALE_BOT_TOKEN", "BALE_WALLET_PROVIDER_TOKEN",
                 "TELEGRAM_FIAT_PROVIDER_TOKEN"):
        assert not os.environ.get(name)

    from sqlalchemy import text
    from sqlalchemy.engine import URL
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from starlette.requests import Request

    import config
    from dashboard import admin_control_api as api
    from models.base import Base
    from models.shop_admin_control import AdminEvent, AdminProfile, AdminSession
    from models.shop_multibot import ShopStore
    from models.shop_staff import ShopStaff
    from services import shop_admin_security as security

    schema = "qa_mfa_lock_" + uuid4().hex
    url = URL.create(
        "postgresql+asyncpg", username=config.DB_USER, password=config.DB_PASS,
        host=config.DB_HOST, port=int(config.DB_PORT), database=config.DB_NAME,
    )
    admin = create_async_engine(url)
    engine = None
    original_proof, original_throttle = api.fresh_proof, api.throttle
    tasks = []
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={
            "server_settings": {"search_path": schema},
        })
        tables = [ShopStaff.__table__, ShopStore.__table__,
                  AdminProfile.__table__, AdminSession.__table__,
                  AdminEvent.__table__]
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: Base.metadata.create_all(sync, tables=tables),
            )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        password = "Synthetic-PostgreSQL-proof-only-123!"
        async with sessions() as db:
            member = ShopStaff(
                username="qa-lock-probe", role="superadmin", is_active=True,
                password_hash=api.hash_password(password), session_version=1,
            )
            db.add(member)
            await db.flush()
            staff_id = member.id
            await db.run_sync(lambda sync: security.profile_for(sync, staff_id))
            token = await db.run_sync(
                lambda sync: security.issue_session(sync, member, "Lock probe"),
            )
            row = await db.run_sync(
                lambda sync: security.validate_session(sync, member, token),
            )
            session_id = row.id
            await db.commit()

        proof_held, release_proof = asyncio.Event(), asyncio.Event()
        competing_session_held = asyncio.Event()

        async def throttle(*args):
            """Keep external Redis outside this isolated database-lock test."""

        async def paused_proof(*args, **kwargs):
            """Pause the actual proof after its transaction acquired locks."""
            await original_proof(*args, **kwargs)
            proof_held.set()
            await release_proof.wait()

        api.throttle, api.fresh_proof = throttle, paused_proof

        async def enrollment():
            """Execute the real compatibility route using its own transaction."""
            async with sessions() as db:
                member = await db.get(ShopStaff, staff_id)
                request = Request({
                    "type": "http", "method": "POST", "path": "/account/mfa-setup",
                    "headers": [(b"x-shop-session", token.encode())],
                    "state": {"admin_session_id": session_id},
                })
                result = await api.mfa_setup(
                    api.MfaSetup(current_password=password), request, member, db,
                )
                assert result["ok"] is True
                return "enrollment_completed"

        async def concurrent_validation():
            """Acquire the real Session then Profile locks used by middleware."""
            async with sessions() as db:
                member = await db.get(ShopStaff, staff_id)
                await db.run_sync(
                    lambda sync: security.validate_session(sync, member, token),
                )
                competing_session_held.set()
                await db.run_sync(lambda sync: security.profile_for(sync, staff_id))
                await db.commit()
                return "session_validated"

        tasks.append(asyncio.create_task(enrollment()))
        await asyncio.wait_for(proof_held.wait(), 15)
        tasks.append(asyncio.create_task(concurrent_validation()))
        try:
            # The fixed route holds Session already, so the other transaction
            # waits here until enrollment commits rather than forming a cycle.
            await asyncio.wait_for(competing_session_held.wait(), 0.5)
        except TimeoutError:
            pass
        release_proof.set()
        outcomes = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), 20,
        )
        errors = [item for item in outcomes if isinstance(item, BaseException)]
        if expect_deadlock:
            assert any(sqlstate(error) == "40P01" for error in errors)
            print(json.dumps({"status": "REPRODUCED", "sqlstate": "40P01"}))
        else:
            assert not errors, "Concurrent enrollment must not deadlock"
            print(json.dumps({"status": "PASS", "outcomes": outcomes}))
    finally:
        api.fresh_proof, api.throttle = original_proof, original_throttle
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if engine is not None:
            await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()
        print(json.dumps({"probe_schema_cleanup": "PASS"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-deadlock", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.expect_deadlock))
    except Exception as error:
        # Never expose a driver exception's connection details or SQL parameters.
        print(json.dumps({"status": "FAIL", "type": type(error).__name__}))
        raise SystemExit(1) from None
