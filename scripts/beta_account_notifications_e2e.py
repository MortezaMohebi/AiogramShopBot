"""Run guarded PostgreSQL account, linking, credit and notification journeys.

Only the isolated Beta QA stack may import this runner. All provider work
terminates in explicit native Telegram/Bale fakes. Synthetic users, products
and receipts are additive; no table, existing fixture or credential is reset.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
import re
from unittest.mock import patch
from uuid import uuid4

from scripts.test_lab_safety import require_isolated_lab

require_isolated_lab()
if os.environ.get("SHOP_BETA_QA") != "1":
    raise RuntimeError("Account QA requires the named isolated Beta stack.")

from sqlalchemy import func, select, text  # noqa: E402
from starlette.requests import Request  # noqa: E402

from channels.bale import BaleTransport  # noqa: E402
from channels.telegram import TelegramTransport  # noqa: E402
from dashboard import shop_customer_experience_api as admin_api  # noqa: E402
from db import engine, session_maker  # noqa: E402
from models.shop_bot_catalog_acl import ShopBotProductRule  # noqa: E402
from models.shop_content import Product, ShopIdentity, ShopOrder  # noqa: E402
from models.shop_customer_crm import ShopCustomerConsentEvent  # noqa: E402
from models.shop_customer_links import ShopCustomerLinkRequest  # noqa: E402
from models.shop_customer_notifications import (  # noqa: E402
    ShopCustomerNotificationOutbox,
    ShopStockAlert,
)
from models.shop_customer_support import (  # noqa: E402
    ShopSupportMessage,
    ShopSupportTicket,
)
from models.shop_engagement import ShopWalletEntry  # noqa: E402
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase  # noqa: E402
from models.shop_staff import ShopStaff  # noqa: E402
from models.shop_store_commerce import (  # noqa: E402
    ShopStoreCustomer,
    ShopStoreCustomerLinkEvent,
)
from scripts.beta_commerce_e2e import Journey  # noqa: E402
from scripts.beta_storefront_e2e import (  # noqa: E402
    MANIFEST,
    FakeBaleSession,
    FakeTelegram,
    VisibleTap,
    callbacks,
    context,
    seed,
)
from services import shop_admin_security as security  # noqa: E402
from services.shop_customer_notifications import (  # noqa: E402
    claim_outbox_message,
    enqueue_notification,
    prepare_stock_alerts,
)
from services.shop_identity import register_customer  # noqa: E402
from services.shop_refunds import ShopRefundService  # noqa: E402
from services.shop_store_context import StoreContext, memberships  # noqa: E402
from services.shop_wallet import ShopWalletService, StoreCreditRejected  # noqa: E402
from workers import shop_customer_notifications as notification_worker  # noqa: E402


def stage(message: str) -> None:
    """Flush a bounded checkpoint so a failing PG run names its active stage."""
    print(message, flush=True)


async def identity_for(journey: Journey) -> dict:
    """Read immutable identity/customer IDs through exact authenticated scope."""
    async with session_maker() as db:
        row = await db.scalar(select(ShopIdentity).where(
            ShopIdentity.bot_id == journey.scope.bot_id,
            ShopIdentity.platform == journey.scope.platform.value,
            ShopIdentity.platform_user_id == journey.user_id,
            ShopIdentity.store_id == journey.scope.store_id,
        ))
        assert row is not None and row.customer_id is not None
        return {
            "id": row.id,
            "customer_id": row.customer_id,
            "consent": row.allow_announcements,
        }


async def postgres_guard(fixture: dict) -> None:
    """Verify the actual DB identity before adding any synthetic records."""
    assert engine.dialect.name == "postgresql", "Actual PostgreSQL is required"
    assert len(set(fixture["stores"])) == 2
    async with session_maker() as db:
        assert await db.scalar(text("SELECT current_database()")) == "shop_codespace"
        assert await db.scalar(text("SELECT current_user")) == "shop_codespace"
    stage("PASS  Safety: isolated Beta PostgreSQL identity and fixture verified")


async def enrollment_races(scopes: dict, base: int, run: str) -> None:
    """Race independent real PG sessions for absent and legacy-null accounts."""
    stage("RUN   PostgreSQL enrollment races: new and existing-null identities")
    for offset, provider in enumerate(("telegram", "bale")):
        scope = scopes[provider]
        for legacy in (False, True):
            user_id = base + offset * 10 + int(legacy)
            marker = f"qa-enrollment-{run}-{provider}-{int(legacy)}"
            if legacy:
                async with session_maker() as db:
                    db.add(ShopIdentity(
                        store_id=scope.store_id, bot_id=scope.bot_id,
                        platform=scope.platform.value,
                        platform_user_id=user_id, first_name=marker,
                    ))
                    await db.commit()
            gate = asyncio.Event()
            ready = asyncio.Event()
            ready_count = 0

            async def enroll() -> tuple[int, int]:
                """Start six authenticated registrations on separate sessions."""
                nonlocal ready_count
                async with session_maker() as db:
                    # Preloading mirrors the stale identity-map orphan case.
                    if legacy:
                        preloaded = await db.scalar(select(ShopIdentity).where(
                            ShopIdentity.bot_id == scope.bot_id,
                            ShopIdentity.platform_user_id == user_id,
                        ))
                        assert preloaded.customer_id is None
                    ready_count += 1
                    if ready_count == 6:
                        ready.set()
                    await gate.wait()
                    row = await register_customer(
                        db, platform=scope.platform, bot_id=scope.bot_id,
                        platform_user_id=user_id, first_name=marker,
                    )
                    assert row.allow_announcements is False
                    return row.id, row.customer_id

            tasks = [asyncio.create_task(enroll()) for _ in range(6)]
            # Every legacy row is cached before the first competing write.
            # A bounded barrier avoids sleeps and does not replace PG locks.
            await asyncio.wait_for(ready.wait(), timeout=30)
            gate.set()
            owners = await asyncio.wait_for(asyncio.gather(*tasks), timeout=45)
            assert len(set(owners)) == 1, "Concurrent /start split one identity"
            async with session_maker() as db:
                count = await db.scalar(select(func.count()).select_from(
                    ShopIdentity,
                ).where(
                    ShopIdentity.bot_id == scope.bot_id,
                    ShopIdentity.platform_user_id == user_id,
                ))
                customers = await db.scalar(select(func.count()).select_from(
                    ShopStoreCustomer,
                ).where(
                    ShopStoreCustomer.store_id == scope.store_id,
                    ShopStoreCustomer.display_name == marker,
                ))
                assert count == customers == 1, "Enrollment left an orphan Customer"
    # Equal numeric IDs must also stay independent across Bots and Stores.
    owners = []
    for key in ("telegram", "telegram_second", "bale", "foreign"):
        scope = scopes[key]
        async with session_maker() as db:
            row = await register_customer(
                db, platform=scope.platform, bot_id=scope.bot_id,
                platform_user_id=base + 30, first_name=f"qa-isolation-{run}",
            )
            owners.append((row.id, row.customer_id))
    assert len({owner[0] for owner in owners}) == 4
    assert len({owner[1] for owner in owners}) == 4
    stage("PASS  PostgreSQL: concurrent enrollment, no orphan, four-Bot ID isolation")


ACCOUNT_GROUPS = ("ux:account:benefits", "ux:account:settings")


async def account_action(journey: Journey, action: str) -> dict:
    """Find an action through Account or one of its visible groups."""
    await journey.ask(message="/account")
    if action in await journey.actions():
        return await journey.ask(action)
    for group in ACCOUNT_GROUPS:
        await journey.ask(message="/account")
        await journey.ask(group)
        if action in await journey.actions():
            return await journey.ask(action)
    raise AssertionError(f"Account action {action} is missing from both visible groups")


async def raw_denial(journey: Journey, action: str, *withheld: str) -> dict:
    """Inject an intentionally forged old read and inspect only its own response."""
    before = len(journey.native.messages)
    prior = journey.native.messages[-1]
    result = await journey.tap(VisibleTap(prior["message_id"], action))
    assert result["status"] in {"processed", "stale_callback", "blocked"}, result
    fresh = journey.native.messages[before:]
    assert all(secret not in reply["text"] for secret in withheld for reply in fresh)
    return fresh[-1] if fresh else {"text": ""}


async def account_menu(journey: Journey) -> None:
    """Follow every visible Account action within at most two selections."""
    expected = {
        "ux:profile": "مشخصات", "ux:addresses": "نشانی",
        "ux:wallet": "موجودی", "ux:wishlist": "علاقه",
        "ux:links": "حساب", "ux:referral": "معرفی",
        "ux:notifications": "تبلیغات", "ux:stock:list": "اعلان موجودی",
        "ux:language": "فارسی", "ux:privacy": "حریم خصوصی",
        "shop:home": None,
    }
    page = await journey.ask(message="/account")
    direct = list(await journey.actions(page))
    assert direct == ["ux:profile", "ux:addresses", *ACCOUNT_GROUPS, "shop:home"], direct
    secondary = []
    for group in ACCOUNT_GROUPS:
        await journey.ask(message="/account")
        options = await journey.ask(group)
        secondary.extend(
            action for action in await journey.actions(options)
            if action not in {"ux:account", "shop:home"}
        )
    assert set(secondary) == set(expected) - {"ux:profile", "ux:addresses", "shop:home"}
    assert len(secondary) == len(set(secondary))
    for action, fragment in expected.items():
        reply = await account_action(journey, action)
        assert 1 <= len(reply["text"]) <= 4096
        assert all(len(value.encode("utf-8")) <= 64 for value in callbacks(reply))
        if fragment:
            assert fragment in reply["text"], (action, reply["text"])
        else:
            assert "ux:account" in await journey.actions(reply)


async def fund_credit(journey: Journey, amount: int, run: str) -> None:
    """Apply one synthetic credit concurrently and verify one ledger effect."""
    owner = await identity_for(journey)
    key = f"qa-account-credit:{run}:{journey.scope.platform.value}"

    async def apply() -> tuple[int, bool]:
        """Commit the real credit mutation in one competing PG transaction."""
        async with session_maker() as db:
            entry, changed = await ShopWalletService.apply(
                db, identity_id=owner["id"], delta_irr=amount,
                operation_key=key, reason="Isolated Beta QA credit",
                actor="isolated-beta-qa",
            )
            await db.commit()
            return entry.id, changed

    results = await asyncio.wait_for(
        asyncio.gather(*(apply() for _ in range(4))), timeout=45,
    )
    assert len({entry for entry, _ in results}) == 1
    assert sum(changed for _, changed in results) == 1
    async with session_maker() as db:
        assert await ShopWalletService.balance(
            db, journey.scope.platform, journey.user_id,
            bot_id=journey.scope.bot_id,
        ) == amount


async def link_history(fixture: dict, tg: Journey, bale: Journey,
                       outsider: Journey, foreign: Journey) -> int:
    """Require both providers and source approval before sharing old Orders."""
    stage("RUN   Two-sided identity linking and historical Order authorization")
    assert tg.user_id != bale.user_id
    first = await identity_for(tg)
    second = await identity_for(bale)
    assert first["customer_id"] != second["customer_id"]
    tg_order = (await tg.order(fixture, ("physical",)))[0]
    bale_order = (await bale.order(fixture, ("physical",)))[0]
    refused = await raw_denial(tg, f"ux:order:detail:{bale_order}", "qa-v1")
    assert "پیدا نشد" in refused["text"]
    await account_action(tg, "ux:links")
    challenge = await tg.ask("ux:links:start")
    token = re.search(r"/linkconfirm ([A-Za-z0-9_-]{43})", challenge["text"])
    assert token is not None, challenge["text"]
    token = token.group(1)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()

    async def proof(expected: str) -> str:
        """Inspect real hashed consent state without printing the bearer token."""
        async with session_maker() as db:
            row = await db.scalar(select(ShopCustomerLinkRequest).where(
                ShopCustomerLinkRequest.token_hash == digest,
            ))
            assert row is not None and row.state == expected
            assert row.source_id == first["id"] and row.token_hash != token
            return row.id

    await proof("pending")
    await foreign.ask(message=f"/linkconfirm {token}")
    await proof("pending")
    await tg.ask(message=f"/linkapprove {token}")
    await proof("pending")
    await bale.ask(message=f"/linkconfirm {token}")
    await proof("awaiting_confirmation")
    assert (await identity_for(bale))["customer_id"] == second["customer_id"]
    await bale.ask(message=f"/linkapprove {token}")
    await proof("awaiting_confirmation")
    await tg.ask(message=f"/linkapprove {token}")
    request_id = await proof("confirmed")
    assert (await identity_for(bale))["customer_id"] == first["customer_id"]
    async with session_maker() as db:
        assert await db.scalar(select(func.count()).select_from(
            ShopStoreCustomerLinkEvent,
        ).where(ShopStoreCustomerLinkEvent.request_id == request_id)) == 1
        old = await db.get(ShopOrder, bale_order)
        assert old.customer_id == second["customer_id"]
        assert old.bot_id == bale.scope.bot_id and old.platform_user_id == bale.user_id
    for journey in (tg, bale):
        history = await journey.ask(message="/orders")
        assert {f"ux:order:detail:{tg_order}", f"ux:order:detail:{bale_order}"} <= set(
            await journey.actions(history)
        )
        for order_id in (tg_order, bale_order):
            await journey.ask(message="/orders")
            details = await journey.ask(f"ux:order:detail:{order_id}")
            assert f"#{order_id}" in details["text"] and "qa-v1" in details["text"]
    for journey in (outsider, foreign):
        denied = await raw_denial(journey, f"ux:order:detail:{tg_order}", "qa-v1")
        assert "پیدا نشد" in denied["text"]
    await tg.ask(message=f"/linkapprove {token}")
    await proof("confirmed")
    async with session_maker() as db:
        assert await db.scalar(select(func.count()).select_from(
            ShopStoreCustomerLinkEvent,
        ).where(ShopStoreCustomerLinkEvent.request_id == request_id)) == 1
    stage("PASS  Linking: claim/source proof, foreign denial, old Orders visible, no rewrite/replay")
    return tg_order


async def admin_request(db, fixture: dict, store_id: str):
    """Build an admin handler request from real active Store memberships."""
    actor = await db.get(ShopStaff, fixture["admin_id"])
    assert actor is not None and actor.is_active
    request = Request({"type": "http", "method": "POST", "path": "/qa", "headers": []})
    request.state.store_context = StoreContext(
        staff_id=actor.id, session_id="isolated-beta-qa",
        allowed_stores=await memberships(db, staff_id=actor.id),
        active_store_ids=(store_id,), current_store_id=store_id,
        default_store_id=store_id, version=1,
    )
    return actor, request


async def credit_and_shipment(fixture: dict, tg: Journey, bale: Journey,
                              outsider: Journey, order_id: int) -> None:
    """Verify consent, locked debit, staff shipment and one internal refund."""
    stage("RUN   Store Credit payment/refund idempotency and shipment tracking")
    async with session_maker() as db:
        order = await db.get(ShopOrder, order_id)
        amount = order.total_irr
        product_id = order.product_id
        stock_before = (await db.get(Product, product_id)).stock_quantity
        assert order.status == "approved_unpaid" and order.terms_accepted_at
        assert await ShopWalletService.balance(
            db, tg.scope.platform, tg.user_id, bot_id=tg.scope.bot_id,
        ) == 5000
        assert await ShopWalletService.balance(
            db, bale.scope.platform, bale.user_id, bot_id=bale.scope.bot_id,
        ) == 3000
    await tg.ask(message="/orders")
    await tg.ask(f"shop:creditpay:{order_id}")
    confirmation = await tg.prepare(f"shop:creditconfirm:{order_id}")
    async with session_maker() as db:
        assert (await db.get(ShopOrder, order_id)).status == "approved_unpaid"
    # Even a verified linked account cannot initiate another Bot's payment.
    for other in (bale, outsider):
        assert (await other.tap(confirmation))["status"] == "stale_callback"
    async with session_maker() as db:
        assert (await db.get(ShopOrder, order_id)).status == "approved_unpaid"
    outcomes = await asyncio.wait_for(
        asyncio.gather(tg.tap(confirmation), tg.tap(confirmation)), timeout=45,
    )
    assert sorted(item["status"] for item in outcomes) == ["processed", "stale_callback"]
    assert (await tg.tap(confirmation))["status"] == "stale_callback"
    async with session_maker() as db:
        order = await db.get(ShopOrder, order_id)
        assert order.status == "paid" and order.provider == "store_credit"
        assert (await db.get(Product, product_id)).stock_quantity == stock_before - 1
        assert await db.scalar(select(func.count()).select_from(
            ShopWalletEntry,
        ).where(
            ShopWalletEntry.operation_key == f"store-credit-pay-order:{order_id}",
        )) == 1
        assert await db.scalar(select(func.count()).select_from(
            ShopPaymentAttempt,
        ).where(ShopPaymentAttempt.order_id == order_id)) == 1
        actor, request = await admin_request(db, fixture, fixture["stores"][0])
        ready = await admin_api.advance_fulfillment(
            order_id, admin_api.ShipmentStep(expected_version=1, next_status="ready"),
            request, actor, db,
        )
        assert ready["status"] == "ready" and ready["version"] == 2
    tracking = "QA-TRACK-" + uuid4().hex[:12]
    async with session_maker() as db:
        actor, request = await admin_request(db, fixture, fixture["stores"][0])
        shipped = await admin_api.advance_fulfillment(
            order_id,
            admin_api.ShipmentStep(
                expected_version=2, next_status="shipped",
                carrier="حمل‌کننده آزمایشی", tracking_code=tracking,
            ), request, actor, db,
        )
        assert shipped["status"] == "shipped" and shipped["version"] == 3
    for journey in (tg, bale):
        await journey.ask(message="/orders")
        await journey.ask(f"ux:order:detail:{order_id}")
        reply = await journey.ask(f"ux:order:track:{order_id}")
        assert tracking in reply["text"] and "shipped" in reply["text"]
    refused = await raw_denial(outsider, f"ux:order:track:{order_id}", tracking)
    assert tracking not in refused["text"]
    async with session_maker() as db:
        case = await ShopRefundService.request(
            db, platform=tg.scope.platform, payer_id=tg.user_id,
            bot_id=tg.scope.bot_id, order_id=order_id,
            reason="Isolated QA internal credit refund",
        )
        duplicate = await ShopRefundService.request(
            db, platform=tg.scope.platform, payer_id=tg.user_id,
            bot_id=tg.scope.bot_id, order_id=order_id,
            reason="Isolated QA repeated request",
        )
        assert duplicate.id == case.id
        case_id = case.id
        await ShopWalletService.refund_order(db, case_id=case_id, actor="isolated-beta-qa")
    async with session_maker() as db:
        try:
            await ShopWalletService.refund_order(
                db, case_id=case_id, actor="isolated-beta-qa",
            )
        except StoreCreditRejected:
            await db.rollback()
        else:
            raise AssertionError("A finalized Store Credit refund replayed")
        assert (await db.get(ShopRefundCase, case_id)).status == "confirmed"
        assert (await db.get(ShopOrder, order_id)).status == "refunded"
        assert (await db.get(Product, product_id)).stock_quantity == stock_before - 1
        entry = await db.scalar(select(ShopWalletEntry).where(
            ShopWalletEntry.operation_key == f"store-credit-refund-order:{order_id}",
        ))
        assert entry is not None and entry.delta_irr == amount
        assert await db.scalar(select(func.count()).select_from(
            ShopWalletEntry,
        ).where(
            ShopWalletEntry.operation_key == f"store-credit-refund-order:{order_id}",
        )) == 1
        for journey, expected in ((tg, 5000), (bale, 3000)):
            assert await ShopWalletService.balance(
                db, journey.scope.platform, journey.user_id,
                bot_id=journey.scope.bot_id,
            ) == expected
    assert not tg.native.invoices and not bale.native.invoices
    stage("PASS  Credit: one grant/debit/refund, origin-only payment, linked tracking, no auto-restock")


class UncertainTelegram(FakeTelegram):
    """Lose only selected users' responses after recording native sends."""

    def __init__(self, uncertain_users: set[int]) -> None:
        """Keep all successful and ambiguous native calls as evidence."""
        super().__init__()
        self.uncertain_users = uncertain_users

    async def send_message(self, **payload):
        """Model a send accepted by Telegram whose response was lost."""
        result = await super().send_message(**payload)
        if int(payload["chat_id"]) in self.uncertain_users:
            raise TimeoutError("Synthetic accepted notification response lost")
        return result


