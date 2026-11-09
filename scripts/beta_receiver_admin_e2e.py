"""Verify real PostgreSQL receivers and the running isolated administration API.

Run inside the named Beta QA API container with ``python -m
scripts.beta_receiver_admin_e2e``. The existing storefront manifest is required.
All provider operations terminate in in-memory fakes installed before the
receiver flag is enabled in this process. No production lifespan is imported,
no provider activation endpoint is called, and no fixture rows are deleted.

Administration requests go over HTTP to the existing loopback QA API. Their
temporary normal session is always revoked. Request bodies, encoded queries,
and the session proof are signed exactly as on the production bridge.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import secrets
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from scripts.test_lab_safety import require_isolated_lab

require_isolated_lab()
if os.environ.get("SHOP_BETA_QA") != "1" or not __debug__:
    raise RuntimeError("Beta receiver QA requires guarded mode and assertions.")
for flag in (
    "MULTIBOT_V2_RUNTIME_ENABLED",
    "SHOP_RELAY_POOL_ENABLED",
    "SHOP_BROADCAST_REGISTRY_ENABLED",
    "SHOP_CUSTOMER_NOTIFICATIONS_ENABLED",
):
    if os.environ.get(flag, "false") != "false":
        raise RuntimeError("All deployed receiver/provider flags must stay off.")

import httpx  # noqa: E402
from aiogram.types import Update  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

import config  # noqa: E402
from channels.bale import BaleTransport  # noqa: E402
from dashboard.multibot_webhook import router as webhook_router  # noqa: E402
from db import engine, session_maker  # noqa: E402
from models.shop_content import Product, ShopIdentity  # noqa: E402
from models.shop_delivery import ShopInboundUpdate  # noqa: E402
from models.shop_multibot import ShopBot, ShopBotCredential  # noqa: E402
from models.shop_multibot_receiver import ShopBotReceiver  # noqa: E402
from models.shop_store_commerce import ShopBotCommercePolicy  # noqa: E402
from scripts.beta_storefront_e2e import (  # noqa: E402
    MANIFEST,
    FakeBaleResponse,
    FakeBaleSession,
    FakeTelegram,
    context,
    inbound,
)
from scripts.codespace_dashboard_probe import (  # noqa: E402
    assert_isolated_codespace,
    diagnostic_identity,
    revoke_diagnostic_session,
)
from services import shop_bot_secrets as vault  # noqa: E402
from services import shop_multibot_supervisor as runtime  # noqa: E402

API_PREFIX = "/internal/admin/v1"
API_BASE = "http://127.0.0.1:5000"


def expect_status(response: httpx.Response, code: int, label: str) -> None:
    """Assert an HTTP contract without printing response data or credentials."""
    assert response.status_code == code, (
        f"{label}: expected HTTP {code}, received HTTP {response.status_code}"
    )


def update_payload(user_id: int, update_id: int) -> dict:
    """Reuse storefront input with the fields required by aiogram polling."""
    payload = {"update_id": update_id, **inbound(user_id)}
    payload["message"]["date"] = int(time.time())
    payload["message"]["from"]["is_bot"] = False
    return payload


@dataclass
class PollPlan:
    """Stop on an observed committed offset, without timer-based coordination."""

    payload: dict
    stop_event: asyncio.Event
    offsets: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def fetch(self, offset: int) -> list[dict]:
        """Return one update, then stop when its durable next offset is used."""
        self.offsets.append(offset)
        if offset == self.payload["update_id"] + 1:
            self.stop_event.set()
        elif offset != 0 or len(self.offsets) != 1:
            self.errors.append("Polling did not advance the committed offset")
            self.stop_event.set()
        # A nonempty terminal batch makes the real poller observe stop_event
        # before processing, without entering its idle/retry sleep branches.
        return [self.payload]


class ReceiverTelegram(FakeTelegram):
    """Extend the shared fake with the exact native polling API boundary."""

    def __init__(self, token: str) -> None:
        """Bind a synthetic token without constructing an aiogram Bot client."""
        super().__init__()
        self.token = token
        self.plan: PollPlan | None = None

    async def get_webhook_info(self):
        """Report an empty webhook without contacting Telegram."""
        return SimpleNamespace(url="")

    async def get_updates(self, *, offset: int, **_kwargs):
        """Return actual aiogram Update values to the real supervisor parser."""
        assert self.plan is not None, "Unexpected Telegram polling request"
        return [Update.model_validate(item) for item in self.plan.fetch(offset)]


class ReceiverBale(FakeBaleSession):
    """Extend the shared fake while retaining BaleTransport envelope parsing."""

    def __init__(self) -> None:
        """Initialize a provider-free session and an optional polling plan."""
        super().__init__()
        self.plan: PollPlan | None = None

    def post(self, url: str, *, json=None, data=None, **kwargs):
        """Intercept polling before the native adapter can create network I/O."""
        method = url.rsplit("/", 1)[-1]
        if method == "getWebhookInfo":
            return FakeBaleResponse({"url": ""})
        if method == "getUpdates":
            assert self.plan is not None, "Unexpected Bale polling request"
            return FakeBaleResponse(self.plan.fetch(json["offset"]))
        return super().post(url, json=json, data=data, **kwargs)


@dataclass(repr=False)
class ReceiverFixture:
    """Keep synthetic receiver credentials private and scoped to one bot."""

    bot_id: str
    store_id: str
    platform: str
    mode: str
    binding_id: str
    secret: str
    token: str
    native: ReceiverTelegram | ReceiverBale

    @property
    def route(self) -> str:
        """Construct the in-process route; never include it in diagnostics."""
        return f"/webhooks/v2/{self.binding_id}/{self.secret}"


async def receiver_fixtures(fixture: dict) -> list[ReceiverFixture]:
    """Add synthetic bots and encrypted secrets only to existing QA Stores."""
    cases = []
    async with session_maker() as db:
        assert await db.scalar(text("SELECT current_database()")) == "shop_codespace"
        assert await db.scalar(text("SELECT current_user")) == "shop_codespace"
        occupied = await db.scalar(select(func.count()).select_from(
            ShopBotReceiver,
        ).where(ShopBotReceiver.state.in_(("active", "applying"))))
        assert occupied == 0, "Refusing to start alongside an existing receiver"
        for index, (platform, mode) in enumerate((
            ("telegram", "webhook"), ("bale", "webhook"),
            ("telegram", "polling"), ("bale", "polling"),
        )):
            bot_id = str(uuid4())
            provider_id = 9_000_000_000_000 + uuid4().int % 1_000_000_000
            token = f"{provider_id}:{uuid4().hex}{uuid4().hex}"
            secret = secrets.token_urlsafe(32)
            case = ReceiverFixture(
                bot_id, fixture["stores"][index % 2], platform, mode,
                str(uuid4()), secret, token,
                ReceiverTelegram(token) if platform == "telegram" else ReceiverBale(),
            )
            cases.append(case)
            db.add(ShopBot(
                id=bot_id, store_id=case.store_id,
                slug="qa-receiver-" + uuid4().hex[:16], name="QA receiver",
                platform=platform, provider_bot_id=provider_id,
                status="active", runtime_owner="registry", credential_version=1,
            ))
        await db.flush()
        for case in cases:
            db.add(ShopBotCredential(
                id=str(uuid4()), bot_id=case.bot_id, version=1,
                source="encrypted", state="active",
                ciphertext=vault.encrypt_for_bot(
                    case.bot_id, case.platform, case.token,
                ),
                token_fingerprint=vault.fingerprint_token(case.platform, case.token),
                created_by=fixture["admin_id"],
            ))
            db.add(ShopBotCommercePolicy(
                bot_id=case.bot_id, cart_enabled=True, credit_enabled=False,
            ))
            db.add(ShopBotReceiver(
                bot_id=case.bot_id, binding_id=case.binding_id, mode=case.mode,
                state="active" if case.mode == "webhook" else "staged",
                webhook_secret_ciphertext=vault.encrypt_receiver_secret(
                    case.bot_id, case.secret,
                ),
                webhook_secret_digest=hashlib.sha256(case.secret.encode()).hexdigest(),
                credential_version=1, updated_by=fixture["admin_id"],
            ))
        await db.commit()
    return cases


async def rotate_fake_token(case: ReceiverFixture, actor_id: int) -> None:
    """Rotate only a newly created fake credential and retain the old receipt."""
    token = case.token.split(":", 1)[0] + ":" + uuid4().hex + uuid4().hex
    async with session_maker() as db:
        bot = await db.get(ShopBot, case.bot_id, with_for_update=True)
        receiver = await db.get(ShopBotReceiver, case.bot_id, with_for_update=True)
        old = await db.scalar(select(ShopBotCredential).where(
            ShopBotCredential.bot_id == case.bot_id,
            ShopBotCredential.version == 1,
        ).with_for_update())
        assert bot is not None and receiver is not None and old is not None
        old.state = "revoked"
        old.revoked_at = datetime.now(timezone.utc)
        await db.flush()  # Release the one-active-version unique index first.
        db.add(ShopBotCredential(
            id=str(uuid4()), bot_id=case.bot_id, version=2,
            source="encrypted", state="active", created_by=actor_id,
            ciphertext=vault.encrypt_for_bot(case.bot_id, case.platform, token),
            token_fingerprint=vault.fingerprint_token(case.platform, token),
        ))
        bot.credential_version = receiver.credential_version = 2
        await db.commit()
    case.token = token
    case.native.token = token


async def receiver_checks(fixture: dict) -> None:
    """Exercise actual webhook/polling paths, PostgreSQL lease and receipts."""
    assert config.MULTIBOT_V2_RUNTIME_ENABLED is False
    await context(fixture, "telegram")  # Validate the existing trusted fixture.
    cases = await receiver_fixtures(fixture)
    by_id = {case.bot_id: case for case in cases}
    actor_base = 9_100_000_000 + uuid4().int % 1_000_000_000
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(webhook_router)
    supervisor = runtime.MultiBotSupervisor(app)

    @asynccontextmanager
    async def fake_provider(platform: str, token: str, *, bot_id=None):
        """Fail closed for every bot outside this runner's synthetic allowlist."""
        assert bot_id in by_id, "Refusing provider access for a non-fixture bot"
        case = by_id[bot_id]
        assert case.platform == platform and hmac.compare_digest(
            token, case.token,
        ), "Fake provider credential mismatch"
        yield case.native if platform == "telegram" else BaleTransport(
            token, case.native, bot_id=bot_id,
        )

    # Install the network-free factory BEFORE changing the process-local flag.
    # The running QA server and its deployed false flag are never modified.
    with patch.object(runtime, "provider_client", fake_provider):
        with patch.object(config, "MULTIBOT_V2_RUNTIME_ENABLED", True):
            try:
                await supervisor.start()
                assert supervisor.owns_lease and supervisor.lease_pid is not None
                rival = runtime.MultiBotSupervisor(FastAPI())
                try:
                    try:
                        await rival.start()
                    except RuntimeError as error:
                        assert str(error) == (
                            "Another service owns the shared multi-bot receiver lease"
                        ), "Unexpected competing receiver failure"
                    else:
                        raise AssertionError(
                            "Two receivers acquired the same PostgreSQL lease"
                        )
                finally:
                    await rival.close()
                print("PASS  PostgreSQL advisory lease rejects a second receiver owner")

                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://receiver.invalid", trust_env=False,
                    timeout=15, follow_redirects=False,
                ) as client:
                    telegram, bale = cases[:2]
                    payload = update_payload(actor_base + 1, 101)
                    forbidden = (
                        (telegram.route, {}),
                        (
                            telegram.route,
                            {"X-Telegram-Bot-Api-Secret-Token": bale.secret},
                        ),
                        (f"/webhooks/v2/{telegram.binding_id}/{bale.secret}", {}),
                        (f"/webhooks/v2/{bale.binding_id}/{telegram.secret}", {}),
                        (f"/webhooks/v2/{telegram.binding_id}/{'x' * 43}", {}),
                    )
                    for route, headers in forbidden:
                        response = await client.post(
                            route, headers=headers, json=payload,
                        )
                        expect_status(response, 404, "Webhook authenticator denial")
                    assert all(not case.native.messages for case in cases)
                    async with session_maker() as db:
                        count = await db.scalar(select(func.count()).select_from(
                            ShopInboundUpdate,
                        ).where(ShopInboundUpdate.bot_id.in_(by_id)))
                        assert count == 0, "Rejected webhook created a receipt"
                    print(
                        "PASS  Bogus secrets, missing Telegram header "
                        "and cross-bot bindings denied"
                    )

                    for index, case in enumerate(cases[:2]):
                        actor = actor_base + 10 + index
                        payload = update_payload(actor, 201)
                        # Client-selected bot/store fields must not select the
                        # other receiver or widen the authenticated route scope.
                        other = cases[1 - index]
                        payload.update(bot_id=other.bot_id, store_id=other.store_id)
                        headers = {"X-Telegram-Bot-Api-Secret-Token": case.secret}
                        responses = await asyncio.gather(*(
                            client.post(case.route, headers=headers, json=payload)
                            for _ in range(4)
                        ))
                        for response in responses:
                            expect_status(response, 200, "Concurrent webhook receipt")
                        statuses = [response.json()["status"] for response in responses]
                        assert statuses.count("processed") == 1, (
                            "Update did not process exactly once"
                        )
                        assert statuses.count("duplicate") == 3, (
                            "Concurrent duplicate escaped receipt fencing"
                        )
                        assert len(case.native.messages) == 1, (
                            "Duplicate webhook sent more than one message"
                        )
                        async with session_maker() as db:
                            receipts = (await db.scalars(select(ShopInboundUpdate).where(
                                ShopInboundUpdate.bot_id == case.bot_id,
                                ShopInboundUpdate.update_id == 201,
                            ))).all()
                            assert len(receipts) == 1
                            assert receipts[0].status == "processed"
                            original_fingerprint = receipts[0].bot_fingerprint
                            owners = (await db.scalars(select(ShopIdentity.bot_id).where(
                                ShopIdentity.platform_user_id == actor,
                            ))).all()
                            assert owners == [case.bot_id], (
                                "Payload selected an unrelated bot identity"
                            )
                        await rotate_fake_token(case, fixture["admin_id"])
                        replay = await client.post(
                            case.route, headers=headers, json=payload,
                        )
                        expect_status(replay, 200, "Replay after fake token rotation")
                        assert replay.json() == {
                            "status": "duplicate", "receipt_state": "processed",
                        }
                        assert len(case.native.messages) == 1, (
                            "Token rotation replayed a prior update"
                        )
                        fresh_payload = update_payload(actor, 202)
                        fresh_payload["message"]["text"] = "/catalog"
                        fresh = await client.post(case.route, headers=headers, json=fresh_payload)
                        expect_status(
                            fresh, 200, "Fresh update after fake token rotation",
                        )
                        assert fresh.json()["status"] == "processed"
                        assert len(case.native.messages) == 2
                        async with session_maker() as db:
                            receipt = await db.scalar(select(ShopInboundUpdate).where(
                                ShopInboundUpdate.bot_id == case.bot_id,
                                ShopInboundUpdate.update_id == 201,
                            ))
                            assert receipt is not None
                            assert receipt.bot_fingerprint == original_fingerprint
                            latest = await db.scalar(select(ShopInboundUpdate).where(
                                ShopInboundUpdate.bot_id == case.bot_id,
                                ShopInboundUpdate.update_id == 202,
                            ))
                            assert latest is not None and latest.status == "processed"
                            assert latest.bot_fingerprint != original_fingerprint
                        print(
                            f"PASS  {case.platform}: concurrent webhook sends "
                            "once; rotation preserves receipt"
                        )

                for index, case in enumerate(cases[2:]):
                    async with session_maker() as db:
                        row = await db.get(ShopBotReceiver, case.bot_id)
                        assert row is not None
                        row.state = "active"
                        await db.commit()
                    payload = update_payload(actor_base + 20 + index, 301)
                    for expected_offsets in ([0, 302], [302]):
                        supervisor.stop_event.clear()
                        plan = PollPlan(payload, supervisor.stop_event)
                        case.native.plan = plan
                        await asyncio.wait_for(
                            supervisor._poll(case.bot_id), timeout=15,
                        )
                        async with session_maker() as db:
                            row = await db.get(ShopBotReceiver, case.bot_id)
                            receipt = await db.scalar(select(ShopInboundUpdate).where(
                                ShopInboundUpdate.bot_id == case.bot_id,
                                ShopInboundUpdate.update_id == 301,
                            ))
                            offset = row.next_update_id if row else None
                            receipt_state = receipt.status if receipt else "missing"
                        evidence = (
                            f"platform={case.platform}, "
                            f"phase={'initial' if expected_offsets[0] == 0 else 'resume'}, "
                            f"sends={len(case.native.messages)}, "
                            f"provider_offsets={plan.offsets}, "
                            f"durable_offset={offset}, receipt={receipt_state}"
                        )
                        assert not plan.errors, (
                            "; ".join(plan.errors) + "; " + evidence
                        )
                        assert plan.offsets == expected_offsets, (
                            "Polling restart ignored durable offset; " + evidence
                        )
                        assert len(case.native.messages) == 1, (
                            "Polling expected exactly one native send; " + evidence
                        )
                        assert offset == 302, (
                            "Polling did not persist the next offset; " + evidence
                        )
                        assert receipt_state == "processed", (
                            "Polling receipt is not processed; " + evidence
                        )
                    print(
                        f"PASS  {case.platform}: actual polling persists "
                        "offset and resumes without replay"
                    )
            finally:
                # Retain all additive evidence while making synthetic receivers
                # inert before a future supervisor can inspect this QA database.
                try:
                    async with session_maker() as db:
                        rows = (await db.scalars(select(ShopBotReceiver).where(
                            ShopBotReceiver.bot_id.in_(by_id),
                        ))).all()
                        for row in rows:
                            row.state = "paused"
                        await db.commit()
                finally:
                    await supervisor.close()
    assert config.MULTIBOT_V2_RUNTIME_ENABLED is False
    assert not supervisor.owns_lease and supervisor.lease is None
    print(
        "PASS  Receiver lease closed; process flag restored; "
        "synthetic receivers paused"
    )


