"""Verify real PostgreSQL Action atomicity, races, proofs and signed inspection.

Run only inside compose.action-qa.yml after the guarded Beta seed. The runner
creates additive synthetic identities and receipts; it never starts a real
provider, captures payments or installs Workflow Runtime routing.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from scripts.test_lab_safety import require_isolated_lab

require_isolated_lab()
if os.environ.get("SHOP_ACTION_QA") != "1" or not __debug__:
    raise RuntimeError("Use the isolated Action QA stack with assertions enabled.")

import httpx  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from db import engine, session_maker  # noqa: E402
from channels.contracts import Platform  # noqa: E402
from models.shop_action import (
    ShopActionAuthorization,
    ShopActionExecution,
)  # noqa: E402
from models.shop_checkout import ShopCart, ShopCartItem  # noqa: E402
from models.shop_content import ShopIdentity, ShopOrder  # noqa: E402
from models.shop_customer_support import (
    ShopSupportMessage,
    ShopSupportTicket,
)  # noqa: E402
from models.shop_store_commerce import ShopStoreCustomer  # noqa: E402
from scripts.beta_storefront_e2e import MANIFEST  # noqa: E402
from scripts.beta_receiver_admin_e2e import SignedAdmin  # noqa: E402
from scripts.codespace_dashboard_probe import (
    diagnostic_identity,
    revoke_diagnostic_session,
)  # noqa: E402
from services.shop_actions.approvals import issue_authorization  # noqa: E402
from services.shop_actions.catalog import actions  # noqa: E402
from services.shop_actions.context import customer_principal  # noqa: E402
from services.shop_actions.contracts import Invocation  # noqa: E402
from services.shop_actions.execution import invoke  # noqa: E402
from services.shop_actions.registry import Registry  # noqa: E402
from services.shop_bot_context import resolve_bot_context  # noqa: E402

EVIDENCE = Path("/qa/action-registry-evidence.json")
FIXTURE = Path("/qa/action-registry-fixture.json")
checks = []


def passed(check):
    """Record only checks whose assertions have actually completed."""
    checks.append({"check": check, "status": "PASS"})
    print("PASS  " + check, flush=True)


def request(key, data=None, **overrides):
    """Allocate a fresh exact business operation; callers retain it for replay."""
    return Invocation(
        **(
            {
                "invocation_id": str(uuid4()),
                "action_key": key,
                "input": data or {},
                "idempotency_key": str(uuid4()),
                "correlation_id": uuid4().hex,
            }
            | overrides
        )
    )


async def new_buyer(fixture, bot_key="telegram"):
    """Create an explicit existing synthetic customer, never an enrollment shortcut."""
    async with session_maker() as db:
        bot = await resolve_bot_context(
            db,
            authenticated_bot_id=fixture["bots"][bot_key],
            authenticated_platform=(
                Platform.BALE if bot_key == "bale" else Platform.TELEGRAM
            ),
        )
        customer = ShopStoreCustomer(store_id=bot.store_id, display_name="Action QA")
        db.add(customer)
        await db.flush()
        user_id = 10_000_000 + int(uuid4().hex[:7], 16)
        identity = ShopIdentity(
            store_id=bot.store_id,
            bot_id=bot.bot_id,
            platform=bot.platform.value,
            platform_user_id=user_id,
            customer_id=customer.id,
        )
        db.add(identity)
        await db.commit()
        return await customer_principal(db, verified_bot=bot, platform_user_id=user_id)


async def call(principal, operation, *, registry=None):
    """Give each operation its own actual AsyncSession, matching the production contract."""
    async with session_maker() as db:
        return await invoke(db, principal, operation, registry=registry)


async def cart(principal):
    """Read the real current cart through the same typed Action service."""
    result = await call(principal, request("cart.get", mode="dry_run"))
    assert result.status == "succeeded", result.error
    return result.output


async def counts():
    """Count business and receipt tables around operations promised to have no effect."""
    async with session_maker() as db:
        result = {}
        for model in (
            ShopCart,
            ShopCartItem,
            ShopIdentity,
            ShopOrder,
            ShopSupportTicket,
            ShopSupportMessage,
            ShopActionExecution,
            ShopActionAuthorization,
        ):
            result[model.__tablename__] = await db.scalar(
                select(func.count()).select_from(model)
            )
        return result


async def race(principal, operations, *, synchronize_insert=False):
    """Race two real writers; optional flush barrier forces competing unique claims."""
    barrier = asyncio.Barrier(2)
    reached = 0

    async def writer(operation):
        nonlocal reached
        async with session_maker() as db:
            flushed = False
            original = db.flush

            async def synchronized_flush(*args, **kwargs):
                nonlocal flushed, reached
                if (
                    synchronize_insert
                    and not flushed
                    and any(isinstance(row, ShopActionExecution) for row in db.new)
                ):
                    flushed = True
                    reached += 1
                    await barrier.wait()
                return await original(*args, **kwargs)

            db.flush = synchronized_flush
            if not synchronize_insert:
                await barrier.wait()
            return await invoke(db, principal, operation)

    async with asyncio.timeout(45):
        result = await asyncio.gather(*(writer(operation) for operation in operations))
    if synchronize_insert:
        assert reached == 2, "Both concurrent inserts were not synchronized"
    return result


async def execute_checks(fixture):
    """Verify concrete adapter behavior, concurrency, safe modes and ownership."""
    product_id = fixture["products"]["physical"]
    for platform in ("telegram", "bale"):
        principal = await new_buyer(fixture, platform)
        before = await counts()
        catalog = await call(
            principal,
            request("catalog.search_products", {"query": "آزمایشی"}, mode="dry_run"),
        )
        assert catalog.status == "succeeded" and any(
            item["id"] == product_id for item in catalog.output["items"]
        )
        no_effect = request(
            "cart.add_item", {"product_id": product_id, "quantity": 2}, mode="dry_run"
        )
        dry = await call(principal, no_effect)
        simulation = await call(
            principal, no_effect.model_copy(update={"mode": "simulation"})
        )
        assert dry.dry_run and dry.status == "skipped" and not dry.exact_preview
        assert simulation.simulated and simulation.status == "succeeded"
        assert await counts() == before, "A safe mode wrote business/receipt rows"
        added = await call(
            principal,
            request("cart.add_item", {"product_id": product_id, "quantity": 2}),
        )
        assert added.status == "succeeded" and added.output["items"][0]["quantity"] == 2
        changed = await call(
            principal,
            request(
                "cart.update_quantity",
                {
                    "product_id": product_id,
                    "quantity": 3,
                    "expected_cart_revision": added.output["revision"],
                },
            ),
        )
        assert changed.status == "succeeded" and changed.output["subtotal_irr"] == 3000
        checkout = await call(principal, request("checkout.prepare", mode="dry_run"))
        assert checkout.status == "succeeded" and not checkout.output["ready"]
        assert "shipping_address" in checkout.output["missing"]
        passed(
            platform
            + " real catalog/UoM/cart/checkout and no-effect dry-run/simulation"
        )

    principal = await new_buyer(fixture)
    operation = request("cart.add_item", {"product_id": product_id})
    results = await race(principal, [operation, operation], synchronize_insert=True)
    assert all(item.status == "succeeded" for item in results), [
        item.error for item in results
    ]
    assert results[0].execution_receipt == results[1].execution_receipt
    assert (await cart(principal))["items"][0]["quantity"] == 1
    async with session_maker() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ShopActionExecution)
                .where(ShopActionExecution.id == operation.invocation_id)
            )
            == 1
        )
    passed(
        "PostgreSQL concurrent identical insert claims produce one cart effect and receipt"
    )

    conflict = request("cart.add_item", {"product_id": product_id})
    different = conflict.model_copy(
        update={"input": {"product_id": product_id, "quantity": 2}}
    )
    results = await race(principal, [conflict, different], synchronize_insert=True)
    assert sorted(item.status for item in results) == ["failed", "succeeded"]
    loser = next(item for item in results if item.status == "failed")
    winner = next(item for item in results if item.status == "succeeded")
    assert loser.error.code == "action_idempotency_conflict"
    assert (await cart(principal))["items"][0]["quantity"] == winner.output["items"][0][
        "quantity"
    ]
    passed("PostgreSQL same idempotency key with different normalized input conflicts")

    current = await cart(principal)
    operations = [
        request(
            "cart.update_quantity",
            {
                "product_id": product_id,
                "quantity": amount,
                "expected_cart_revision": current["revision"],
            },
        )
        for amount in (4, 5)
    ]
    results = await race(principal, operations)
    assert sorted(item.status for item in results) == ["failed", "succeeded"]
    assert (
        next(item for item in results if item.status == "failed").error.code
        == "action_cart_revision_conflict"
    )
    assert (await cart(principal))["revision"] == current["revision"] + 1
    passed("PostgreSQL competing absolute cart writes reject a stale cart revision")

    current = await cart(principal)
    clear = request("cart.clear", {"expected_cart_revision": current["revision"]})
    assert (await call(principal, clear)).status == "pending_approval"
    async with session_maker() as db:
        token = await issue_authorization(
            db,
            subject=principal,
            approver=principal,
            invocation=clear,
            purpose="customer_confirmation",
            registry=actions(),
        )
    approved = clear.model_copy(update={"confirmation_receipt": token})
    results = await race(principal, [approved, approved])
    assert all(item.status == "succeeded" for item in results)
    assert (await cart(principal))["items"] == []
    async with session_maker() as db:
        proof = await db.scalar(
            select(ShopActionAuthorization).where(
                ShopActionAuthorization.invocation_id == clear.invocation_id
            )
        )
        assert proof.consumed_invocation_id == clear.invocation_id
    passed(
        "Pending approval resumes the same operation once under concurrent confirmation replay"
    )

    failed_principal = await new_buyer(fixture)
    original = actions().resolve("cart.add_item", "1.0.0")

    async def malformed(db, owner, payload):
        output = await original.adapter(db, owner, payload)
        return output | {"private_token": "must-not-leak"}

    broken = Registry()
    broken.register(replace(original, adapter=malformed))
    operation = request("cart.add_item", {"product_id": product_id})
    result = await call(failed_principal, operation, registry=broken)
    assert result.status == "failed" and result.error.code == "action_invalid_output"
    assert (await cart(failed_principal))["cart_id"] is None
    assert "must-not-leak" not in result.model_dump_json()
    async with session_maker() as db:
        receipt = await db.get(ShopActionExecution, operation.invocation_id)
        assert receipt.status == "failed" and "must-not-leak" not in receipt.result_json
    passed(
        "Invalid adapter output rolls back actual cart creation while persisting a safe failed receipt"
    )

    acknowledged = await new_buyer(fixture)
    operation = request("cart.add_item", {"product_id": product_id})
    async with session_maker() as db:
        commit = db.commit

        async def lose_acknowledgment():
            await commit()
            raise SQLAlchemyError("Synthetic commit acknowledgment lost")

        db.commit = lose_acknowledgment
        unknown = await invoke(db, acknowledged, operation)
    assert (
        unknown.status == "pending_external"
        and unknown.error.code == "action_outcome_unknown"
    )
    replay = await call(acknowledged, operation)
    assert (
        replay.status == "succeeded"
        and (await cart(acknowledged))["items"][0]["quantity"] == 1
    )
    passed(
        "Lost commit acknowledgment reconciles through the same receipt without duplicate effects"
    )

    ticket_request = request(
        "support.create_request",
        {"topic": "general", "body": "Synthetic private Action ticket"},
    )
    first = await call(principal, ticket_request)
    second = await call(principal, ticket_request)
    assert (
        first.status == second.status == "succeeded" and first.output == second.output
    )
    async with session_maker() as db:
        ticket = await db.get(ShopSupportTicket, first.output["ticket_id"])
        assert (
            ticket.customer_id == principal.customer_id
            and ticket.bot_id == principal.bot_id
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ShopSupportMessage)
                .where(ShopSupportMessage.ticket_id == ticket.id)
            )
            == 1
        )
        receipt = await db.get(ShopActionExecution, ticket_request.invocation_id)
        assert ticket_request.input["body"] not in receipt.result_json
    passed(
        "Supported support Action reuses real ticket service with exact retry and private-body redaction"
    )

    unavailable = await call(
        principal,
        request("returns.create_request", {"order_id": 1, "reason": "damaged"}),
    )
    assert unavailable.status == "unavailable" and unavailable.output is None
    denied = await call(
        replace(principal, scopes=frozenset()),
        request("catalog.get_product", {"product_id": product_id}),
    )
    assert denied.status == "failed" and denied.error.code == "action_forbidden"
    foreign = await new_buyer(fixture, "foreign")
    hidden = await call(
        foreign, request("catalog.get_product", {"product_id": product_id})
    )
    assert (
        hidden.status == "failed" and hidden.error.code == "action_product_unavailable"
    )
    passed(
        "Unavailable services, missing scopes and Cross-Store product access fail closed"
    )
    return {
        "store_id": fixture["stores"][0],
        "bot_id": fixture["bots"]["telegram"],
        "bale_bot_id": fixture["bots"]["bale"],
        "product_id": product_id,
    }


async def signed_checks(fixture):
    """Exercise actual authentication, context, readonly POST and closed HTTP surface."""
    identity = await diagnostic_identity()
    try:
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:5000", timeout=30, trust_env=False
        ) as client:
            api = SignedAdmin(client, identity)
            await api.select(fixture["stores"][0], fixture["stores"])
            catalog = await api.call(
                "GET", "/actions", params={"bot_id": fixture["bots"]["telegram"]}
            )
            assert catalog["total"] == 19 and not catalog["runtime_available"]
            await api.call(
                "GET",
                "/actions",
                params={"bot_id": fixture["bots"]["foreign"]},
                expected=404,
            )
            before = await counts()
            preview = await api.call(
                "POST",
                "/actions/dry-run",
                payload={
                    "action_key": "catalog.search_products",
                    "bot_id": fixture["bots"]["telegram"],
                    "platform": "telegram",
                    "input": {"query": "آزمایشی"},
                },
            )
            assert preview["status"] == "succeeded" and preview["dry_run"]
            assert await counts() == before
            await api.call(
                "POST",
                "/actions/dry-run",
                payload={
                    "action_key": "cart.clear",
                    "bot_id": fixture["bots"]["telegram"],
                    "platform": "telegram",
                    "input": {"expected_cart_revision": 1},
                },
                expected=403,
            )
            await api.call("POST", "/actions/invoke", payload={}, expected=404)
            await api.call(
                "POST",
                "/actions/dry-run",
                payload={
                    "action_key": "catalog.search_products",
                    "bot_id": fixture["bots"]["telegram"],
                    "platform": "telegram",
                    "customer_id": 999,
                    "input": {},
                },
                expected=422,
            )
            passed(
                "Real signed HTTP Catalog/dry-run preserves rows, rejects tenant/authority spoofing and exposes no live execute"
            )
    finally:
        await revoke_diagnostic_session(identity[0], identity[3])


async def main():
    """Keep bounded evidence; failure exits nonzero and never records overall PASS."""
    evidence = {
        "environment": "isolated Layer 2 Codespace PostgreSQL",
        "checks": checks,
        "live_provider_calls": 0,
        "runtime_enabled": False,
    }
    try:
        fixture = json.loads(MANIFEST.read_text())
        async with session_maker() as db:
            assert (
                await db.scalar(text("SELECT current_database()")) == "shop_codespace"
            )
        state = await execute_checks(fixture)
        await signed_checks(fixture)
        FIXTURE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        evidence["status"] = "PASS"
    except Exception:
        evidence["status"] = "FAIL"
        raise
    finally:
        EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