class UncertainBale(FakeBaleSession):
    """Lose selected native Bale sendMessage responses without using HTTP."""

    def __init__(self, uncertain_users: set[int]) -> None:
        """Keep the same official fake API envelope and message recorder."""
        super().__init__()
        self.uncertain_users = uncertain_users

    def post(self, url: str, *, json=None, data=None, **kwargs):
        """Record the native request before simulating an ambiguous timeout."""
        result = super().post(url, json=json, data=data, **kwargs)
        if (
            url.rsplit("/", 1)[-1] == "sendMessage"
            and int((json or {})["chat_id"]) in self.uncertain_users
        ):
            raise TimeoutError("Synthetic accepted notification response lost")
        return result


class NotificationHarness:
    """Drive the real notification worker with native per-Bot fake adapters."""

    def __init__(self, scopes: dict, uncertain_users: set[int]) -> None:
        """Bind fake transports to the fixture's exact server-owned Bot IDs."""
        self.scopes = {scopes[key].bot_id: scopes[key] for key in ("telegram", "bale")}
        self.providers = {
            scopes["telegram"].bot_id: UncertainTelegram(uncertain_users),
            scopes["bale"].bot_id: UncertainBale(uncertain_users),
        }

    @asynccontextmanager
    async def transport(self, bot_id: str):
        """Replace credential resolution only; retain native API serializers."""
        assert bot_id in self.scopes, "Worker attempted a non-fixture Bot"
        native = self.providers[bot_id]
        if isinstance(native, FakeTelegram):
            yield TelegramTransport(native, bot_id=bot_id)
        else:
            yield BaleTransport("qa-fake-token", native, bot_id=bot_id)

    async def once(self, bot_id: str) -> bool:
        """Use the worker's normal transport/session/dispatch boundaries."""
        async with notification_worker._transport_for_bot(bot_id) as transport:
            async with session_maker() as db:
                return await notification_worker.deliver_once(
                    db, bot_id=bot_id, transport=transport,
                )

    async def drain(self) -> None:
        """Race claims until only terminal or crashed processing rows remain."""
        with patch.object(notification_worker, "_transport_for_bot", self.transport):
            for _ in range(100):
                active = set(await notification_worker._active_bot_ids()) & set(self.scopes)
                if not active:
                    return
                await asyncio.wait_for(asyncio.gather(*(
                    self.once(bot_id) for bot_id in sorted(active) for _ in range(2)
                )), timeout=45)
        raise AssertionError("Bounded fixture notification drain did not converge")

    def sent(self, journey: Journey, body: str | None = None) -> int:
        """Count actual serialized native messages for one synthetic customer."""
        return sum(
            int(message["chat_id"]) == journey.user_id
            and (body is None or message["text"] == body)
            for message in self.providers[journey.scope.bot_id].messages
        )