class SignedAdmin:
    """Issue exact signed loopback requests without exposing transient secrets."""

    def __init__(self, client: httpx.AsyncClient, identity: tuple) -> None:
        """Retain one revocable diagnostic session for this bounded test run."""
        self.client = client
        self.staff_id, self.version, self.token, self.session_id = identity

    def request(
        self, method: str, path: str, *, payload=None, params=None,
        token: str | None = None,
    ) -> httpx.Request:
        """Sign the actual UTF-8 body and httpx-encoded path plus query bytes."""
        body = b"" if payload is None else json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        request = self.client.build_request(
            method, API_PREFIX + path, content=body, params=params,
            headers={"content-type": "application/json"},
        )
        stamp = str(int(time.time()))
        canonical = "\n".join((
            stamp, method.upper(), request.url.raw_path.decode("ascii"),
            hashlib.sha256(body).hexdigest(), str(self.staff_id), str(self.version),
        ))
        signature = hmac.new(
            config.NEXT_ADMIN_BRIDGE_SECRET.encode(),
            canonical.encode(), hashlib.sha256,
        ).hexdigest()
        bearer = self.token if token is None else token
        request.headers.update({
            "x-shop-time": stamp, "x-shop-signature": signature,
            "x-shop-staff": str(self.staff_id), "x-shop-version": str(self.version),
            "x-shop-session": bearer,
            "x-shop-session-proof": self.proof(bearer, signature),
        })
        return request

    @staticmethod
    def proof(token: str, signature: str) -> str:
        """Bind a session bearer to the specific canonical bridge signature."""
        return hmac.new(
            config.NEXT_ADMIN_BRIDGE_SECRET.encode(),
            ("session-v1\n" + signature + "\n" + token).encode(), hashlib.sha256,
        ).hexdigest()

    async def call(
        self, method: str, path: str, *, payload=None, params=None,
        expected: int = 200,
    ):
        """Assert a real API response before returning its JSON data."""
        response = await self.client.send(self.request(
            method, path, payload=payload, params=params,
        ))
        expect_status(response, expected, f"Signed {method} {path}")
        return response.json()

    async def select(self, store_id: str, active: list[str]) -> dict:
        """Switch only this diagnostic session through the normal HTTP route."""
        current = await self.call("GET", "/store-context")
        selected = await self.call("POST", "/store-context/select", payload={
            "expected_version": current["version"], "current_store_id": store_id,
            "active_store_ids": active,
        })
        assert selected["current_store_id"] == store_id
        assert set(selected["active_store_ids"]) == set(active)
        return selected


