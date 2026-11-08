"""Publication, durable replay and authored outcome integration regressions."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from channels.contracts import Platform
from models.shop_content import ShopIdentity
from tests.schema_support import TEST_BOT_IDS, seed_customer
from models.shop_workflow_runtime import (
    WorkflowEvent,
    WorkflowInbox,
    WorkflowOutbox,
    WorkflowRun,
    WorkflowWait,
)
from services import shop_admin_security as security
from services.shop_actions.context import customer_principal
from services.shop_bot_context import resolve_bot_context
from services.shop_runtime import sessions, workers
from services.shop_runtime.adapters import _markup, normalize
from services.shop_runtime.publication import (
    confirmation_findings,
    presentation_findings,
)
from services.shop_workflow_schema import Definition
from services.shop_workflow_templates import wholesale_application_template
from tests.test_action_security import buyer, db
from tests.test_runtime_interpreter import form
from tests.test_runtime_sessions import inbound, setup_runtime
from tests.test_runtime_workers import factory


async def interrupted(database, context, event, monkeypatch):
    """Leave a real durable inbox pending at the pre-consumption crash boundary."""

    async def crash(*args, **kwargs):
        raise RuntimeError("offline crash")

    with monkeypatch.context() as fault:
        fault.setattr(sessions, "_consume", crash)
        with pytest.raises(RuntimeError, match="offline crash"):
            await sessions.handle(database, context=context, event=event)
    await database.rollback()


@pytest.mark.asyncio
async def test_typed_defaults_and_trusted_name_survive_pending_start(
    buyer, monkeypatch
):
    """All reference defaults remain JSON across start, restart worker and exact replay."""
    database, principal = buyer
    raw = form().model_dump(mode="json")
    refs = {
        kind: {"kind": kind, "id": 1}
        for kind in ("category", "customer", "order", "product")
    }
    raw["variables"] += [
        {"name": k, "type": k + "_ref", "default": v} for k, v in refs.items()
    ]
    raw["nodes"][1]["config"]["prompt"] = "Hello {{context.customer_name}}"
    await setup_runtime(
        database, principal, monkeypatch, Definition.model_validate(raw)
    )
    start = inbound(1, "/wholesale", "command")
    await interrupted(database, principal.bot, start, monkeypatch)
    assert await workers.inbox_once(factory(database))
    replay = await sessions.handle(database, context=principal.bot, event=start)
    run = await database.scalar(select(WorkflowRun))
    assert replay == {
        "handled": True,
        "status": "waiting_input",
        "run_id": run.id,
        "duplicate": True,
    }
    assert run.values == refs
    assert (await database.scalar(select(WorkflowOutbox))).payload[
        "text"
    ] == "Hello QA buyer"
    assert "QA buyer" not in str((await database.scalar(select(WorkflowEvent))).summary)


@pytest.mark.asyncio
async def test_invalid_stored_input_quarantined_before_next_ready_input(
    buyer, monkeypatch
):
    """Corrupt payload or envelope identity cannot execute, leak text or block replay."""
    database, p = buyer
    await setup_runtime(database, p, monkeypatch)
    await interrupted(database, p.bot, inbound(1, "/wholesale", "command"), monkeypatch)
    row = await database.scalar(select(WorkflowInbox))
    row.payload = {"text": "private"}
    await database.commit()
    await interrupted(database, p.bot, inbound(2, "/wholesale", "command"), monkeypatch)
    assert await workers.inbox_once(factory(database))
    assert await workers.inbox_once(factory(database))
    database.session.expire_all()
    assert row.status == "rejected" and row.payload == {}
    assert row.error_code == "runtime_stored_input_invalid"
    assert (await database.scalar(select(WorkflowRun))).status == "waiting_input"


@pytest.mark.asyncio
async def test_timer_only_wait_rejects_early_text_without_answering_next_question(
    buyer, monkeypatch
):
    """An unanswerable epoch never steals the next question or blocks its timer."""
    database, p = buyer
    raw = form().model_dump(mode="json")
    raw["nodes"].append({"id": "delay", "type": "delay", "config": {"seconds": 5}})
    raw["edges"][0]["target"] = "delay"
    raw["edges"].append({"id": "after_delay", "source": "delay", "target": "name"})
    await setup_runtime(database, p, monkeypatch, Definition.model_validate(raw))
    await sessions.handle(
        database, context=p.bot, event=inbound(1, "/wholesale", "command")
    )
    await interrupted(database, p.bot, inbound(2, "early answer"), monkeypatch)
    later = security.clock() + timedelta(seconds=10)
    monkeypatch.setattr(security, "clock", lambda: later)
    assert await workers.timeout_once(factory(database))
    assert await workers.inbox_once(factory(database))
    database.session.expire_all()
    row = await database.scalar(
        select(WorkflowInbox).where(WorkflowInbox.input_id == "2")
    )
    run = await database.scalar(select(WorkflowRun))
    assert (run.node_id, run.status, run.values) == ("name", "waiting_input", {})
    assert row.status == "rejected" and row.error_code == "runtime_input_stale"


@pytest.mark.parametrize("kind", ["show_buttons", "go_to_step"])
def test_consent_analysis_includes_direct_graph_targets(kind):
    """No binding or per-platform direct jump may circumvent prior confirmation."""
    definition, _ = wholesale_application_template()
    raw = definition.model_dump(mode="json")
    config = (
        {
            "text": "Choose",
            "buttons": [
                {"key": "go", "label": "Go", "target": "apply", "platforms": ["bale"]}
            ],
        }
        if kind == "show_buttons"
        else {"target": "apply"}
    )
    raw["nodes"].append({"id": "jump", "type": kind, "config": config})
    raw["edges"][0]["target"] = "jump"
    findings = confirmation_findings(Definition.model_validate(raw))
    assert any(
        x["code"] == "runtime_confirmation_required" and x["node_id"] == "apply"
        for x in findings
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "bale"])
async def test_reply_label_round_trip(buyer, monkeypatch, platform):
    """A normalized literal label resolves only an offered current server choice."""
    database, p = buyer
    if platform == "bale":
        bot_id = TEST_BOT_IDS["bale"]
        identity = seed_customer(database.session, "bale", 101)
        identity.customer_id = p.customer_id
        await database.commit()
        bot = await resolve_bot_context(
            database, authenticated_bot_id=bot_id, authenticated_platform=Platform.BALE
        )
        p = await customer_principal(database, verified_bot=bot, platform_user_id=101)
    raw = form().model_dump(mode="json")
    raw["nodes"][1] = {
        "id": "name",
        "type": "show_buttons",
        "config": {
            "text": "Choose",
            "keyboard": "reply",
            "buttons": [
                {"key": "go", "label": "Continue", "target": "amount"},
                {
                    "key": "hidden",
                    "label": "Forbidden",
                    "target": "done",
                    "platforms": ["telegram" if platform == "bale" else "bale"],
                },
            ],
        },
    }
    await setup_runtime(database, p, monkeypatch, Definition.model_validate(raw))

    def event(i, text):
        return normalize(
            p.bot,
            {
                "update_id": i,
                "message": {
                    "chat": {"type": "private", "id": 101},
                    "from": {"id": 101},
                    "text": text,
                },
            },
        )

    await sessions.handle(database, context=p.bot, event=event(1, "/wholesale"))
    payload = (await database.scalar(select(WorkflowOutbox))).payload
    label = _markup(payload)["keyboard"][0][0]["text"]
    assert label == "Continue"
    for i, text in enumerate(("Forbidden", "amount", label), 2):
        await sessions.handle(database, context=p.bot, event=event(i, text))
    run = await database.scalar(select(WorkflowRun))
    assert (run.node_id, run.status) == ("amount", "waiting_input")


@pytest.mark.asyncio
@pytest.mark.parametrize("decline", [False, True])
async def test_authored_decline_loop_is_distinct_from_global_cancel(
    buyer, monkeypatch, decline
):
    """A literal global cancel terminates even when the decline edge revisits a form."""
    database, p = buyer
    raw = form().model_dump(mode="json")
    raw["edges"][0]["target"] = "review"
    raw["edges"][-1]["target"] = "name"
    await setup_runtime(database, p, monkeypatch, Definition.model_validate(raw))
    await sessions.handle(
        database, context=p.bot, event=inbound(1, "/wholesale", "command")
    )
    token = (await database.scalar(select(WorkflowOutbox))).payload["buttons"][1][
        "callback_data"
    ]
    event = (
        inbound(2, "", "callback").model_copy(update={"callback": token})
        if decline
        else inbound(2, "/cancel", "command")
    )
    result = await sessions.handle(database, context=p.bot, event=event)
    assert result["status"] == ("waiting_input" if decline else "cancelled")
    if decline:
        assert (await database.scalar(select(WorkflowRun))).node_id == "name"


@pytest.mark.asyncio
async def test_wholesale_decline_delivers_configured_notice_only(buyer, monkeypatch):
    """Declining the provided form sends one real delivery receipt and no Action."""
    database, p = buyer
    definition, _ = wholesale_application_template()
    await setup_runtime(database, p, monkeypatch, definition)
    from models.shop_workflow_runtime import RuntimeBinding, WorkflowActionJob

    (await database.scalar(select(RuntimeBinding))).node_id = "review"
    await database.commit()
    await sessions.handle(
        database, context=p.bot, event=inbound(1, "/wholesale", "command")
    )
    token = (await database.scalar(select(WorkflowOutbox))).payload["buttons"][1][
        "callback_data"
    ]
    await sessions.handle(
        database,
        context=p.bot,
        event=inbound(2, "", "callback").model_copy(update={"callback": token}),
    )
    sent = []

    async def send(context, chat_id, payload):
        sent.append(payload["text"])
        return ["91"]

    while await workers.deliver_once(factory(database), send=send):
        pass
    database.session.expire_all()
    rows = (
        await database.scalars(select(WorkflowOutbox).order_by(WorkflowOutbox.sequence))
    ).all()
    assert [x.status for x in rows] == ["cancelled", "sent"] and rows[
        -1
    ].message_ids == ["91"]
    assert sent == [
        next(x.config["message"] for x in definition.nodes if x.id == "cancelled")
    ]
    assert await database.scalar(select(WorkflowActionJob)) is None


@pytest.mark.parametrize("kind", ["request_contact", "reserved", "reply_command"])
def test_publication_rejects_unrepresentable_choices(kind):
    """Reject misleading contact, control collision and command-shaped labels."""
    raw = form().model_dump(mode="json")
    button = {
        "key": "cancel" if kind == "reserved" else "go",
        "label": "/cancel" if kind == "reply_command" else "Go",
        "type": "request_contact" if kind == "request_contact" else "callback",
        "target": "done",
    }
    raw["nodes"][1] = {
        "id": "name",
        "type": "show_buttons",
        "config": {"text": "Pick", "keyboard": "reply", "buttons": [button]},
    }
    assert presentation_findings(Definition.model_validate(raw))


def test_album_requires_target_runtime_capability(monkeypatch):
    """Schema compatibility alone cannot enable a missing platform adapter capability."""
    from services.shop_platform_capabilities import CAPABILITIES

    raw = form().model_dump(mode="json")
    raw["nodes"][1] = {
        "id": "name",
        "type": "send_media_group",
        "config": {"media_ids": [1, 2]},
    }
    monkeypatch.setitem(CAPABILITIES["bale"], "runtime_media_group", False)
    findings = presentation_findings(
        Definition.model_validate(raw), media_kinds={1: "photo", 2: "photo"}
    )
    assert [(x["node_id"], x["platform"]) for x in findings] == [("name", "bale")]


@pytest.mark.asyncio
@pytest.mark.parametrize("scheduled", [False, True])
@pytest.mark.parametrize("outcome", ["cancel", "end"])
async def test_wait_policy_shared_by_receiver_and_scheduler(
    buyer, monkeypatch, scheduled, outcome
):
    """The input timeout policy governs an unanswered wait, never a pending effect."""
    database, p = buyer
    raw = form().model_dump(mode="json")
    raw["timeout_policy"] = {"seconds": 1, "outcome": outcome}
    await setup_runtime(database, p, monkeypatch, Definition.model_validate(raw))
    await sessions.handle(
        database, context=p.bot, event=inbound(1, "/wholesale", "command")
    )
    later = security.clock() + timedelta(seconds=3)
    monkeypatch.setattr(security, "clock", lambda: later)
    if scheduled:
        assert await workers.timeout_once(factory(database))
    else:
        await sessions.handle(database, context=p.bot, event=inbound(2, "late"))
    database.session.expire_all()
    run = await database.scalar(select(WorkflowRun))
    assert run.status == ("cancelled" if outcome == "cancel" else "completed")
    assert run.error_code == "runtime_input_timeout" and run.values == {}
    assert (
        (
            await database.scalars(
                select(WorkflowOutbox).order_by(WorkflowOutbox.sequence)
            )
        )
        .all()[-1]
        .payload["notice"]
    )


def test_error_policy_uses_authored_terminal_message():
    """Resource exhaustion keeps its stable reason without inventing business success."""
    from services.shop_runtime.interpreter import Machine

    raw = form().model_dump(mode="json")
    raw["error_policy"] = {
        "on_error": "cancel",
        "message": "Unable to continue",
        "max_steps": 1,
    }
    machine = Machine(Definition.model_validate(raw), node_id="s", platform="telegram")
    machine.advance()
    assert (machine.status, machine.error, machine.outbound[-1]["text"]) == (
        "cancelled",
        "runtime_step_budget",
        "Unable to continue",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["version", "disabled", "invalid_input"])
async def test_registry_outcomes_route_distinct_ports_and_next_customer(
    buyer, monkeypatch, failure
):
    """Real Registry errors select authored destinations; removal cannot poison the queue."""
    from models.shop_action import ShopActionExecution
    from models.shop_store_commerce import ShopBotCommercePolicy, ShopStoreCustomer
    from models.shop_workflow_runtime import WorkflowActionJob

    database, p = buyer
    raw = form().model_dump(mode="json")
    raw["nodes"][1] = {
        "id": "name",
        "type": "action",
        "config": {
            "action_key": "cart.get",
            "action_version": "1.0.0",
            "input_mapping": {},
            "output_mapping": {},
        },
    }
    raw["nodes"] += [
        {"id": k, "type": "cancel", "config": {"message": k}}
        for k in ("err", "offline")
    ]
    raw["edges"] = [e for e in raw["edges"] if e["source"] != "name"]
    raw["edges"] += [
        {"id": "port_" + port, "source": "name", "port": port, "target": target}
        for port, target in (
            ("success", "done"),
            ("error", "err"),
            ("unavailable", "offline"),
            ("retry", "err"),
            ("pending_approval", "err"),
        )
    ]
    raw["nodes"].append(
        {
            "id": "catalog",
            "type": "action",
            "config": {
                "action_key": "catalog.list_categories",
                "action_version": "1.0.0",
                "input_mapping": {},
                "output_mapping": {},
            },
        }
    )
    raw["edges"].append(
        {
            "id": "catalog_success",
            "source": "catalog",
            "port": "success",
            "target": "done",
        }
    )
    await setup_runtime(database, p, monkeypatch, Definition.model_validate(raw))
    first = await sessions.handle(
        database, context=p.bot, event=inbound(1, "/wholesale", "command")
    )
    job = await database.scalar(select(WorkflowActionJob))
    if failure == "version":
        from services.shop_actions.catalog import actions

        registry = actions()
        monkeypatch.delitem(registry._specs, ("cart.get", "1.0.0"))
    elif failure == "disabled":
        (await database.get(ShopBotCommercePolicy, p.bot_id)).cart_enabled = False
    else:
        job.input = {"unexpected": "private-value"}
    from models.shop_workflow_runtime import RuntimeBinding

    (await database.scalar(select(RuntimeBinding))).node_id = "catalog"
    customer = ShopStoreCustomer(store_id=p.store_id, display_name="Other")
    database.add(customer)
    await database.flush()
    database.add(
        ShopIdentity(
            store_id=p.store_id,
            customer_id=customer.id,
            platform=p.platform,
            bot_id=p.bot_id,
            platform_user_id=202,
        )
    )
    await database.commit()
    other = await sessions.handle(
        database,
        context=p.bot,
        event=inbound(2, "/wholesale", "command").model_copy(
            update={"user_id": 202, "chat_id": 202}
        ),
    )
    # Both jobs must be serviced; no synthetic success receipt or physical effect.
    assert await workers.action_once(factory(database))
    assert await workers.action_once(factory(database))
    database.session.expire_all()
    run = await database.get(WorkflowRun, first["run_id"])
    assert run.node_id == ("err" if failure == "invalid_input" else "offline")
    assert job.status == "failed" and job.error_code
    other_run = await database.get(WorkflowRun, other["run_id"])
    assert other_run.node_id == "done"
    assert await database.get(ShopActionExecution, job.invocation_id) is None
    assert "private-value" not in str(
        (await database.scalars(select(WorkflowEvent.summary))).all()
    )


@pytest.mark.asyncio
async def test_malformed_snapshot_replay_rejects_durably_and_other_work_advances(
    buyer, monkeypatch
):
    """Malformed persisted definitions quarantine their Run without leaking stored data."""
    from models.shop_workflow_runtime import PublishedWorkflow, RuntimeBinding

    database, p = buyer
    good = await setup_runtime(database, p, monkeypatch)
    original = await database.scalar(select(RuntimeBinding))
    bad = PublishedWorkflow(
        store_id=p.store_id,
        workflow_id=good.workflow_id,
        revision=2,
        definition={"private": "broken"},
        digest="b" * 64,
        published_by=good.published_by,
    )
    database.add(bad)
    await database.flush()
    database.add(
        RuntimeBinding(
            store_id=p.store_id,
            bot_id=p.bot_id,
            workflow_id=good.workflow_id,
            publication_id=bad.id,
            kind="command",
            key="broken",
            node_id=original.node_id,
        )
    )
    await database.commit()
    await interrupted(database, p.bot, inbound(1, "/broken", "command"), monkeypatch)
    assert await workers.inbox_once(factory(database))
    database.session.expire_all()
    inbox = await database.scalar(select(WorkflowInbox))
    run = await database.get(WorkflowRun, inbox.run_id)
    assert inbox.status == "rejected" and inbox.payload == {}
    assert (
        run.status == "failed" and run.error_code == "runtime_stored_definition_invalid"
    )
    assert (await database.scalar(select(WorkflowEvent))).error_code == run.error_code
    assert (
        await sessions.handle(
            database, context=p.bot, event=inbound(2, "/wholesale", "command")
        )
    )["status"] == "waiting_input"


@pytest.mark.asyncio
async def test_timely_durable_answer_wins_after_deadline(buyer, monkeypatch):
    """Priority is based on durable receipt time, not worker scheduling time."""
    database, p = buyer
    await setup_runtime(database, p, monkeypatch)
    await sessions.handle(
        database, context=p.bot, event=inbound(1, "/wholesale", "command")
    )
    await interrupted(database, p.bot, inbound(2, "Timely"), monkeypatch)
    deadline = (await database.scalar(select(WorkflowWait))).deadline
    monkeypatch.setattr(
        security, "clock", lambda: security.utc(deadline) + timedelta(seconds=2)
    )
    assert not await workers.timeout_once(factory(database))
    assert await workers.inbox_once(factory(database))
    database.session.expire_all()
    run = await database.scalar(select(WorkflowRun))
    assert run.node_id == "amount" and run.values == {"name": "Timely"}


@pytest.mark.asyncio
@pytest.mark.parametrize("scheduled", [True, False])
async def test_explicit_timeout_edge_overrides_terminal_policy(
    buyer, monkeypatch, scheduled
):
    """Late input and scheduled timeout traverse the same authored edge exactly once."""
    database, p = buyer
    raw = form().model_dump(mode="json")
    raw["edges"].append(
        {"id": "too_late", "source": "name", "port": "timeout", "target": "amount"}
    )
    await setup_runtime(database, p, monkeypatch, Definition.model_validate(raw))
    await sessions.handle(
        database, context=p.bot, event=inbound(1, "/wholesale", "command")
    )
    deadline = (await database.scalar(select(WorkflowWait))).deadline
    monkeypatch.setattr(
        security, "clock", lambda: security.utc(deadline) + timedelta(seconds=2)
    )
    if scheduled:
        assert await workers.timeout_once(factory(database))
    else:
        await sessions.handle(database, context=p.bot, event=inbound(2, "late"))
    database.session.expire_all()
    run = await database.scalar(select(WorkflowRun))
    assert (run.node_id, run.status, run.values) == ("amount", "waiting_input", {})
    assert (
        await database.scalar(
            select(WorkflowEvent).where(WorkflowEvent.kind == "timeout")
        )
    ).error_code == "runtime_input_timeout"


@pytest.mark.parametrize("port", ["retry", "pending_approval"])
def test_publication_blocks_simulator_only_wait_destinations(port):
    """A durable wait cannot claim to jump to a distinct simulator-only destination."""
    definition, _ = wholesale_application_template()
    assert not presentation_findings(definition)
    raw = definition.model_dump(mode="json")
    next(e for e in raw["edges"] if e["source"] == "apply" and e["port"] == port)[
        "target"
    ] = "done"
    assert {
        x["code"] for x in presentation_findings(Definition.model_validate(raw))
    } == {"runtime_action_wait_port_unsupported"}


def test_declared_alternate_entry_cannot_skip_consent():
    """Every bindable entry, not merely the start node, establishes a trust boundary."""
    definition, _ = wholesale_application_template()
    assert not confirmation_findings(definition)
    raw = definition.model_dump(mode="json")
    raw["entry_points"].append({"kind": "command", "key": "unsafe", "node_id": "apply"})
    assert {
        x["code"] for x in confirmation_findings(Definition.model_validate(raw))
    } == {"runtime_confirmation_required"}


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_confirmed_cart_loses_availability_before_proof(
    buyer, monkeypatch, expired
):
    """Route disabled commerce only after valid consent, preserving the real cart."""
    from models.shop_action import ShopActionAuthorization, ShopActionExecution
    from models.shop_checkout import ShopCartItem
    from models.shop_store_commerce import ShopBotCommercePolicy
    from models.shop_workflow_runtime import WorkflowActionJob
    from services.shop_actions.execution import invoke
    from tests.test_action_adapters import request
    from tests.test_shared_cart import seed

    database, principal = buyer
    product, _ = seed(database)
    added = await invoke(
        database,
        principal,
        request("cart.add_item", {"product_id": product.id, "quantity": 2}),
    )
    assert added.status == "succeeded"

    nodes = [
        {"id": "start", "type": "start"},
        {"id": "review", "type": "confirm", "config": {"prompt": "Clear your cart?"}},
        {
            "id": "clear",
            "type": "action",
            "config": {
                "action_key": "cart.clear",
                "action_version": "1.0.0",
                "input_mapping": {
                    "expected_cart_revision": {
                        "kind": "constant",
                        "value": added.output["revision"],
                    }
                },
                "output_mapping": {},
            },
        },
        *(
            {"id": key, "type": "end"}
            for key in ("done", "failure", "offline", "decline")
        ),
    ]
    transitions = [
        ("start", "next", "review"),
        ("review", "confirm", "clear"),
        ("review", "cancel", "decline"),
        ("clear", "success", "done"),
        ("clear", "error", "failure"),
        ("clear", "unavailable", "offline"),
        ("clear", "retry", "failure"),
        ("clear", "pending_approval", "failure"),
    ]
    definition = Definition.model_validate(
        {
            "nodes": nodes,
            "edges": [
                {"id": f"e{i}", "source": source, "port": port, "target": target}
                for i, (source, port, target) in enumerate(transitions)
            ],
        }
    )
    await setup_runtime(database, principal, monkeypatch, definition)
    await sessions.handle(
        database, context=principal.bot, event=inbound(1, "/wholesale", "command")
    )
    offered = (await database.scalar(select(WorkflowOutbox))).payload["buttons"][0][
        "callback_data"
    ]
    confirmed = await sessions.handle(
        database,
        context=principal.bot,
        event=inbound(2, "", "callback").model_copy(update={"callback": offered}),
    )
    assert confirmed["status"] == "waiting_action"

    (await database.get(ShopBotCommercePolicy, principal.bot_id)).cart_enabled = False
    await database.commit()
    if expired:
        after_consent = security.clock() + timedelta(minutes=6)
        monkeypatch.setattr(security, "clock", lambda: after_consent)
    assert await workers.action_once(factory(database))
    database.session.expire_all()

    run = await database.scalar(select(WorkflowRun))
    job = await database.scalar(select(WorkflowActionJob))
    assert (run.status, run.node_id) == (
        ("failed", "clear") if expired else ("completed", "offline")
    )
    code = "runtime_confirmation_expired" if expired else "action_cart_disabled"
    assert job.status == "failed" and job.error_code == code and job.receipt_id is None
    event = await database.scalar(
        select(WorkflowEvent).where(WorkflowEvent.kind == "action")
    )
    assert (event.status, event.error_code) == (
        "failed" if expired else "unavailable",
        code,
    )
    assert await database.get(ShopActionExecution, job.invocation_id) is None
    assert (
        await database.scalar(
            select(ShopActionAuthorization.id).where(
                ShopActionAuthorization.invocation_id == job.invocation_id
            )
        )
        is None
    )
    assert (await database.scalar(select(ShopCartItem))).quantity == 2
