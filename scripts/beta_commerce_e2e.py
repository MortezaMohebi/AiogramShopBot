"""Exercise real PostgreSQL checkout, payment and workers with native fakes.

Only the guarded compose.beta-qa.yml runtime may import this runner. Every
external operation terminates in the fake clients in beta_storefront_e2e;
temporary Python configuration overrides never enable a running receiver.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
import json
from unittest.mock import patch
from uuid import uuid4

from scripts.beta_storefront_e2e import (
    MANIFEST,
    FakeBaleSession,
    FakeTelegram,
    StorefrontJourney,
    VisibleTap,
    context,
    inbound,
    seed,
)

import config
from channels.bale import BaleTransport
from channels.telegram import TelegramTransport
from db import engine, session_maker
from models.shop_checkout import ShopOrderLine
from models.shop_checkout_policy import ShopStoreCheckoutPolicy
from models.shop_content import Product, ShopOrder
from models.shop_digital_delivery import ShopDigitalDelivery, ShopDigitalLicense
from models.shop_payment import ShopPaymentAttempt
from services.shop_digital_catalog import set_private_product_file
from services.shop_cart import ShopCartFlow
from services.shop_checkout_policy import save_bot_checkout, save_store_checkout
from services.shop_multibot_dispatch import dispatch
from services.shop_refunds import ShopRefundService
from sqlalchemy import select, text
from starlette.datastructures import Headers, UploadFile
from workers import shop_digital_delivery as digital_worker


class Journey(StorefrontJourney):
    """One independently scoped customer, native provider fake and trusted Bot."""

    async def prepare_checkout(
        self, fixture: dict, kinds: tuple[str, ...],
    ) -> VisibleTap:
        """Build a quote and return the actual rendered confirmation button."""
        await self.ask(message="/start")
        for kind in kinds:
            product_id = fixture["products"][kind]
            await self.open_product(product_id)
            await self.ask(f"shop:add:{product_id}")
        if "physical" in kinds:
            await self.ask("shop:address")
            await self.ask(await self.add_address())
            await self.ask("shop:cart")
            await self.ask("shop:shipping")
            await self.ask(f"shop:ship:{fixture['shipping_id']}")
        preview = await self.ask("shop:checkout")
        buttons = [
            tap for action, tap in (await self.actions(preview)).items()
            if action.startswith("shop:place:")
        ]
        assert len(buttons) == 1, preview["text"]
        return buttons[0]

    async def order(self, fixture: dict, kinds: tuple[str, ...]) -> list[int]:
        """Walk cart actions and atomically submit a freshly signed preview."""
        confirmation = await self.prepare_checkout(fixture, kinds)
        # PostgreSQL row locks and uniqueness must survive two simultaneous taps.
        results = await asyncio.gather(self.tap(confirmation), self.tap(confirmation))
        assert all(r["status"] in {"processed", "stale_callback"} for r in results)
        assert (await self.tap(confirmation))["status"] in {"processed", "stale_callback"}
        async with session_maker() as db:
            rows = (
                await db.scalars(
                    select(ShopOrder)
                    .where(
                        ShopOrder.bot_id == self.scope.bot_id,
                        ShopOrder.platform_user_id == self.user_id,
                    )
                    .order_by(ShopOrder.id)
                )
            ).all()
            expected = (
                2
                if len(kinds) > 1
                and "physical" in kinds
                and self.scope.platform.value == "telegram"
                else 1
            )
            assert len(rows) == expected, "Repeated checkout created extra Orders"
            assert all(row.status == "approved_unpaid" for row in rows)
            assert all(
                row.terms_accepted_at and row.terms_version_snapshot == "qa-v1"
                for row in rows
            )
            return [row.id for row in rows]

    async def invoice(self, order_id: int, *, unknown=False) -> dict:
        """Use real invoice planning/account selection with an offline API fake."""
        before = len(self.native.invoices)
        if isinstance(self.native, FakeTelegram):
            self.native.fail_invoice = unknown
        await self.ask(message="/orders")
        tap = await self.prepare(f"shop:pay:{order_id}")
        assert (await self.tap(tap))["status"] == "invoice_requested"
        assert len(self.native.invoices) == before + 1, self.native.messages[-1]["text"]
        assert (await self.tap(tap))["status"] in {"invoice_requested", "stale_callback"}
        assert len(self.native.invoices) == before + 1, "Uncertain invoice was resent"
        if isinstance(self.native, FakeTelegram):
            self.native.fail_invoice = False
        async with session_maker() as db:
            attempt = await db.scalar(
                select(ShopPaymentAttempt).where(
                    ShopPaymentAttempt.order_id == order_id,
                )
            )
            assert attempt is not None and attempt.payment_account_id
            assert attempt.status == ("dispatch_unknown" if unknown else "invoice_sent")
            return dict(
                payload=attempt.payload,
                currency=attempt.currency,
                amount=attempt.amount,
            )

    async def settle(self, invoice: dict) -> None:
        """Reject altered precheckout, verify native success and replay once."""
        query = {
            "id": uuid4().hex,
            "from": {"id": self.user_id},
            "invoice_payload": invoice["payload"],
            "currency": invoice["currency"],
            "total_amount": invoice["amount"] + 1,
        }
        result = await dispatch(self.scope, self.client, {"pre_checkout_query": query})
        assert result["status"] == "declined"
        query["total_amount"] = invoice["amount"]
        result = await dispatch(self.scope, self.client, {"pre_checkout_query": query})
        assert result["status"] == "accepted", result
        charge = "qa-charge-" + uuid4().hex
        payment = {
            "invoice_payload": invoice["payload"],
            "currency": invoice["currency"],
            "total_amount": invoice["amount"],
            "telegram_payment_charge_id": charge,
            "provider_payment_charge_id": "qa-provider-" + uuid4().hex,
        }
        if isinstance(self.native, FakeBaleSession):
            self.native.transactions[charge] = {
                "status": "paid",
                "id": charge,
                "userID": self.user_id,
                "amount": invoice["amount"],
            }
        raw = inbound(self.user_id)
        raw["message"].pop("text")
        raw["message"]["successful_payment"] = payment
        assert (await dispatch(self.scope, self.client, raw))["status"] == "settled"
        assert (await dispatch(self.scope, self.client, raw))[
            "status"
        ] == "already_settled"


async def blocked_by(pid: int, waiting: asyncio.Task) -> None:
    """Observe a real PostgreSQL block before releasing its current holder."""
    async with asyncio.timeout(5):
        while True:
            assert not waiting.done(), "Checkout policy operations did not serialize"
            async with session_maker() as db:
                blocked = await db.scalar(text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND :holder = ANY(pg_blocking_pids(pid)))"
                ), {"holder": pid})
            if blocked:
                return
            await asyncio.sleep(0.02)


async def shopper_orders(journey: Journey) -> list[ShopOrder]:
    """Read orders and assert reviewing or submitting has not started a charge."""
    async with session_maker() as db:
        orders = list(await db.scalars(select(ShopOrder).where(
            ShopOrder.store_id == journey.scope.store_id,
            ShopOrder.bot_id == journey.scope.bot_id,
            ShopOrder.platform_user_id == journey.user_id,
        )))
        attempts = list(await db.scalars(select(ShopPaymentAttempt).where(
            ShopPaymentAttempt.order_id.in_([order.id for order in orders]),
        )))
    assert not attempts and not journey.native.invoices
    return orders


async def review_terms() -> None:
    """Read every checkout terms page without creating orders or charges."""
    fixture = await seed(persist_manifest=False)
    suffix = uuid4().int % 1_000_000
    store_id = fixture["stores"][0]
    long_terms = (
        "شروع-شرایط-آزمایشی\n"
        + ("ارسال خرید پس از بررسی موجودی و دریافت رسید انجام می‌شود.\n" * 120)[:4900]
        + "\nپایان-شرایط-آزمایشی"
    )
    with patch.multiple(
        config,
        TELEGRAM_STARS_CHECKOUT_ENABLED=True,
        BALE_WALLET_CHECKOUT_ENABLED=True,
    ):
        for mode_index, mode in enumerate(("manual", "instant")):
            async with session_maker() as db:
                policy = await db.get(ShopStoreCheckoutPolicy, store_id)
                await save_store_checkout(
                    db, store_id=store_id, actor_id=fixture["admin_id"],
                    expected_version=policy.version, mode=mode,
                    terms_version="qa-long-v1", terms_text=long_terms,
                )
            for bot_index, bot_key in enumerate(("telegram", "bale")):
                journey = Journey(
                    await context(fixture, bot_key),
                    831_000_000 + suffix + mode_index * 2 + bot_index,
                )
                await journey.prepare_checkout(fixture, ("file",))
                initial = journey.native.messages[-1]["text"]
                terms = next(
                    action for action in await journey.actions()
                    if action.startswith("ux:terms:")
                )
                page = await journey.ask(terms)
                assert "شروع-شرایط-آزمایشی" in page["text"]
                assert not await shopper_orders(journey)
                for page_index in range(1, 6):
                    actions = await journey.actions(page)
                    back = next(
                        action for action in actions if action.startswith("shop:checkout:")
                    )
                    next_page = next((
                        action for action in actions
                        if action.startswith("ux:terms:")
                        and int(action.split(":")[3]) == page_index
                    ), None)
                    if next_page is None:
                        break
                    page = await journey.ask(next_page)
                    assert not await shopper_orders(journey)
                assert "پایان-شرایط-آزمایشی" in page["text"]
                returned = await journey.ask(back)
                assert returned["text"] == initial
                assert not await shopper_orders(journey)
                await journey.ask("shop:cart")
                assert not await shopper_orders(journey)
                await journey.ask("shop:checkout")
                confirm = next(
                    tap for action, tap in (await journey.actions()).items()
                    if action.startswith("shop:place:")
                )
                assert (await journey.tap(confirm))["status"] == "processed"
                assert (await journey.tap(confirm))["status"] == "stale_callback"
                orders = await shopper_orders(journey)
                assert len(orders) == 1 and orders[0].terms_accepted_at
                assert orders[0].terms_version_snapshot == "qa-long-v1"
                assert orders[0].status == (
                    "pending_review" if mode == "manual" else "approved_unpaid"
                )
                print(
                    f"PASS  {bot_key} {mode}: one-tap long Terms, same review on "
                    "Back, no read/cancel effects, one explicit order"
                )


async def policy_races() -> None:
    """Exercise both checkout-policy linearization orders on real PostgreSQL."""
    fixture = await seed(persist_manifest=False)
    suffix = uuid4().int % 1_000_000
    telegram = Journey(await context(fixture, "telegram"), 821_000_000 + suffix)
    bale = Journey(await context(fixture, "bale"), 822_000_000 + suffix)
    with patch.multiple(
        config,
        TELEGRAM_STARS_CHECKOUT_ENABLED=True,
        BALE_WALLET_CHECKOUT_ENABLED=True,
    ):
        confirmation = await telegram.prepare_checkout(fixture, ("file",))
        held = asyncio.Event()
        release = asyncio.Event()
        async with session_maker() as writer_db:
            policy = await writer_db.get(ShopStoreCheckoutPolicy, telegram.scope.store_id)
            pid = await writer_db.scalar(text("SELECT pg_backend_pid()"))
            original_commit = writer_db.commit

            async def hold_writer_commit():
                held.set()
                await asyncio.wait_for(release.wait(), 10)
                await original_commit()

            with patch.object(writer_db, "commit", hold_writer_commit):
                writer = asyncio.create_task(save_store_checkout(
                    writer_db, store_id=telegram.scope.store_id, actor_id=fixture["admin_id"],
                    expected_version=policy.version, mode=policy.mode,
                    terms_version=policy.terms_version,
                    terms_text=policy.terms_text + " روش پیگیری سفارش به‌روز شده است.",
                ))
                decision = None
                try:
                    await asyncio.wait_for(held.wait(), 5)
                    decision = asyncio.create_task(telegram.tap(confirmation))
                    await blocked_by(pid, decision)
                    assert not await shopper_orders(telegram)
                finally:
                    release.set()
                    results = await asyncio.gather(
                        *(task for task in (writer, decision) if task is not None),
                        return_exceptions=True,
                    )
            assert all(isinstance(result, dict) for result in results), results
        assert not await shopper_orders(telegram), "Old confirmation accepted changed terms"
        assert (await telegram.tap(confirmation))["status"] == "stale_callback"
        preview = await telegram.ask(message="/checkout")
        refreshed = next(
            tap for action, tap in (await telegram.actions(preview)).items()
            if action.startswith("shop:place:")
        )
        assert refreshed != confirmation
        assert (await telegram.tap(refreshed))["status"] == "processed"
        orders = await shopper_orders(telegram)
        assert len(orders) == 1 and orders[0].terms_version_snapshot == "qa-v1"

        # No Bot override exists yet. Hold the decision after it takes its
        # policy read lock and prove an inserting writer must wait for it.
        confirmation = await bale.prepare_checkout(fixture, ("file",))
        held, release = asyncio.Event(), asyncio.Event()
        decision_pid = None
        original_quote = ShopCartFlow._quote

        async def hold_decision_quote(flow, cart, db, **kwargs):
            nonlocal decision_pid
            if decision_pid is None:
                decision_pid = await db.scalar(text("SELECT pg_backend_pid()"))
                held.set()
                await asyncio.wait_for(release.wait(), 10)
            return await original_quote(flow, cart, db, **kwargs)

        async def insert_override():
            async with session_maker() as db:
                return await save_bot_checkout(
                    db, bot_id=bale.scope.bot_id, actor_id=fixture["admin_id"],
                    expected_version=0, mode_override="manual",
                )

        with patch.object(ShopCartFlow, "_quote", hold_decision_quote):
            decision = asyncio.create_task(bale.tap(confirmation))
            writer = None
            try:
                await asyncio.wait_for(held.wait(), 5)
                writer = asyncio.create_task(insert_override())
                await blocked_by(decision_pid, writer)
                assert not await shopper_orders(bale)
            finally:
                release.set()
                results = await asyncio.gather(
                    *(task for task in (decision, writer) if task is not None),
                    return_exceptions=True,
                )
        assert results[0]["status"] == "processed"
        assert results[1]["mode_override"] == "manual"
        orders = await shopper_orders(bale)
        assert len(orders) == 1 and orders[0].status == "approved_unpaid"
        assert orders[0].terms_accepted_at and orders[0].terms_version_snapshot == "qa-v1"
        assert (await bale.tap(confirmation))["status"] == "stale_callback"
        assert len(await shopper_orders(bale)) == 1
    print("PASS  PostgreSQL checkout: writer-first terms refresh, decision-first Bot override insertion, zero charges or duplicate orders")


async def commerce(fixture: dict) -> None:
    """Verify split payment independence and real digital worker crash behavior."""
    suffix = uuid4().int % 10_000_000
    tg = Journey(await context(fixture, "telegram"), 710_000_000 + suffix)
    bale = Journey(await context(fixture, "bale"), 730_000_000 + suffix)
    license_only = Journey(await context(fixture, "telegram"), 750_000_000 + suffix)
    ambiguous = Journey(await context(fixture, "telegram"), 770_000_000 + suffix)
    crash = Journey(await context(fixture, "telegram"), 790_000_000 + suffix)
    # Overrides exist only in this fake-client process, never the API service.
    with patch.multiple(
        config,
        TELEGRAM_STARS_CHECKOUT_ENABLED=True,
        TELEGRAM_FIAT_CHECKOUT_ENABLED=True,
        TELEGRAM_IRR_MINOR_MULTIPLIER=1,
        BALE_WALLET_CHECKOUT_ENABLED=True,
    ):
        mixed_ids = await tg.order(fixture, ("physical", "file"))
        bale_ids = await bale.order(fixture, ("file", "license"))
        license_ids = await license_only.order(fixture, ("license",))
        ambiguous_ids = await ambiguous.order(fixture, ("license",))
        crash_ids = await crash.order(fixture, ("license",))
        async with session_maker() as db:
            mixed = (
                await db.scalars(select(ShopOrder).where(ShopOrder.id.in_(mixed_ids)))
            ).all()
            physical = next(
                row for row in mixed if row.checkout_part_kind == "physical"
            )
            digital = next(row for row in mixed if row.checkout_part_kind == "digital")
            assert physical.checkout_group_id == digital.checkout_group_id
            assert physical.total_irr == 1500 and digital.total_stars_snapshot == 7
            assert not digital.shipping_irr and not digital.discount_irr
            pinned = await db.scalar(
                select(ShopOrderLine.digital_asset_id_snapshot).where(
                    ShopOrderLine.order_id == digital.id,
                )
            )
            assert pinned == fixture["asset"]["file"]["id"]
            # Mutating the live catalog must not change already approved Orders.
            file_product = await db.get(Product, fixture["products"]["file"])
            file_product.price = 9000
            file_product.price_stars = 19
            await db.commit()
            await set_private_product_file(
                db,
                store_id=fixture["stores"][0],
                product_id=file_product.id,
                uploaded=UploadFile(
                    file=BytesIO(b"%PDF-1.4\n% QA version TWO\n%%EOF\n"),
                    filename="qa-private-v2.pdf",
                    headers=Headers({"content-type": "application/pdf"}),
                ),
            )
        ir = await tg.invoice(physical.id, unknown=True)
        stars = await tg.invoice(digital.id)
        assert ir["amount"] == 1500 and ir["currency"] == "IRR"
        assert stars["amount"] == 7 and stars["currency"] == "XTR"
        assert "provider_token" not in tg.native.invoices[-1]
        await tg.settle(stars)
        async with session_maker() as db:
            assert (await db.get(ShopOrder, physical.id)).status == "pending_payment"
            assert (await db.get(ShopOrder, digital.id)).status == "paid"
            receipts = (
                await db.scalars(
                    select(ShopDigitalDelivery).where(
                        ShopDigitalDelivery.order_id == digital.id,
                    )
                )
            ).all()
            assert len(receipts) == 1 and receipts[0].asset_id == pinned
        await tg.settle(ir)
        for journey, ids in (
            (bale, bale_ids),
            (license_only, license_ids),
            (ambiguous, ambiguous_ids),
            (crash, crash_ids),
        ):
            invoice = await journey.invoice(ids[0])
            await journey.settle(invoice)
        print(
            "PASS  PostgreSQL: mixed checkout atomic double-tap, IRR/XTR independent settlement, frozen price/file, native Bale inquiry, invoice timeout no retry"
        )

    # A real worker consumes real queued rows, through native Telegram/Bale fakes.
    providers = {
        fixture["bots"]["telegram"]: FakeTelegram(),
        fixture["bots"]["bale"]: FakeBaleSession(),
    }

    @asynccontextmanager
    async def provider(bot_id):
        native = providers[bot_id]
        yield (
            TelegramTransport(native, bot_id=bot_id)
            if isinstance(native, FakeTelegram)
            else BaleTransport("qa-fake-token", native, bot_id=bot_id)
        )

    # Separate normal queued work from intentionally ambiguous/crashed work.
    async with session_maker() as db:
        deferred = (
            await db.scalars(
                select(ShopDigitalDelivery).where(
                    ShopDigitalDelivery.order_id.in_(ambiguous_ids + crash_ids),
                )
            )
        ).all()
        for row in deferred:
            row.state = "needs_review"
        await db.commit()
    with patch.object(digital_worker, "_transport_for_bot", provider):
        for _ in range(5):
            await asyncio.gather(
                digital_worker._deliver_one(fixture["bots"]["telegram"]),
                digital_worker._deliver_one(fixture["bots"]["telegram"]),
                digital_worker._deliver_one(fixture["bots"]["bale"]),
                digital_worker._deliver_one(fixture["bots"]["bale"]),
            )
        assert len(providers[fixture["bots"]["telegram"]].documents) == 1
        assert len(providers[fixture["bots"]["bale"]].documents) == 1
        assert all(
            native.documents[0]["sha256"] == fixture["file_sha256"]
            for native in providers.values()
        )
        for journey, ids, failure in (
            (ambiguous, ambiguous_ids, "provider"),
            (crash, crash_ids, "receipt"),
        ):
            async with session_maker() as db:
                row = await db.scalar(
                    select(ShopDigitalDelivery).where(
                        ShopDigitalDelivery.order_id == ids[0]
                    )
                )
                row.state = "queued"  # Test fixture: this row has never been attempted.
                await db.commit()
            native = providers[journey.scope.bot_id]
            before = len(native.messages)
            if failure == "provider":
                native.fail_delivery = True
                await digital_worker._deliver_one(journey.scope.bot_id)
                native.fail_delivery = False
            else:

                async def lose_receipt(*_args, **_kwargs):
                    raise RuntimeError(
                        "Synthetic DB outage after Provider acknowledged send"
                    )

                with patch.object(digital_worker, "complete_delivery", lose_receipt):
                    await digital_worker._deliver_one(journey.scope.bot_id)
            assert len(native.messages) == before + 1
            assert not await digital_worker._deliver_one(journey.scope.bot_id)
            assert len(native.messages) == before + 1, (
                "Ambiguous one-time license was sent twice"
            )
            async with session_maker() as db:
                row = await db.scalar(
                    select(ShopDigitalDelivery).where(
                        ShopDigitalDelivery.order_id == ids[0]
                    )
                )
                assert row.state == (
                    "needs_review" if failure == "provider" else "sending"
                )
        async with session_maker() as db:
            delivered = (
                await db.scalars(
                    select(ShopDigitalDelivery).where(
                        ShopDigitalDelivery.order_id.in_(
                            mixed_ids + bale_ids + license_ids
                        ),
                    )
                )
            ).all()
            assert len(delivered) == 4 and all(
                row.state == "delivered" and row.provider_message_id
                for row in delivered
            )
            licenses = [row.license_id for row in delivered if row.kind == "license"]
            assert len(licenses) == len(set(licenses)) == 2
            license_rows = [await db.get(ShopDigitalLicense, key) for key in licenses]
            assert all(row.state == "delivered" for row in license_rows)
    print(
        "PASS  Native Telegram/Bale digital worker: pinned private files, unique licenses, concurrent claims, receipt IDs, timeout/crash quarantine without replay"
    )

    # Refund only one side, with a fake official Stars API, then the other side.
    async with session_maker() as db:
        case = await ShopRefundService.request(
            db,
            platform=tg.scope.platform,
            payer_id=tg.user_id,
            bot_id=tg.scope.bot_id,
            order_id=digital.id,
            reason="Synthetic QA independent refund",
        )
        await ShopRefundService.refund_stars(
            db,
            case_id=case.id,
            bot=tg.native,
            enabled=True,
            reviewer="isolated-beta-qa",
        )
        assert (await db.get(ShopOrder, physical.id)).status == "paid"
        case = await ShopRefundService.request(
            db,
            platform=tg.scope.platform,
            payer_id=tg.user_id,
            bot_id=tg.scope.bot_id,
            order_id=physical.id,
            reason="Synthetic QA independent fiat refund",
        )
        await ShopRefundService.confirm_manual(
            db,
            case_id=case.id,
            provider_reference="qa-fake-proof-" + uuid4().hex,
            reviewer="isolated-beta-qa",
        )
        assert (await db.get(ShopOrder, digital.id)).status == "refunded"
        assert (await db.get(ShopOrder, physical.id)).status == "refunded"
    print(
        "PASS  Mixed group: both refunds independently reconcile without changing the other payment"
    )


async def main() -> None:
    """Reuse only the exact synthetic fixture prepared by the guarded seed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=("commerce", "policy", "terms"), default="commerce",
    )
    args = parser.parse_args()
    try:
        if args.stage == "policy":
            await policy_races()
        elif args.stage == "terms":
            await review_terms()
        else:
            await commerce(json.loads(MANIFEST.read_text()))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