async def create_admin_catalog(api: SignedAdmin, store_id: str, tag: str) -> dict:
    """Create/read/update synthetic catalog rows; retain them unpublished."""
    await api.select(store_id, [store_id])
    category = await api.call("POST", "/categories", expected=201, payload={
        "name": f"دسته آزمایشی {tag}", "is_published": False,
    })
    category_id = category["id"]
    await api.call("PATCH", f"/categories/{category_id}", payload={
        "name": f"دسته ویرایش شده {tag}", "is_published": True,
    })
    categories = await api.call("GET", "/categories")
    saved = next(item for item in categories if item["id"] == category_id)
    assert saved["store_id"] == store_id and saved["is_published"] is True
    sku = "QARX-" + tag
    created = await api.call("POST", "/products", expected=201, payload={
        "sku": sku, "name": f"محصول آزمایشی {tag}", "category_id": category_id,
        "description": "داده ساختگی برای کنترل محدوده فروشگاه",
        "price_irr": 12000, "stock_quantity": 2, "is_published": False,
    })
    product_id = created["id"]
    await api.call("PATCH", f"/products/{product_id}", payload={
        "name": f"محصول ویرایش شده {tag}", "price_irr": 14000,
    })
    product = await api.call("GET", f"/products/{product_id}")
    assert product["store_id"] == store_id and product["category_id"] == category_id
    assert product["price_irr"] == "14000" and product["sku"] == sku
    page = await api.call("GET", "/products", params={"search": sku, "page": 1})
    assert page["total"] == 1 and page["items"][0]["id"] == product_id
    # Deletion is intentionally unsupported. Exercise its denial without
    # removing any synthetic or historical QA row.
    await api.call("DELETE", f"/products/{product_id}", expected=405)
    await api.call("DELETE", f"/categories/{category_id}", expected=405)
    await api.call(
        "PATCH", f"/categories/{category_id}",
        payload={"is_published": False},
    )
    return {
        "product": product_id, "category": category_id,
        "sku": sku, "store": store_id,
    }


