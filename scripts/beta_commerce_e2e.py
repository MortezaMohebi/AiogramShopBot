"""Exercise real PostgreSQL checkout, payment and workers with native fakes.

Only the guarded compose.beta-qa.yml runtime may import this runner. Every
external operation terminates in the fake clients in beta_storefront_e2e;
temporary Python configuration overrides never enable a running receiver.
"""

from __future__ import annotations

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
    callbacks,
    context,
    inbound,
)

import config
from channels.bale import BaleTransport
from channels.telegram import TelegramTransport
from db import engine, session_maker
from models.shop_checkout import ShopOrderLine
from models.shop_content import Product, ShopOrder
from models.shop_digital_delivery import ShopDigitalDelivery, ShopDigitalLicense
from models.shop_payment import ShopPaymentAttempt
from services.shop_digital_catalog import set_private_product_file
from services.shop_multibot_dispatch import dispatch
from services.shop_refunds import ShopRefundService
from sqlalchemy import select
from starlette.datastructures import Headers, UploadFile
from workers import shop_digital_delivery as digital_worker


class Journey:
    """One independently scoped customer, native provider fake and trusted Bot."""

    def __init__(self, scope, user_id: int) -> None:
        """Bind a server-authenticated context; inbound data cannot change it."""
        self.scope = scope
        self.user_id = user_id
        self.native = (
            FakeTelegram() if scope.platform.value == "telegram" else FakeBaleSession()
        )
        self.client = (
            self.native
            if scope.platform.value == "telegram"
            else BaleTransport("qa-fake-token", self.native, bot_id=scope.bot_id)
        )

    async def ask(self, action=None, *, message=None):
        """Run an actual raw provider update through the shared Dispatcher."""
        result = await dispatch(
            self.scope,
            self.client,
            inbound(self.user_id, action=action, message=message),
        )
        assert result["status"] in {"processed", "invoice_requested"}, result
        return self.native.messages[-1]

    async def order(self, fixture: dict, kinds: tuple[str, ...]) -> list[int]:
        """Walk cart actions and atomically submit a freshly signed preview."""
        await self.ask(message="/start")
        for kind in kinds:
            await self.ask(f"shop:add:{fixture['products'][kind]}")
        if "physical" in kinds:
            await self.ask("shop:address")
            await self.ask(message="نشانی آزمایشی تهران خیابان نمونه پلاک ۱۲")
            await self.ask(f"shop:ship:{fixture['shipping_id']}")
        preview = await self.ask("shop:checkout")
        buttons = [
            value for value in callbacks(preview) if value.startswith("shop:place:")
        ]
        assert len(buttons) == 1, preview["text"]
        # PostgreSQL row locks and uniqueness must survive two simultaneous taps.
        await asyncio.gather(self.ask(buttons[0]), self.ask(buttons[0]))
        await self.ask(buttons[0])
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
        await self.ask(f"shop:pay:{order_id}")
        assert len(self.native.invoices) == before + 1, self.native.messages[-1]["text"]
        await self.ask(f"shop:pay:{order_id}")
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
            assert digital.total_irr == 0, "Stars Order was represented as IRR"
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
    try:
        await commerce(json.loads(MANIFEST.read_text()))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
