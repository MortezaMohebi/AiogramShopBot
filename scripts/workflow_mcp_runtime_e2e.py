"""Exercise an MCP-published inquiry with real PostgreSQL and fake Bot I/O."""

from __future__ import annotations

import asyncio
import json
import os
from copy import deepcopy

from scripts.test_lab_safety import require_isolated_lab

require_isolated_lab()
if os.environ.get("SHOP_MCP_QA") != "1" or not __debug__:
    raise RuntimeError("Dedicated MCP QA mode is required.")

import httpx
from sqlalchemy import func, select

from db import engine, session_maker
from models.shop_action import ShopActionExecution
from models.shop_workflow_runtime import WorkflowRun
from scripts.beta_receiver_admin_e2e import SignedAdmin
from scripts.beta_storefront_e2e import MANIFEST
from scripts.codespace_dashboard_probe import (
    diagnostic_identity,
    revoke_diagnostic_session,
)
from scripts.workflow_runtime_e2e import Harness
from services.shop_runtime import workers


async def run(data: dict) -> dict:
    """Consume the fixed published snapshot without a live provider or payment."""
    fixture = json.loads(MANIFEST.read_text())
    identity = await diagnostic_identity()
    try:
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:5000",
            timeout=15,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            harness = Harness(fixture, SignedAdmin(client, identity), {})
            await harness.bootstrap()
            # These synthetic Bots have no running receiver. Establish the lab's
            # existing Native Runtime gate through its normal signed manager API.
            await harness.set_gate()
            for platform in ("telegram", "bale"):
                await harness.set_gate(bot_id=fixture["bots"][platform])

            def callback(case, label):
                """Use only the capability actually rendered to this customer."""
                for message in reversed(harness.native[case.bot_id].messages):
                    if int(message["chat_id"]) != case.user_id:
                        continue
                    for row in message.get("reply_markup", {}).get(
                        "inline_keyboard", []
                    ):
                        for button in row:
                            if button.get("text") == label:
                                return button["callback_data"]
                raise AssertionError("qa_rendered_callback_missing")

            cases = []
            with harness.fence.install(), harness.providers():
                for platform in ("telegram", "bale"):
                    case = await harness.new_case(platform, start=False)
                    update = harness.raw(case, text_value="/" + data["command"])
                    answers = await asyncio.gather(
                        harness.offer(case, update),
                        harness.offer(case, deepcopy(update)),
                    )
                    case.run_id = next(
                        row["run_id"] for row in answers if row.get("run_id")
                    )
                    row = await harness.run(case)
                    assert row.publication_id == data["publication_id"]
                    assert row.workflow_id == data["workflow_id"]
                    assert row.node_id == "question"
                    await harness.drain()
                    await harness.input(
                        case, "category", text_value=data["query"]
                    )
                    await harness.offer(
                        case,
                        harness.raw(
                            case,
                            callback=callback(case, data["category_name"]),
                        ),
                    )
                    await harness.drain(workers.action_once)
                    await harness.drain()
                    assert (await harness.run(case)).node_id == "phone"
                    # A contact belonging to another person never satisfies an
                    # own-contact question, even when its phone looks valid.
                    phone = "+98912" + str(case.user_id)[-7:]
                    contact = {
                        "phone_number": phone,
                        "first_name": "QA_PRIVATE",
                        "user_id": case.user_id + 1,
                    }
                    await harness.offer(
                        case, harness.raw(case, contact=contact)
                    )
                    assert (await harness.run(case)).node_id == "phone"
                    await harness.offer(
                        case,
                        harness.raw(
                            case, contact=contact | {"user_id": case.user_id}
                        ),
                    )
                    await harness.drain()
                    assert (await harness.run(case)).node_id == "confirm"
                    finish = harness.raw(
                        case, callback=callback(case, "پایان استعلام")
                    )
                    await harness.offer(case, finish)
                    await harness.drain()
                    before = len(harness.native[case.bot_id].messages)
                    assert (await harness.run(case)).status == "completed"
                    assert (await harness.offer(case, finish))["duplicate"]
                    await harness.drain()
                    assert len(harness.native[case.bot_id].messages) == before
                    outboxes = await harness.outboxes(case)
                    assert all(item.status == "sent" for item in outboxes)
                    assert all(item.message_ids for item in outboxes)
                    cases.append(case)
            assert (
                await harness.commerce_fingerprint()
                == harness.initial_commerce
            )
            async with session_maker() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(WorkflowRun)
                        .where(WorkflowRun.workflow_id == data["workflow_id"])
                    )
                    == 2
                )
                count = await db.scalar(
                    select(func.count())
                    .select_from(ShopActionExecution)
                    .where(
                        ShopActionExecution.workflow_id == data["workflow_id"],
                        ShopActionExecution.action_key
                        == "catalog.search_products",
                        ShopActionExecution.action_version == "2.0.0",
                        ShopActionExecution.status == "succeeded",
                    )
                )
                assert count == 2
            return {
                "status": "PASS",
                "platforms": ["telegram", "bale"],
                "completed_runs": len(cases),
                "action_receipts": count,
                "commerce_unchanged": True,
                "duplicate_send_count": 0,
                "denied_network_calls": harness.fence.denied,
            }
    finally:
        await revoke_diagnostic_session(identity[0], identity[3])
        await engine.dispose()