async def admin_checks(fixture: dict) -> None:
    """Verify session, catalog Store boundaries and HMAC over the real HTTP API."""
    assert_isolated_codespace()
    async with httpx.AsyncClient(
        base_url=API_BASE, timeout=15, trust_env=False, follow_redirects=False,
    ) as client:
        identity = await diagnostic_identity()
        api = SignedAdmin(client, identity)
        try:
            assert api.staff_id == fixture["admin_id"], (
                "Diagnostic admin differs from fixture owner"
            )
            scope = await api.call("GET", "/store-context")
            assert set(fixture["stores"]) <= set(scope["allowed_store_ids"])
            tag = uuid4().hex[:12]
            first, second = fixture["stores"]
            a = await create_admin_catalog(api, first, tag + "-A")
            await api.call(
                "GET", f"/products/{fixture['foreign_product']}", expected=404,
            )
            b = await create_admin_catalog(api, second, tag + "-B")
            await api.call("GET", f"/products/{a['product']}", expected=404)
            await api.call("PATCH", f"/products/{a['product']}", expected=404,
                           payload={"price_irr": 1})
            await api.call("PATCH", f"/categories/{a['category']}", expected=404,
                           payload={"name": "Cross-Store mutation must fail"})
            hidden = await api.call("GET", "/products", params={"search": a["sku"]})
            assert hidden["total"] == 0 and hidden["items"] == []
            categories = await api.call("GET", "/categories")
            assert a["category"] not in {item["id"] for item in categories}
            model = await api.call("POST", "/data-models/products/search", payload={
                "filters": [{"field": "id", "op": "eq", "value": a["product"]}],
            })
            assert model["total"] == 0 and model["items"] == []
            await api.select(first, [first])
            await api.call("GET", f"/products/{b['product']}", expected=404)
            await api.call(
                "PATCH", f"/products/{b['product']}", expected=404,
                payload={"price_irr": 1},
            )
            await api.call(
                "PATCH", f"/categories/{b['category']}", expected=404,
                payload={"name": "Cross-Store mutation must fail"},
            )
            print(
                "PASS  Real HTTP: Store A/B catalog creation, reads, "
                "updates and cross-Store denial"
            )

            for path in ("/customer-retention", "/referral-policy"):
                denied = await api.call("GET", path, expected=409)
                assert denied == {"detail": "store_scope_not_supported"}
            for path in ("/admin", "/admin/shop-products/list"):
                denied = await client.get(path)
                expect_status(denied, 404, "Legacy raw administration route")
                assert denied.json() == {
                    "detail": "Use the Next.js administration panel",
                }
                assert a["sku"] not in denied.text and b["sku"] not in denied.text
            print(
                "PASS  Unsupported global/legacy routes fail closed "
                "without catalog data"
            )

            await api.select(first, [first, second])
            page = await api.call("GET", "/products", params={"search": "QARX-" + tag})
            assert page["total"] == 2
            assert {item["id"] for item in page["items"]} == {
                a["product"], b["product"],
            }
            assert {item["store_id"] for item in page["items"]} == {first, second}
            await api.call("GET", f"/products/{b['product']}")
            await api.call("PATCH", f"/products/{b['product']}", expected=409,
                           payload={"price_irr": 1})
            await api.call("PATCH", f"/categories/{b['category']}", expected=409,
                           payload={"name": "Selected Store is not the write owner"})
            await api.call(
                "PATCH", f"/products/{a['product']}",
                payload={"price_irr": 15000},
            )
            extra = await api.call("POST", "/products", expected=201, payload={
                "sku": "QARX-" + tag + "-MULTI", "name": "محصول انتخاب چند فروشگاه",
                "price_irr": 16000,
            })
            current_owned = await api.call("GET", f"/products/{extra['id']}")
            assert current_owned["store_id"] == first
            unchanged = await api.call("GET", f"/products/{b['product']}")
            assert unchanged["price_irr"] == "14000"
            aggregate = await api.call("GET", "/overview")
            async with session_maker() as db:
                actual_count = await db.scalar(
                    select(func.count()).select_from(Product).where(
                        Product.store_id.in_((first, second)),
                    )
                )
            assert aggregate["products"] == actual_count
            model = await api.call("POST", "/data-models/products/search", payload={
                "filters": [{"field": "sku", "op": "starts", "value": "QARX-" + tag}],
            })
            assert model["total"] == 3
            assert {item["id"] for item in model["items"]} == {
                a["product"], b["product"], extra["id"],
            }
            print(
                "PASS  Multiple Stores aggregate reads; mutations use "
                "only the current Store"
            )

            invalid = api.request("GET", "/store-context", token="Z" * 43)
            expect_status(
                await client.send(invalid), 401, "Unknown session with valid proof",
            )
            invalid = api.request("GET", "/store-context")
            invalid.headers["x-shop-session-proof"] = "0" * 64
            expect_status(await client.send(invalid), 401, "Invalid session proof")
            invalid = api.request("GET", "/store-context")
            invalid.headers["x-shop-signature"] = "0" * 64
            invalid.headers["x-shop-session-proof"] = api.proof(api.token, "0" * 64)
            expect_status(
                await client.send(invalid), 401,
                "Invalid HMAC with valid session proof",
            )
            original = api.request("GET", "/products", params={"search": a["sku"]})
            altered = client.build_request(
                "GET", API_PREFIX + "/products", params={"search": b["sku"]},
                headers=original.headers,
            )
            expect_status(
                await client.send(altered), 401, "Query tampering after signing",
            )
            original = api.request("PATCH", f"/products/{a['product']}",
                                   payload={"price_irr": 17000})
            altered = client.build_request(
                "PATCH", API_PREFIX + f"/products/{a['product']}",
                content=b'{"price_irr":18000}', headers=original.headers,
            )
            expect_status(
                await client.send(altered), 401, "Body tampering after signing",
            )
            saved = await api.call("GET", f"/products/{a['product']}")
            assert saved["price_irr"] == "15000", "Rejected request mutated a product"
            print(
                "PASS  Invalid sessions, proof, HMAC, query "
                "and body tampering denied"
            )
        finally:
            await revoke_diagnostic_session(api.staff_id, api.session_id)
        expect_status(
            await client.send(api.request("GET", "/store-context")), 401,
            "Revoked diagnostic session",
        )
        print("PASS  Normal diagnostic session revoked and rejected by running API")


async def main() -> int:
    """Run bounded selected scenarios and close every database pool on exit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("receiver", "admin", "all"), default="all")
    args = parser.parse_args()
    try:
        assert MANIFEST.is_file(), "Run the existing Beta storefront seed first"
        fixture = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert len(fixture["stores"]) == 2 and fixture["admin_id"] > 0
        if args.stage in {"receiver", "all"}:
            await receiver_checks(fixture)
        if args.stage in {"admin", "all"}:
            await admin_checks(fixture)
        print("PASS  All requested receiver/admin Beta QA assertions completed")
        return 0
    except AssertionError as error:
        # Every explicit assertion above contains only safe static labels,
        # numeric statuses or receipt counts. Never print a provider exception.
        print(f"FAIL  Receiver/admin assertion: {error}")
        return 1
    except Exception as error:
        print(f"FAIL  Receiver/admin QA ({type(error).__name__}); secrets omitted")
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
