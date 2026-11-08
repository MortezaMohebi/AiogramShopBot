"""Prove digital claim/refund interleavings in the guarded PostgreSQL QA stack.

Two application sessions hold real row locks behind explicit commit barriers.
A read-only observer verifies PostgreSQL blocking before each barrier opens.
All invoice, payment, delivery and refund operations use the native QA fakes;
this runner never constructs a provider-capable Bot or changes public config.
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import patch
from uuid import uuid4

from scripts.test_lab_safety import require_isolated_lab

require_isolated_lab()
if os.environ.get("SHOP_BETA_QA") != "1":
    raise RuntimeError("This PostgreSQL proof requires the named Beta QA stack.")

import config  # noqa: E402
from channels.telegram import TelegramTransport  # noqa: E402
from db import engine, session_maker  # noqa: E402
from models.shop_content import ShopOrder  # noqa: E402
from models.shop_digital_delivery import ShopDigitalDelivery  # noqa: E402
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase  # noqa: E402
from scripts.beta_commerce_e2e import Journey  # noqa: E402
from scripts.beta_storefront_e2e import MANIFEST, context  # noqa: E402
from services.shop_digital_fulfillment import (  # noqa: E402
    claim_one_delivery,
    complete_delivery,
)
from services.shop_payments import PaymentRejected  # noqa: E402
from services.shop_refunds import ShopRefundService  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

_TIMEOUT = 15


class CommitGate:
    """Pause one real transaction immediately before its durable commit."""

    def __init__(self, session: AsyncSession) -> None:
        """Retain the real session and explicit ready/release barriers."""
        self.session = session
        self.ready = asyncio.Event()
        self.release = asyncio.Event()

    def __getattr__(self, name):
        """Delegate every ORM operation to the unmodified PostgreSQL session."""
        return getattr(self.session, name)

    async def commit(self) -> None:
        """Hold acquired row locks until the other action is observably waiting."""
        self.ready.set()
        await asyncio.wait_for(self.release.wait(), timeout=_TIMEOUT)
        await self.session.commit()


class RefundFake:
    """Control the existing native QA refund fake without provider access."""

    def __init__(self, native, *, confirmed: bool, pause: bool = False) -> None:
        """Optionally keep provider-pending durable while its response waits."""
        self.native = native
        self.confirmed = confirmed
        self.calls = []
        self.release = asyncio.Event()
        if not pause:
            self.release.set()

    async def refund_star_payment(self, **payload):
        """Record a fake request, then return a controlled confirmation."""
        self.calls.append(payload)
        await asyncio.wait_for(self.release.wait(), timeout=_TIMEOUT)
        successful = await self.native.refund_star_payment(**payload)
        return successful if self.confirmed else False


async def backend_pid(session: AsyncSession) -> int:
    """Bind a known PostgreSQL connection under the production isolation level."""
    assert await session.scalar(text("SHOW transaction_isolation")) == "read committed"
    return int(await session.scalar(text("SELECT pg_backend_pid()")))


async def require_database_wait(task, *, waiter: int, holder: int) -> None:
    """Require actual PostgreSQL lock blocking, without timing-based sleeps."""
    async with asyncio.timeout(_TIMEOUT):
        async with engine.connect() as observer:
            while True:
                if task.done():
                    await task
                    raise AssertionError("Action finished before its Order lock was released.")
                blocked = await observer.scalar(
                    text("SELECT :holder = ANY(pg_blocking_pids(:waiter))"),
                    {"holder": holder, "waiter": waiter},
                )
                if blocked:
                    return


async def expect_refund_rejection(session, *, case_id: int, provider) -> None:
    """Require the service to reject without mistaking success for quarantine."""
    try:
        await ShopRefundService.refund_stars(
            session, case_id=case_id, bot=provider,
            enabled=True, reviewer="isolated-beta-qa",
        )
    except PaymentRejected:
        return
    raise AssertionError("This scheduled refund must require reconciliation.")


async def finish_tasks(tasks, *releases) -> None:
    """Release barriers and drain tasks before their PostgreSQL sessions close."""
    for release in releases:
        release.set()
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def paid_license(fixture: dict, *, user_id: int):
    """Reuse the raw customer Journey and verified synthetic payment pipeline."""
    journey = Journey(await context(fixture, "telegram"), user_id)
    with patch.object(config, "TELEGRAM_STARS_CHECKOUT_ENABLED", True):
        order_ids = await journey.order(fixture, ("license",))
        assert len(order_ids) == 1
        invoice = await journey.invoice(order_ids[0])
        assert invoice["currency"] == "XTR"
        await journey.settle(invoice)
    async with session_maker() as db:
        delivery = (await db.scalars(select(ShopDigitalDelivery).where(
            ShopDigitalDelivery.order_id == order_ids[0],
        ))).one()
        assert delivery.state == "queued" and delivery.kind == "license"
        case = await ShopRefundService.request(
            db, platform=journey.scope.platform, bot_id=journey.scope.bot_id,
            payer_id=user_id, order_id=order_ids[0],
            reason="Synthetic QA digital refund serialization",
        )
        return journey, order_ids[0], delivery.id, case.id


async def refund_wins(fixture: dict, *, user_id: int) -> None:
    """A pending refund releases Order only after new claims must be blocked."""
    journey, order_id, delivery_id, case_id = await paid_license(
        fixture, user_id=user_id,
    )
    provider = RefundFake(journey.native, confirmed=False, pause=True)
    async with session_maker() as refund_db, session_maker() as claim_db:
        refund_pid, claim_pid = await backend_pid(refund_db), await backend_pid(claim_db)
        cached_order = await claim_db.get(ShopOrder, order_id)
        assert cached_order.status == "paid"
        gate = CommitGate(refund_db)
        tasks = []
        try:
            refund_task = asyncio.create_task(expect_refund_rejection(
                gate, case_id=case_id, provider=provider,
            ))
            tasks.append(refund_task)
            await asyncio.wait_for(gate.ready.wait(), timeout=_TIMEOUT)
            claim_task = asyncio.create_task(claim_one_delivery(
                claim_db, bot_id=journey.scope.bot_id,
            ))
            tasks.append(claim_task)
            await require_database_wait(claim_task, waiter=claim_pid, holder=refund_pid)
            gate.release.set()
            assert await asyncio.wait_for(claim_task, timeout=_TIMEOUT) is None
            provider.release.set()
            await asyncio.wait_for(refund_task, timeout=_TIMEOUT)
        finally:
            await finish_tasks(tasks, gate.release, provider.release)
    async with session_maker() as db:
        assert (await db.get(ShopDigitalDelivery, delivery_id)).state == "blocked"
        assert (await db.get(ShopRefundCase, case_id)).status == "provider_pending"
        assert (await db.get(ShopOrder, order_id)).status == "paid"
    assert len(provider.calls) == 1
    assert not journey.native.documents
    assert not any(message.get("protect_content") for message in journey.native.messages)
    print("PASS  PostgreSQL refund-first: claim waits on Order, pending refund blocks private send")


async def claim_wins(fixture: dict, *, user_id: int) -> None:
    """A committed send claim rejects refund until its delivery is confirmed."""
    journey, order_id, delivery_id, case_id = await paid_license(
        fixture, user_id=user_id,
    )
    provider = RefundFake(journey.native, confirmed=True)
    async with session_maker() as claim_db, session_maker() as refund_db:
        claim_pid, refund_pid = await backend_pid(claim_db), await backend_pid(refund_db)
        gate = CommitGate(claim_db)
        tasks = []
        try:
            claim_task = asyncio.create_task(claim_one_delivery(
                gate, bot_id=journey.scope.bot_id,
            ))
            tasks.append(claim_task)
            await asyncio.wait_for(gate.ready.wait(), timeout=_TIMEOUT)
            refund_task = asyncio.create_task(expect_refund_rejection(
                refund_db, case_id=case_id, provider=provider,
            ))
            tasks.append(refund_task)
            await require_database_wait(refund_task, waiter=refund_pid, holder=claim_pid)
            gate.release.set()
            send = await asyncio.wait_for(claim_task, timeout=_TIMEOUT)
            assert send is not None and send.delivery_id == delivery_id
            await asyncio.wait_for(refund_task, timeout=_TIMEOUT)
            assert provider.calls == []
            await refund_db.rollback()
        finally:
            await finish_tasks(tasks, gate.release)
    # Complete the real native transport using the existing socket-free fake,
    # then show that an explicit refund of a known delivery remains possible.
    receipt = await TelegramTransport(
        journey.native, bot_id=journey.scope.bot_id,
    ).deliver_digital(send)
    async with session_maker() as db:
        await complete_delivery(db, delivery_id=delivery_id, provider_message_id=receipt)
    async with session_maker() as db:
        await ShopRefundService.refund_stars(
            db, case_id=case_id, bot=provider,
            enabled=True, reviewer="isolated-beta-qa",
        )
        assert (await db.get(ShopDigitalDelivery, delivery_id)).state == "delivered"
        assert (await db.get(ShopRefundCase, case_id)).status == "confirmed"
        assert (await db.get(ShopOrder, order_id)).status == "refunded"
        attempt = await db.scalar(select(ShopPaymentAttempt).where(
            ShopPaymentAttempt.order_id == order_id,
        ))
        assert attempt.status == "refunded"
    assert len(provider.calls) == 1
    print("PASS  PostgreSQL claim-first: refund waits, rejects unknown send, succeeds after fake delivery")


async def main() -> None:
    """Run both bounded lock schedules against the existing synthetic fixture."""
    try:
        assert engine.dialect.name == "postgresql"
        async with session_maker() as db:
            assert await db.scalar(text("SELECT current_database()")) == "shop_codespace"
            assert await db.scalar(text("SELECT current_user")) == "shop_codespace"
        fixture = json.loads(MANIFEST.read_text(encoding="utf-8"))
        suffix = uuid4().int % 10_000_000
        await refund_wins(fixture, user_id=900_000_000 + suffix)
        await claim_wins(fixture, user_id=920_000_000 + suffix)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