async def enqueue(journey: Journey, *, topic: str, key: str, body: str) -> bool:
    """Commit real idempotent outbox creation without replacing domain code."""
    async with session_maker() as db:
        added = await enqueue_notification(
            db, context=journey.scope, user_id=journey.user_id,
            topic=topic, event_key=key, body=body,
        )
        await db.commit()
        return added


async def notification_journeys(fixture: dict, scopes: dict,
                                tg: Journey, bale: Journey,
                                base: int, run: str) -> NotificationHarness:
    """Verify stock cancellation, live consent, native claims and uncertainty."""
    stage("RUN   Stock subscriptions and concurrent native notification worker")
    async with session_maker() as db:
        template = await db.get(Product, fixture["products"]["physical"])
        product = Product(
            store_id=template.store_id, category_id=template.category_id,
            uom_id=template.uom_id, sku=f"QA-ALERT-{run}",
            name=f"اعلان آزمایشی {run}", description="موجودی آزمایشی",
            price=1000, stock_quantity=0, product_type="physical",
            requires_shipping=False, is_published=True,
        )
        db.add(product)
        await db.flush()
        product_id = product.id
        for provider in ("telegram", "bale"):
            db.add(ShopBotProductRule(
                bot_id=scopes[provider].bot_id, product_id=product_id,
                effect="allow", updated_by=fixture["admin_id"],
            ))
        await db.commit()
    cases = []
    for offset, original in enumerate((tg, bale)):
        for index, outcome in enumerate(("sent", "needs_review", "cancelled", "no_queue")):
            journey = original if index == 0 else Journey(
                original.scope, base + 100 + offset * 10 + index,
            )
            await journey.ask(message="/start")
            await journey.open_product(product_id)
            await journey.ask(f"ux:stock:toggle:{product_id}")
            listed = await account_action(journey, "ux:stock:list")
            assert f"ux:stock:toggle:{product_id}" in await journey.actions(listed)
            if outcome == "no_queue":
                await journey.ask(f"ux:stock:toggle:{product_id}")
            async with session_maker() as db:
                alert = await db.scalar(select(ShopStockAlert).where(
                    ShopStockAlert.bot_id == journey.scope.bot_id,
                    ShopStockAlert.platform_user_id == journey.user_id,
                    ShopStockAlert.product_id == product_id,
                ))
                assert alert is not None
                assert alert.status == ("cancelled" if outcome == "no_queue" else "active")
                cases.append((journey, outcome, alert.id))
    async with session_maker() as db:
        (await db.get(Product, product_id)).stock_quantity = 20
        await db.commit()

    async def prepare() -> int:
        """Let PostgreSQL SKIP LOCKED arbitrate simultaneous stock scanners."""
        async with session_maker() as db:
            return await prepare_stock_alerts(db, store_id=fixture["stores"][0])

    await asyncio.gather(prepare(), prepare())
    for journey, outcome, _ in cases:
        if outcome == "cancelled":
            await journey.ask(f"ux:stock:toggle:{product_id}")
    harness = NotificationHarness(scopes, {
        journey.user_id for journey, outcome, _ in cases if outcome == "needs_review"
    })
    await harness.drain()
    await harness.drain()
    async with session_maker() as db:
        for journey, outcome, alert_id in cases:
            row = await db.scalar(select(ShopCustomerNotificationOutbox).where(
                ShopCustomerNotificationOutbox.event_key == f"stock:{alert_id}",
            ))
            if outcome == "no_queue":
                assert row is None and harness.sent(journey) == 0
                continue
            assert row is not None and row.status == outcome, (alert_id, outcome)
            assert row.bot_id == journey.scope.bot_id
            assert harness.sent(journey) == (outcome != "cancelled")
            if outcome == "needs_review":
                assert row.failure_code == "provider_outcome_unknown"
            alert = await db.get(ShopStockAlert, alert_id)
            assert alert.status == {
                "sent": "notified", "needs_review": "queued", "cancelled": "cancelled",
            }[outcome]
    stage("PASS  Stock: explicit subscribe/cancel, real concurrent claims, native timeout quarantine/no replay")

    stage("RUN   Bot-scoped advertising consent and live revocation")
    for offset, journey in enumerate((tg, bale)):
        body = f"QA consent notice {run} {offset}"
        key = f"qa-marketing:{run}:{offset}"
        assert not (await identity_for(journey))["consent"]
        assert not await enqueue(journey, topic="marketing", key=key, body=body)
        await account_action(journey, "ux:notifications")
        await journey.ask("ux:notify:on")
        assert (await identity_for(journey))["consent"] is True
        if offset == 0:
            assert (await identity_for(bale))["consent"] is False
        inserted = await asyncio.gather(*(
            enqueue(journey, topic="marketing", key=key, body=body) for _ in range(2)
        ))
        assert sorted(inserted) == [False, True]
        await harness.drain()
        assert harness.sent(journey, body) == 1
        revoked_key = f"qa-marketing-revoked:{run}:{offset}"
        revoked_body = f"QA revoked consent {run} {offset}"
        assert await enqueue(journey, topic="marketing", key=revoked_key, body=revoked_body)
        await account_action(journey, "ux:notifications")
        await journey.ask("ux:notify:off")
        assert (await identity_for(journey))["consent"] is False
        assert not await enqueue(
            journey, topic="marketing", key=f"qa-after-revoke:{run}:{offset}", body=body,
        )
        await harness.drain()
        assert harness.sent(journey, revoked_body) == 0
        async with session_maker() as db:
            row = await db.scalar(select(ShopCustomerNotificationOutbox).where(
                ShopCustomerNotificationOutbox.event_key == revoked_key,
            ))
            assert row.status == "cancelled" and row.failure_code == "authorization_revoked"
            owner = await identity_for(journey)
            consent = (await db.scalars(select(ShopCustomerConsentEvent).where(
                ShopCustomerConsentEvent.identity_id == owner["id"],
            ).order_by(ShopCustomerConsentEvent.id))).all()
            assert [event.allowed for event in consent] == [True, False]
    # A process exit after the durable claim must not replay a provider send.
    for offset, journey in enumerate((tg, bale)):
        body = f"QA claimed before crash {run} {offset}"
        assert await enqueue(
            journey, topic="order", key=f"qa-crash:{run}:{offset}", body=body,
        )
        async with session_maker() as db:
            claimed = await claim_outbox_message(db, bot_id=journey.scope.bot_id)
            assert claimed is not None and claimed.body == body
            claimed_id = claimed.id
        await harness.drain()
        assert harness.sent(journey, body) == 0
        async with session_maker() as db:
            assert (await db.get(ShopCustomerNotificationOutbox, claimed_id)).status == "processing"
    stage("PASS  Consent: opt-in/out receipts, linked Bot isolation, revoke-before-send, crash has no replay")
    return harness


