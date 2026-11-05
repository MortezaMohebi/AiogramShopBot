"""Exercise persisted Studio, signed HTTP and concurrent real PostgreSQL writes.

Run only in compose.workflow-qa.yml after the guarded Beta fixture seed. All
commerce/customer rows are counted before and after simulation. Temporary
normal admin sessions are revoked; no provider clients or Runtime are started.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from scripts.test_lab_safety import require_isolated_lab

require_isolated_lab()
if os.environ.get("SHOP_WORKFLOW_QA") != "1" or not __debug__:
    raise RuntimeError("Use the isolated Workflow QA stack with assertions.")

import httpx  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from db import engine, session_maker  # noqa: E402
from models.shop_workflow import ShopWorkflowRevision  # noqa: E402
from models.shop_staff import ShopStaff  # noqa: E402
from scripts.beta_receiver_admin_e2e import SignedAdmin  # noqa: E402
from scripts.beta_storefront_e2e import MANIFEST  # noqa: E402
from scripts.codespace_dashboard_probe import (  # noqa: E402
    diagnostic_identity,
    revoke_diagnostic_session,
)
from services import shop_admin_security as security  # noqa: E402
from services import shop_workflows as workflows  # noqa: E402
from services.shop_store_context import resolve_context  # noqa: E402

FIXTURE = Path("/qa/workflow-studio-fixture.json")
EVIDENCE = Path("/qa/workflow-studio-evidence.json")


def creation(template="blank"):
    """Allocate caller-reconcilable IDs for one independent additive QA draft."""
    return {
        "id": str(uuid4()),
        "operation_id": str(uuid4()),
        "key": "qa_" + uuid4().hex[:12],
        "name": "مرجوعی آزمایشی Studio",
        "description": "Synthetic isolated workflow acceptance",
        "template": template,
    }


def save_payload(record, name=None):
    """Retain exact canonical data and an explicit optimistic base."""
    return {
        "operation_id": str(uuid4()),
        "expected_revision": record["revision"],
        "name": name or record["name"],
        "description": record["description"],
        "definition": record["definition"],
        "layout": record["layout"],
    }


async def business_counts():
    """Fingerprint every existing customer/commerce table with aggregate counts."""
    async with session_maker() as db:
        tables = (
            (
                await db.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                        "AND (tablename LIKE 'shop_order%' OR tablename LIKE 'shop_cart%' "
                        "OR tablename LIKE 'shop_support%' OR tablename LIKE 'shop_payment%' "
                        "OR tablename LIKE 'shop_customer%' OR tablename LIKE 'shop_identity%')"
                    )
                )
            )
            .scalars()
            .all()
        )
        result = {}
        for name in tables:
            # The identifier is catalog-owned, never derived from request data.
            assert name.replace("_", "").isalnum()
            result[name] = await db.scalar(
                text('SELECT count(*) FROM "' + name + '"')
            )
        assert tables, "No business tables were inspected"
        return result


@asynccontextmanager
async def simultaneous_checks():
    """Release exactly two writers after both read the same authoritative base."""
    original = workflows._check_document
    ready, count = asyncio.Event(), 0

    async def gate(*args, **kwargs):
        nonlocal count
        await original(*args, **kwargs)
        count += 1
        if count == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=20)

    with patch.object(workflows, "_check_document", gate):
        yield
    assert count == 2, "The concurrency barrier did not cover both writers"


async def race(identity, record=None, *, exact=True):
    """Use separate real AsyncSessions, not mocked DB replies or serial retries."""
    payload = save_payload(record) if record else creation()

    async def writer(number):
        data = dict(payload)
        if not exact:
            data["operation_id"] = str(uuid4())
            data["name"] = "writer " + str(number)
        async with session_maker() as db:
            actor = await db.get(ShopStaff, identity[0])
            scope = await resolve_context(
                db, staff_id=actor.id, session_id=identity[3]
            )
            try:
                if record:
                    value = await workflows.save_draft(
                        db,
                        scope=scope,
                        actor=actor,
                        workflow_id=record["id"],
                        payload=data,
                    )
                else:
                    value = await workflows.create_draft(
                        db, scope=scope, actor=actor, payload=data
                    )
                await db.commit()
                return {"status": "ok", "revision": value["revision"]}
            except security.SecurityRejected as error:
                await db.rollback()
                return {"status": error.code}
            except Exception as error:
                await db.rollback()
                return {"status": type(error).__name__}

    async with simultaneous_checks():
        results = await asyncio.gather(writer(1), writer(2))
    expected = ["ok", "ok"] if exact else ["ok", "workflow_revision_conflict"]
    assert sorted(item["status"] for item in results) == sorted(
        expected
    ), results
    target = record["id"] if record else payload["id"]
    async with session_maker() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(ShopWorkflowRevision)
            .where(ShopWorkflowRevision.workflow_id == target)
        )
        assert count == (record["revision"] + 1 if record else 1)
    return results


async def main():
    """Record independently observed PASS/FAIL evidence, retaining additive fixtures."""
    fixture = json.loads(MANIFEST.read_text())
    evidence = {
        "environment": "isolated Codespace PostgreSQL",
        "checks": [],
        "live_provider_calls": 0,
        "runtime_enabled": False,
    }
    identity = await diagnostic_identity()
    failures = []
    try:
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:5000",
            timeout=30,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            api = SignedAdmin(client, identity)
            first_store, second_store = fixture["stores"]
            await api.select(first_store, [first_store])
            before = await business_counts()
            record = await api.call(
                "POST",
                "/workflows",
                expected=201,
                payload=creation("return_request"),
            )
            FIXTURE.write_text(
                json.dumps(
                    {
                        "workflow_id": record["id"],
                        "store_id": first_store,
                        "bots": fixture["bots"],
                    }
                )
            )
            assert record["validation"]["can_simulate"] is True
            assert record["runtime_available"] is False
            reloaded = await api.call("GET", "/workflows/" + record["id"])
            assert reloaded["definition"] == record["definition"]
            saved = await api.call(
                "PATCH",
                "/workflows/" + record["id"],
                payload=save_payload(record, "ویرایش پایدار"),
            )
            assert saved["revision"] == 2
            stale = await api.call(
                "PATCH",
                "/workflows/" + record["id"],
                payload=save_payload(record, "نباید بازنویسی شود"),
                expected=409,
            )
            assert stale["detail"] == "workflow_revision_conflict"
            await api.call(
                "POST",
                f'/workflows/{record["id"]}/publish',
                payload={},
                expected=409,
            )
            compare = await api.call(
                "GET",
                f'/workflows/{record["id"]}/compare',
                params={"left": 1, "right": 2},
            )
            assert "name" in compare["metadata_changed"]
            for platform in ("telegram", "bale"):
                preview = await api.call(
                    "POST",
                    f'/workflows/{record["id"]}/simulate',
                    payload={
                        "revision": 2,
                        "bot_id": fixture["bots"][platform],
                        "platform": platform,
                        "context": {"customer_name": "مشتری ساختگی"},
                        "events": [],
                    },
                )
                assert (
                    preview["status"] == "waiting"
                    and preview["simulation_only"] is True
                )
                assert preview["active_node_id"] == "order"
            await api.call(
                "POST",
                f'/workflows/{record["id"]}/simulate',
                payload={
                    "revision": 2,
                    "bot_id": fixture["bots"]["foreign"],
                    "platform": "telegram",
                    "events": [],
                },
                expected=422,
            )
            await api.select(second_store, [second_store])
            await api.call("GET", "/workflows/" + record["id"], expected=404)
            await api.select(second_store, [first_store, second_store])
            await api.call(
                "PATCH",
                "/workflows/" + record["id"],
                payload=save_payload(saved),
                expected=409,
            )
            await api.select(first_store, [first_store])
            restored = await api.call(
                "POST",
                f'/workflows/{record["id"]}/restore',
                payload={
                    "operation_id": str(uuid4()),
                    "expected_revision": 2,
                    "revision": 1,
                },
            )
            assert (
                restored["revision"] == 3
                and restored["name"] == record["name"]
            )
            old = await api.call(
                "GET", f'/workflows/{record["id"]}/revisions/2'
            )
            assert old["name"] == saved["name"]
            assert await business_counts() == before
            evidence["checks"].append(
                {
                    "check": "signed HTTP persistence, history, scopes, publish denial, both-platform simulation and unchanged business rows",
                    "status": "PASS",
                }
            )
            print(
                "PASS  Signed HTTP CRUD/history/scopes; both platforms; business rows unchanged",
                flush=True,
            )
            for name, source, exact in (
                ("concurrent exact create", None, True),
                ("concurrent exact save", restored, True),
            ):
                try:
                    await race(identity, source, exact=exact)
                    evidence["checks"].append(
                        {"check": name, "status": "PASS"}
                    )
                    print("PASS  " + name, flush=True)
                except AssertionError as error:
                    evidence["checks"].append(
                        {"check": name, "status": "FAIL", "reason": str(error)}
                    )
                    failures.append(name)
                    print("FAIL  " + name + ": " + str(error), flush=True)
            fresh = await api.call("GET", "/workflows/" + record["id"])
            try:
                await race(identity, fresh, exact=False)
                evidence["checks"].append(
                    {
                        "check": "concurrent distinct saves CAS",
                        "status": "PASS",
                    }
                )
                print("PASS  concurrent distinct saves CAS", flush=True)
            except AssertionError as error:
                evidence["checks"].append(
                    {
                        "check": "concurrent distinct saves CAS",
                        "status": "FAIL",
                        "reason": str(error),
                    }
                )
                failures.append("concurrent distinct saves CAS")
                print(
                    "FAIL  concurrent distinct saves CAS: " + str(error),
                    flush=True,
                )
    finally:
        await revoke_diagnostic_session(identity[0], identity[3])
        EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        await engine.dispose()
    assert not failures, "Workflow acceptance failed: " + ", ".join(failures)


if __name__ == "__main__":
    asyncio.run(main())
