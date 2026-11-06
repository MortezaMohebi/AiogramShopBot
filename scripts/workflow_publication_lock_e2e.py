"""Race gateway-first and Studio publication locks in isolated PostgreSQL.

Run in the named provider-free QA container. A private disposable schema holds
four synthetic rows. Both competitors call the real publication service; the
gateway competitor first holds the real Store admission mutex. Interception
stops each call once both parent locks are acquired, before any publication.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from uuid import uuid4

from scripts.test_lab_safety import require_isolated_lab

require_isolated_lab()

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from db import engine  # noqa: E402
from models.shop_multibot import ShopStore  # noqa: E402
from models.shop_staff import ShopStaff  # noqa: E402
from models.shop_workflow import ShopWorkflow  # noqa: E402
from models.shop_workflow_runtime import PublicationPreview  # noqa: E402
from services import shop_admin_security as security  # noqa: E402
from services.shop_runtime import publication  # noqa: E402
from services.shop_store_context import (  # noqa: E402
    AuthorizedStore,
    StoreContext,
)


class OrderedLocks(Exception):
    """Stop immediately after both real SQL parent locks are acquired."""


class LockBoundary:
    """Observe actual SQL locks without replacing the production service."""

    def __init__(self, session, *, admitted=False):
        self.session, self.store_locked = session, admitted
        self.preview_locked = asyncio.Event()
        self.first_attempt = asyncio.Event()
        self.first_table = None

    async def scalar(self, statement):
        """Let PostgreSQL acquire every real lock before signaling progress."""
        sql = str(statement)
        table = "store" if "FROM shop_stores" in sql else "preview"
        if self.first_table is None:
            self.first_table = table
            self.first_attempt.set()
        result = await self.session.scalar(statement)
        if table == "store":
            self.store_locked = True
        else:
            self.preview_locked.set()
        if self.store_locked and self.preview_locked.is_set():
            raise OrderedLocks()
        return result


async def race():
    """Fail on a real deadlock when the two supported entry points compete."""
    schema = "mcp_lock_" + uuid4().hex
    owner, workflow, preview = (str(uuid4()) for _ in range(3))
    async with engine.begin() as connection:
        await connection.execute(text('CREATE SCHEMA "' + schema + '"'))
        await connection.execute(
            text('SET LOCAL search_path TO "' + schema + '", public')
        )
        await connection.run_sync(
            lambda sync: ShopStore.__table__.create(sync)
        )
        await connection.run_sync(
            lambda sync: ShopStaff.__table__.create(sync)
        )
        await connection.run_sync(
            lambda sync: ShopWorkflow.__table__.create(sync)
        )
        await connection.run_sync(
            lambda sync: PublicationPreview.__table__.create(sync)
        )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                text('SET LOCAL search_path TO "' + schema + '", public')
            )
            store = ShopStore(id=owner, slug="lock-test", name="Lock QA")
            actor = ShopStaff(
                id=1,
                username="lock-qa",
                password_hash="!disabled",
                role="superadmin",
                is_active=True,
            )
            session.add_all([store, actor])
            await session.flush()
            session.add(
                ShopWorkflow(
                    id=workflow,
                    store_id=owner,
                    key="lock-qa",
                    name="Lock QA",
                    created_by=1,
                )
            )
            await session.flush()
            session.add(
                PublicationPreview(
                    id=preview,
                    store_id=owner,
                    workflow_id=workflow,
                    revision=1,
                    staff_id=1,
                    session_id=owner,
                    digest="f" * 64,
                    request={},
                    report={},
                    expires_at=security.clock() + timedelta(minutes=5),
                )
            )
            await session.commit()
        allowed = AuthorizedStore(
            owner, "lock-test", "Lock QA", "active", "manager"
        )
        scope = StoreContext(1, owner, (allowed,), (owner,), owner, owner, 1)
        async with (
            AsyncSession(engine) as native,
            AsyncSession(engine) as studio,
        ):
            for session in (native, studio):
                await session.execute(
                    text('SET LOCAL search_path TO "' + schema + '", public')
                )
            # This is the native gateway's real admission mutex, not a test lock.
            await publication.lock_routes(native, owner)
            native_boundary = LockBoundary(native, admitted=True)
            studio_boundary = LockBoundary(studio)

            async def activate(boundary):
                try:
                    await publication.activate(
                        boundary,
                        actor=actor,
                        scope=scope,
                        preview_id=preview,
                        approved=True,
                    )
                except OrderedLocks:
                    return "ordered"
                except Exception as error:
                    original = getattr(error, "orig", error)
                    return getattr(original, "sqlstate", type(error).__name__)
                finally:
                    await boundary.session.rollback()

            competing = asyncio.create_task(activate(studio_boundary))
            await asyncio.wait_for(studio_boundary.first_attempt.wait(), 5)
            if studio_boundary.first_table == "preview":
                await asyncio.wait_for(
                    studio_boundary.preview_locked.wait(), 5
                )
            results = await asyncio.wait_for(
                asyncio.gather(activate(native_boundary), competing), 10
            )
            assert results == ["ordered", "ordered"], {
                "results": results,
                "studio_first": studio_boundary.first_table,
            }
            return {
                "status": "PASS",
                "competitors": results,
                "studio_first": studio_boundary.first_table,
            }
    finally:
        # Only the uniquely named schema created above is disposable test data.
        async with engine.begin() as connection:
            await connection.execute(
                text('DROP SCHEMA "' + schema + '" CASCADE')
            )


async def main():
    """Return redacted, reproducible PostgreSQL evidence without provider calls."""
    try:
        print(json.dumps(await race(), sort_keys=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