async def support_replies(fixture: dict, tg: Journey, bale: Journey,
                          outsider: Journey, harness: NotificationHarness,
                          run: str) -> None:
    """Execute real authorized staff reply plus atomic native outbox delivery."""
    stage("RUN   Customer support and authorized staff reply/outbox transaction")
    for journey in (tg, bale):
        await journey.ask(message="/support")
        await journey.ask("ux:ticket:new")
        await journey.ask("ux:ticket:topic:general")
        customer_body = f"درخواست پشتیبانی آزمایشی {run}"
        created = await journey.ask(message=customer_body)
        detail = next(
            action for action in await journey.actions(created) if action.startswith("ux:ticket:view:")
        )
        ticket_id = int(detail.rsplit(":", 1)[-1])
        answer_body = f"پاسخ کارکنان آزمایشی {run} {journey.scope.platform.value}"
        async with session_maker() as db:
            ticket = await db.get(ShopSupportTicket, ticket_id)
            actor, request = await admin_request(db, fixture, fixture["stores"][0])
            answer = await admin_api.reply_to_ticket(
                ticket_id,
                admin_api.StaffTicketReply(expected_version=ticket.version, body=answer_body),
                request, actor, db,
            )
            event_key = f"ticket_reply:{ticket_id}:{answer['version']}"
            row = await db.scalar(select(ShopCustomerNotificationOutbox).where(
                ShopCustomerNotificationOutbox.event_key == event_key,
            ))
            assert row is not None and row.status == "queued"
            notice = row.body
            assert await db.scalar(select(func.count()).select_from(
                ShopSupportMessage,
            ).where(
                ShopSupportMessage.ticket_id == ticket_id,
                ShopSupportMessage.sender_kind == "staff",
            )) == 1
        first_page = await journey.ask(detail)
        assert customer_body in first_page["text"]
        # Follow the provider's visible navigation rather than assuming that
        # all messages in a paginated thread appear on its opening page.
        next_action = await action_with_label(journey, first_page, "بعدی")
        next_tap = await journey.prepare(next_action, first_page)
        staff_page = await journey.ask(next_action)
        assert answer_body in staff_page["text"]
        previous_action = await action_with_label(journey, staff_page, "قبلی")
        assert customer_body in (await journey.ask(previous_action))["text"]
        await raw_denial(outsider, detail, answer_body, customer_body)
        before = len(outsider.native.messages)
        assert (await outsider.tap(next_tap))["status"] == "stale_callback"
        assert all(
            answer_body not in reply["text"] and customer_body not in reply["text"]
            for reply in outsider.native.messages[before:]
        )
        await harness.drain()
        await harness.drain()
        assert harness.sent(journey, notice) == 1
    stage("PASS  Support: paginated staff reply, next/previous, foreign denial, atomic outbox, one native notice")


async def action_with_label(journey: Journey, reply: dict, label: str) -> str:
    """Find the logical action only if the actual provider rendered its label."""
    payloads = {
        button["callback_data"]
        for row in reply["reply_markup"]["inline_keyboard"]
        for button in row
        if button.get("text") == label
    }
    actions = [
        action for action, tap in (await journey.actions(reply)).items()
        if tap.data in payloads
    ]
    assert len(actions) == 1, (label, actions)
    return actions[0]


async def main() -> None:
    """Reuse the exact synthetic fixture without changing external settings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh-fixture", action="store_true")
    args = parser.parse_args()
    try:
        fixture = (
            await seed(persist_manifest=False)
            if args.fresh_fixture else json.loads(MANIFEST.read_text(encoding="utf-8"))
        )
        await postgres_guard(fixture)
        scopes = {key: await context(fixture, key) for key in (
            "telegram", "telegram_second", "bale", "foreign",
        )}
        run = uuid4().hex[:12]
        base = 1_000_000_000 + uuid4().int % 100_000_000
        await enrollment_races(scopes, base, run)
        tg = Journey(scopes["telegram"], base + 40)
        bale = Journey(scopes["bale"], base + 41)
        outsider = Journey(scopes["telegram"], base + 42)
        foreign = Journey(scopes["foreign"], base + 43)
        for journey in (tg, bale, outsider, foreign):
            await journey.ask(message="/start")
        stage("RUN   Direct and grouped Account actions on Telegram and Bale")
        await account_menu(tg)
        await account_menu(bale)
        stage("PASS  Account: every menu callback routes through native provider output")
        stage("RUN   Concurrent Store Credit grants on independently linked identities")
        await fund_credit(tg, 5000, run)
        await fund_credit(bale, 3000, run)
        stage("PASS  Credit grants: each four-session race wrote one ledger entry")
        order_id = await link_history(fixture, tg, bale, outsider, foreign)
        await credit_and_shipment(fixture, tg, bale, outsider, order_id)
        harness = await notification_journeys(fixture, scopes, tg, bale, base, run)
        await support_replies(fixture, tg, bale, outsider, harness, run)
        stage("PASS  Account/notifications PostgreSQL integration complete; all providers were native fakes")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
