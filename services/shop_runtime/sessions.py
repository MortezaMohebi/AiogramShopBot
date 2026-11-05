"""Serialized customer transitions, deduplicated inbox and atomic outbound intents."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

import config
from channels.contracts import Platform
from models.shop_content import ShopIdentity
from models.shop_store_commerce import ShopStoreCustomer
from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import ShopBot, ShopStore
from models.shop_workflow_runtime import (
    PublishedWorkflow,
    RuntimeAudit,
    RuntimeBinding,
    RuntimeGate,
    RuntimeSlot,
    WorkflowActionJob,
    WorkflowCallback,
    WorkflowEvent,
    WorkflowInbox,
    WorkflowOutbox,
    WorkflowRun,
    WorkflowWait,
)
from services import shop_admin_security as security
from services.shop_action_bindings import resolve_inputs
from services.shop_actions.context import customer_principal
from services.shop_actions.contracts import ActionRejected
from services.shop_bot_context import resolve_bot_context
from services.shop_runtime.contracts import (
    INPUTS_PER_MINUTE,
    MAX_EVENTS,
    MAX_OUTBOX,
    MAX_PENDING_INPUTS,
    RESERVED_COMMANDS,
    TERMINAL,
    RuntimeInput,
    RuntimeRejected,
)
from services.shop_runtime.interpreter import Machine
from services.shop_workflow_schema import Definition


def token_hash(token):
    """Store only a digest of customer callback capabilities."""
    return hashlib.sha256(token.encode()).hexdigest()


def gate_key(store_id, bot_id=None):
    """Namespace independent Store and Bot authority even for colliding UUIDs."""
    return "bot:" + bot_id if bot_id is not None else "store:" + store_id


async def enabled(db, context) -> bool:
    """Recheck every opt-in and live Bot/Store operation state before doing work."""
    if (
        not config.SHOP_WORKFLOW_RUNTIME_ENABLED
        or config.SHOP_WORKFLOW_RUNTIME_KILL_SWITCH
    ):
        return False
    try:
        fresh = await resolve_bot_context(
            db,
            authenticated_bot_id=context.bot_id,
            authenticated_platform=context.platform,
        )
    except security.SecurityRejected:
        return False
    if fresh.store_id != context.store_id:
        return False
    operation = await db.get(ShopBotOperations, context.bot_id)
    if operation and operation.desired_state != "active":
        return False
    for key in (gate_key(context.store_id), gate_key(context.store_id, context.bot_id)):
        gate = await db.scalar(
            select(RuntimeGate).where(
                RuntimeGate.scope_key == key, RuntimeGate.store_id == context.store_id
            )
        )
        if gate is None or not gate.enabled or gate.killed:
            return False
    return True


async def _slot(db, context, user_id):
    """Create a unique serialization row safely even for simultaneous first messages."""
    query = select(RuntimeSlot).where(
        RuntimeSlot.bot_id == context.bot_id, RuntimeSlot.user_id == user_id
    )
    # Acquiring the lock must also replace any preloaded identity-map state.
    query = query.execution_options(populate_existing=True)
    row = await db.scalar(query.with_for_update())
    if row is None:
        try:
            async with db.begin_nested():
                db.add(
                    RuntimeSlot(
                        id=str(uuid4()),
                        store_id=context.store_id,
                        bot_id=context.bot_id,
                        user_id=user_id,
                    )
                )
                await db.flush()
        except IntegrityError:
            pass
        row = await db.scalar(query.with_for_update())
    return row


async def entry(db, context, event, *, origin="customer"):
    """Resolve declared stable keys only; input never supplies a node or version."""
    kind, key = None, None
    if event.kind == "command":
        command, *arguments = event.text.split(maxsplit=1)
        command = command.removeprefix("/").split("@", 1)[0].lower()
        if command in RESERVED_COMMANDS:
            return None
        if command == "start":
            kind, key = "start", arguments[0] if arguments else "default"
        else:
            kind, key = "command", command
    elif event.kind == "callback" and event.callback.startswith("wfe:"):
        kind, key = "menu", event.callback[4:]
    elif event.kind == "internal" and origin in {
        "internal",
        "legacy_bridge",
        "admin_test",
    }:
        kind, key = origin if origin != "internal" else "internal", event.text
    if kind is None:
        return None
    # Routing reads a committed pointer; the resulting Run pins its immutable
    # publication. Locking this parent before the customer slot would invert
    # the FK key-share/slot lock order after the durable Inbox commit.
    return await db.scalar(
        select(RuntimeBinding)
        .where(
            RuntimeBinding.store_id == context.store_id,
            RuntimeBinding.bot_id == context.bot_id,
            RuntimeBinding.kind == kind,
            RuntimeBinding.key == key,
            RuntimeBinding.enabled.is_(True),
        )
        .order_by(RuntimeBinding.priority.desc(), RuntimeBinding.id)
    )


class InvalidStoredRun(RuntimeRejected):
    """Identify only deterministic decoding errors for a known, locked Run."""

    def __init__(self, run, code):
        """Keep the ORM record for quarantine; never include its contents in logs."""
        super().__init__(code)
        self.run = run


async def quarantine_run(db, run, code):
    """Stop one invalid record, with bounded redacted evidence, in its own transaction."""
    run.status, run.error_code = "failed", code
    run.lock_version += 1
    run.updated_at = security.clock()
    await system_event(db, run, kind="runtime", status="failed", error_code=code)


async def machine_for(db, run, *, initialize=False):
    """Load only the Run's pinned snapshot; no active binding or draft is consulted."""
    published = await db.scalar(
        select(PublishedWorkflow).where(
            PublishedWorkflow.id == run.publication_id,
            PublishedWorkflow.store_id == run.store_id,
        )
    )
    if published is None:
        raise InvalidStoredRun(run, "runtime_publication_missing")
    try:
        definition = Definition.model_validate(published.definition)
    except ValidationError:
        raise InvalidStoredRun(run, "runtime_stored_definition_invalid") from None
    if run.node_id not in {n.id for n in definition.nodes}:
        raise InvalidStoredRun(run, "runtime_stored_definition_invalid")
    if not isinstance(run.state, dict) or not isinstance(run.values, dict):
        raise InvalidStoredRun(run, "runtime_stored_state_invalid")
    store = await db.get(ShopStore, run.store_id)
    bot = await db.get(ShopBot, run.bot_id)
    # Personalization is private and optional; do not borrow another Bot's
    # identity or a name from the incoming message. Missing names render empty.
    if "customer_name" in run.state:
        customer_name = run.state["customer_name"]
    else:
        customer_name = await db.scalar(
            select(ShopStoreCustomer.display_name)
            .join(ShopIdentity, ShopIdentity.customer_id == ShopStoreCustomer.id)
            .where(
                ShopStoreCustomer.store_id == run.store_id,
                ShopStoreCustomer.id == run.customer_id,
                ShopIdentity.id == run.identity_id,
                ShopIdentity.store_id == run.store_id,
                ShopIdentity.bot_id == run.bot_id,
                ShopIdentity.platform == run.platform,
                ShopIdentity.platform_user_id == run.user_id,
            )
        )
    machine = Machine(
        definition,
        platform=run.platform,
        node_id=run.node_id,
        values=None if initialize else run.values,
        state=run.state,
        now=security.clock(),
        context={
            "context.store_name": store.name,
            "context.bot_name": bot.name,
            "context.customer_name": customer_name or "",
        },
    )
    # Pin the trusted name with the session, so later profile edits cannot
    # change the input shown at confirmation before the same Action runs.
    machine.state["customer_name"] = customer_name or ""
    machine.status = run.status
    return machine


async def persist(db, run, machine):
    """Atomically stage state, wait, action and outbound; caller owns the commit."""
    now = security.clock()
    output_count = await db.scalar(
        select(func.count())
        .select_from(WorkflowOutbox)
        .where(WorkflowOutbox.run_id == run.id)
    )
    if output_count + len(machine.outbound) > MAX_OUTBOX or (
        machine.action and output_count >= MAX_OUTBOX
    ):
        if machine.status != "cancelled":
            machine.status = "failed"
        machine.error = "runtime_outbound_budget"
        machine.outbound, machine.action, machine.wait = [], None, None
    run.node_id, run.status = machine.node_id, machine.status
    run.values, run.state = machine.values, machine.state
    run.error_code = machine.error
    run.updated_at = now
    run.lock_version += 1
    wait = await db.scalar(select(WorkflowWait).where(WorkflowWait.run_id == run.id))
    if machine.status in {"waiting_input", "waiting_timeout"}:
        seconds = (machine.wait or {}).get(
            "seconds", machine.definition.timeout_policy.seconds
        )
        if wait is None:
            wait = WorkflowWait(
                id=str(uuid4()),
                store_id=run.store_id,
                run_id=run.id,
                node_id=run.node_id,
                kind=(machine.wait or {}).get("kind", machine.nodes[run.node_id].type),
                deadline=min(
                    security.utc(run.expires_at), now + timedelta(seconds=seconds)
                ),
                epoch=machine.state.get("epoch", 0),
            )
            db.add(wait)
        elif wait.epoch != machine.state.get("epoch", 0):
            wait.node_id = run.node_id
            wait.kind = (machine.wait or {}).get(
                "kind", machine.nodes[run.node_id].type
            )
            wait.deadline = min(
                security.utc(run.expires_at), now + timedelta(seconds=seconds)
            )
            wait.epoch = machine.state.get("epoch", 0)
        wait.attempts = machine.state.get("attempts", 0)
        wait.resume_node = next(
            (
                e.target
                for e in machine.definition.edges
                if e.source == run.node_id and e.port == "next"
            ),
            None,
        )
        wait.timeout_node = next(
            (
                e.target
                for e in machine.definition.edges
                if e.source == run.node_id and e.port == "timeout"
            ),
            None,
        )
        wait.cancel_node = next(
            (
                e.target
                for e in machine.definition.edges
                if e.source == run.node_id and e.port == "cancel"
            ),
            None,
        )
    elif wait:
        await db.delete(wait)
    if machine.action:
        config = machine.action["config"]
        try:
            inputs = resolve_inputs(config, machine.values | machine.context)
            job = WorkflowActionJob(
                id=str(uuid4()),
                store_id=run.store_id,
                run_id=run.id,
                node_id=run.node_id,
                epoch=machine.state.get("epoch", 0),
                action_key=config["action_key"],
                action_version=config["action_version"],
                input=inputs,
            )
            db.add(job)
        except ActionRejected as error:
            run.status, run.error_code = "failed", error.code
    sequence = max(run.state.get("outbound_sequence", 0), output_count)
    for intent in machine.outbound:
        payload = dict(intent)
        buttons = []
        for button in payload.pop("buttons", []):
            if button.get("url"):
                buttons.append(
                    {
                        "label": button["label"],
                        "url": button["url"],
                        "row": button.get("row", 0),
                    }
                )
                continue
            token = "wf:" + secrets.token_urlsafe(24)
            db.add(
                WorkflowCallback(
                    id=str(uuid4()),
                    store_id=run.store_id,
                    token_hash=token_hash(token),
                    run_id=run.id,
                    bot_id=run.bot_id,
                    user_id=run.user_id,
                    node_id=intent["node_id"],
                    epoch=intent["epoch"],
                    value=button["value"],
                    expires_at=min(
                        security.utc(run.expires_at), now + timedelta(minutes=30)
                    ),
                )
            )
            buttons.append(
                {
                    "label": button["label"],
                    "callback_data": token,
                    "row": button.get("row", 0),
                    "command": button.get("command"),
                }
            )
        if payload.get("kind") == "legacy_menu":
            from services.shop_customer_menu import effective_menu

            rows = await effective_menu(
                db, bot_id=run.bot_id, platform=Platform(run.platform)
            )
            buttons = [
                {"label": b.label, "callback_data": b.callback_data, "row": i}
                for i, row in enumerate(rows)
                for b in row
            ]
            payload["kind"] = "text"
            payload["legacy_menu"] = True
        payload["buttons"] = buttons
        payload["interactive"] = (
            (bool(buttons) and not payload.get("legacy_menu", False))
            or payload.get("request_contact", False)
            or machine.nodes[intent["node_id"]].type.startswith("ask_")
        )
        sequence += 1
        outbox = WorkflowOutbox(
            id=str(uuid4()),
            store_id=run.store_id,
            run_id=run.id,
            bot_id=run.bot_id,
            node_id=intent["node_id"],
            epoch=intent["epoch"],
            sequence=sequence,
            payload=payload,
            available_at=now,
        )
        db.add(outbox)
        run.last_outbound_id = outbox.id
    run.state = machine.state | {"outbound_sequence": sequence}
    await db.flush()


async def event_capacity(db, run):
    """Check the durable event ceiling while the caller holds the Run lock."""
    return (
        await db.scalar(
            select(func.count())
            .select_from(WorkflowEvent)
            .where(WorkflowEvent.run_id == run.id)
        )
        < MAX_EVENTS
    )


async def action_budget(db, run):
    """Block new physical effects after either durable Run budget is exhausted."""
    if not await event_capacity(db, run):
        return "runtime_event_budget"
    count = await db.scalar(
        select(func.count())
        .select_from(WorkflowOutbox)
        .where(WorkflowOutbox.run_id == run.id)
    )
    return "runtime_outbound_budget" if count >= MAX_OUTBOX else None


async def control_input(db, context, event, *, run=None):
    """Keep authenticated cancellation/menu choices usable under input pressure."""
    if event.kind == "command":
        return event.text in {"/cancel", "/menu", "/restart"}
    if event.kind != "callback" or not event.callback.startswith("wf:"):
        return False
    if run is None:
        return False
    query = select(WorkflowCallback.value).where(
        WorkflowCallback.token_hash == token_hash(event.callback),
        WorkflowCallback.store_id == context.store_id,
        WorkflowCallback.bot_id == context.bot_id,
        WorkflowCallback.user_id == event.user_id,
        WorkflowCallback.value.in_(("cancel", "main_menu")),
        WorkflowCallback.consumed_at.is_(None),
        WorkflowCallback.expires_at > security.clock(),
    )
    if not isinstance(run.state, dict):
        return False
    query = query.where(
        WorkflowCallback.run_id == run.id,
        WorkflowCallback.node_id == run.node_id,
        WorkflowCallback.epoch == run.state.get("epoch", 0),
    )
    choice = await db.scalar(query)
    if choice == "cancel":
        # Confirm's authored decline may loop or take another transition. It
        # is a normal answer and cannot bypass the wait deadline or input caps.
        publication = await db.get(PublishedWorkflow, run.publication_id)
        return bool(
            publication
            and isinstance(publication.definition, dict)
            and not any(
                n.get("id") == run.node_id and n.get("type") == "confirm"
                for n in publication.definition.get("nodes", [])
                if isinstance(n, dict)
            )
        )
    return choice == "main_menu"


async def finish_input(db, inbox, result):
    """Commit the redacted exact input outcome with its durable processing state."""
    inbox.outcome = result
    await db.commit()
    return result


async def replay_input(db, inbox, *, count_duplicate=True):
    """Replay durable ownership without resuming work or retaining private input.

    The receiver and direct coordinator share this boundary. A real incoming
    redelivery increments its counter once; worker reconciliation never does.
    RETURNING reads the outcome from the same atomic update, avoiding a stale
    identity-map receipt if the worker completed while the receiver waited.
    """
    if count_duplicate:
        result = await db.execute(
            update(WorkflowInbox)
            .where(WorkflowInbox.id == inbox.id)
            .values(duplicate_count=WorkflowInbox.duplicate_count + 1)
            .returning(WorkflowInbox.status, WorkflowInbox.outcome)
        )
        status, outcome = result.one()
    else:
        status, outcome = inbox.status, inbox.outcome
    await db.commit()
    return (outcome or {"handled": True, "status": status}) | {"duplicate": True}


async def system_event(db, run, *, kind, status, error_code=None, summary=None):
    """Append safe correlated system metadata without exceeding stored history."""
    if not await event_capacity(db, run):
        run.status, run.error_code = "failed", "runtime_event_budget"
        return False
    db.add(
        WorkflowEvent(
            store_id=run.store_id,
            run_id=run.id,
            bot_id=run.bot_id,
            input_id="system:" + str(uuid4()),
            kind=kind,
            node_id=run.node_id,
            status=status,
            error_code=error_code,
            summary=summary or {},
            correlation_id=run.correlation_id,
        )
    )
    await db.flush()
    return True


async def reject_wait_input(
    db, run, inbox, event, machine, *, code, expired=False, target=None
):
    """Record a stale answer explicitly and keep it out of another question's values."""
    if expired:
        machine.timeout(target)
    else:
        machine.emit(
            "این پاسخ مربوط به مرحلهٔ قبلی بود؛ لطفاً به پرسش فعلی پاسخ دهید.",
            kind="text",
            buttons=[],
            notice=True,
        )
    db.add(
        WorkflowEvent(
            id=str(uuid4()),
            store_id=run.store_id,
            run_id=run.id,
            bot_id=run.bot_id,
            input_id=event.update_id,
            kind="timeout" if expired else event.kind,
            node_id=inbox.node_id or run.node_id,
            status="rejected",
            error_code=code,
            summary={"kind": event.kind, "characters": len(event.text)},
            correlation_id=run.correlation_id,
        )
    )
    await persist(db, run, machine)
    inbox.status, inbox.payload, inbox.error_code = "rejected", {}, code
    return await finish_input(
        db,
        inbox,
        {
            "handled": True,
            "status": machine.status if expired else "input_stale",
            "run_id": run.id,
        },
    )


async def _consume(
    db, context, event, *, slot, inbox, binding, principal, file_verifier=None
):
    """Advance one input under the customer slot and Run locks."""
    run = (
        await db.scalar(
            select(WorkflowRun)
            .where(
                WorkflowRun.id == slot.run_id, WorkflowRun.store_id == context.store_id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if slot.run_id
        else None
    )
    if run and (run.status in TERMINAL or run.status == "suspended"):
        run = None
    if (
        inbox.run_id is not None
        and (run is None or inbox.run_id != run.id)
        and binding is None
    ):
        inbox.status = "rejected"
        inbox.payload = {}
        inbox.error_code = "runtime_input_stale"
        return await finish_input(db, inbox, {"handled": True, "status": "input_stale"})
    if run is not None and event.kind == "command" and event.text == "/restart":
        candidate = await db.get(RuntimeBinding, run.binding_id)
        if (
            candidate
            and candidate.enabled
            and candidate.store_id == run.store_id
            and candidate.bot_id == run.bot_id
        ):
            binding = candidate

    if run and security.utc(run.expires_at) <= security.clock():
        run.status = "expired"
        run.error_code = "runtime_run_expired"
        await system_event(
            db, run, kind="timeout", status="expired", error_code="runtime_run_expired"
        )
        run = None
    control = await control_input(db, context, event, run=run)
    if run is not None and not await event_capacity(db, run):
        # Stop before interpreting another input, verifying a file, or creating
        # an Action. Controls retain their ability to terminate the session.
        run.status = "cancelled" if control else "failed"
        run.error_code = "runtime_event_budget"
        run.lock_version += 1
        run.updated_at = security.clock()
        inbox.status, inbox.payload, inbox.error_code = "rejected", {}, run.error_code
        return await finish_input(
            db, inbox, {"handled": True, "status": run.status, "run_id": run.id}
        )
    machine = None
    if run is not None and binding is None and not control:
        machine = await machine_for(db, run)
        if inbox.epoch is not None and (
            inbox.epoch != run.state.get("epoch", 0) or inbox.node_id != run.node_id
        ):
            return await reject_wait_input(
                db, run, inbox, event, machine, code="runtime_input_stale"
            )
        wait = await db.scalar(
            select(WorkflowWait).where(WorkflowWait.run_id == run.id).with_for_update()
        )
        if (
            wait is not None
            and wait.kind != "delay"
            and wait.epoch == run.state.get("epoch")
            and security.utc(inbox.created_at) >= security.utc(wait.deadline)
        ):
            return await reject_wait_input(
                db,
                run,
                inbox,
                event,
                machine,
                code="runtime_input_timeout",
                expired=True,
                target=wait.timeout_node,
            )
    if binding:
        if run:
            run.status = (
                "cancelled"
                if event.kind == "command" and event.text == "/restart"
                else "suspended"
            )
            run.updated_at = security.clock()
        if await db.scalar(
            select(RuntimeAudit.id).where(
                RuntimeAudit.action == "retire",
                RuntimeAudit.target_id == binding.publication_id,
            )
        ):
            inbox.status = "rejected"
            inbox.payload = {}
            return await finish_input(
                db, inbox, {"handled": True, "status": "publication_retired"}
            )
        publication = await db.get(PublishedWorkflow, binding.publication_id)
        run = WorkflowRun(
            id=str(uuid4()),
            store_id=context.store_id,
            bot_id=context.bot_id,
            customer_id=principal.customer_id,
            identity_id=principal.identity_id,
            user_id=event.user_id,
            chat_id=event.chat_id,
            platform=event.platform,
            workflow_id=publication.workflow_id,
            publication_id=publication.id,
            binding_id=binding.id,
            node_id=binding.node_id,
            status="active",
            values={},
            state={},
            lock_version=0,
            expires_at=security.clock() + timedelta(hours=24),
        )
        db.add(run)
        await db.flush()
        slot.run_id = run.id
        inbox.run_id = run.id
        machine = await machine_for(db, run, initialize=True)
        machine.advance()
    elif run is None:
        inbox.status = "rejected"
        inbox.payload = {}
        return await finish_input(
            db, inbox, {"handled": True, "status": "no_active_run"}
        )
    else:
        machine = machine or await machine_for(db, run)
        if run.status in {"waiting_action", "waiting_approval"} and not (
            event.kind == "command" and event.text in {"/cancel", "/menu"}
        ):
            # Retain valid input durably; the worker will consume it after the Action boundary.
            return await finish_input(
                db, inbox, {"handled": True, "status": "queued", "run_id": run.id}
            )
        if event.kind == "callback":
            callback = await db.scalar(
                select(WorkflowCallback)
                .where(
                    WorkflowCallback.token_hash == token_hash(event.callback),
                    WorkflowCallback.store_id == run.store_id,
                    WorkflowCallback.bot_id == run.bot_id,
                    WorkflowCallback.user_id == run.user_id,
                    WorkflowCallback.run_id == run.id,
                )
                .with_for_update()
            )
            if (
                callback is None
                or callback.consumed_at is not None
                or callback.node_id != run.node_id
                or callback.epoch != run.state.get("epoch", 0)
                or security.utc(callback.expires_at) <= security.clock()
            ):
                inbox.status = "rejected"
                inbox.payload = {}
                await system_event(
                    db,
                    run,
                    kind="callback",
                    status="rejected",
                    error_code="runtime_callback_expired",
                )
                return await finish_input(
                    db, inbox, {"handled": True, "status": "callback_expired"}
                )
            callback.consumed_at = security.clock()
            machine.choose(callback.value)
        elif event.kind == "command" and event.text in {
            "/cancel",
            "/menu",
            "/restart",
            "/back",
            "/skip",
        }:
            if event.text in {"/back", "/skip"}:
                machine.choose(event.text.removeprefix("/"))
            elif event.text == "/restart":
                machine.status = "cancelled"
            else:
                machine.cancel(menu=event.text == "/menu")
        elif machine.status == "waiting_input":
            if event.file is not None:
                expected = machine.nodes[run.node_id]
                if (
                    expected.type != "ask_" + event.file.kind
                    or event.file.size > expected.config.get("max_bytes", 20_000_000)
                ):
                    event = event.model_copy(update={"file": None, "text": ""})
                else:
                    if file_verifier is None:
                        from services.shop_runtime.adapters import verify_upload

                        file_verifier = verify_upload
                    try:
                        handle_id = await file_verifier(db, context, event, principal)
                        event = event.model_copy(update={"text": handle_id})
                    except (RuntimeRejected, ValueError):
                        event = event.model_copy(update={"text": "", "kind": "text"})
            machine.accept(
                event.text,
                kind=event.kind,
                contact_owner=event.contact_owner,
                user_id=event.user_id,
            )
        elif machine.status == "waiting_timeout":
            # Text received during a timer is never an answer to a future question.
            return await reject_wait_input(
                db, run, inbox, event, machine, code="runtime_input_stale"
            )
        else:
            # A non-input boundary remains queued until its timeout/action completes.
            return await finish_input(
                db, inbox, {"handled": True, "status": "queued", "run_id": run.id}
            )
    run.last_input_id = event.update_id
    db.add(
        WorkflowEvent(
            id=str(uuid4()),
            store_id=run.store_id,
            run_id=run.id,
            bot_id=run.bot_id,
            input_id=event.update_id,
            kind=event.kind,
            node_id=machine.node_id,
            status=machine.status,
            summary={
                "kind": event.kind,
                "characters": len(event.text),
                "has_file": event.file is not None,
            },
            correlation_id=run.correlation_id,
        )
    )
    await persist(db, run, machine)
    inbox.status = "processed"
    inbox.payload = {}
    return await finish_input(
        db, inbox, {"handled": True, "status": run.status, "run_id": run.id}
    )


async def handle(
    db,
    *,
    context,
    event: RuntimeInput,
    origin="customer",
    file_verifier=None,
    was_existing=True,
    resume_pending=False,
):
    """Accept Runtime-owned input before legacy receipt claims; return False for fallback."""
    if context.platform.value != event.platform:
        raise RuntimeRejected("runtime_platform_mismatch", 403)
    duplicate = await db.scalar(
        select(WorkflowInbox).where(
            WorkflowInbox.bot_id == context.bot_id,
            WorkflowInbox.input_id == event.update_id,
        )
    )
    if duplicate is not None and (not resume_pending or duplicate.status != "pending"):
        return await replay_input(db, duplicate, count_duplicate=not resume_pending)
    if not await enabled(db, context):
        return {"handled": False}
    principal = await customer_principal(
        db, verified_bot=context, platform_user_id=event.user_id
    )
    binding = await entry(db, context, event, origin=origin)
    if duplicate is not None:
        was_existing = duplicate.was_existing
    if (
        binding is not None
        and binding.eligibility == "existing_customer"
        and not was_existing
    ):
        return {
            "handled": binding.fallback == "ignore",
            "status": "eligibility_rejected",
        }
    existing = await db.scalar(
        select(RuntimeSlot).where(
            RuntimeSlot.bot_id == context.bot_id, RuntimeSlot.user_id == event.user_id
        )
    )
    active = (
        await db.get(WorkflowRun, existing.run_id)
        if existing and existing.run_id
        else None
    )
    has_active = (
        active is not None
        and active.status not in TERMINAL | {"suspended"}
        and security.utc(active.expires_at) > security.clock()
    )
    if binding is None and not has_active and not event.callback.startswith("wf:"):
        if duplicate is not None:
            duplicate.status = "rejected"
            duplicate.payload = {}
            duplicate.error_code = "runtime_run_not_waiting"
            return await finish_input(
                db, duplicate, {"handled": True, "status": "input_stale"}
            )
        return {"handled": False}
    slot = await _slot(db, context, event.user_id)
    # Preserve legacy navigation/payment callbacks and commands even during an active Run.
    navigation = (
        event.kind == "callback" and not event.callback.startswith(("wf:", "wfe:"))
    ) or (
        event.kind == "command"
        and (
            event.text.split()[0].removeprefix("/").split("@")[0] in RESERVED_COMMANDS
            or (
                binding is None
                and event.text.split()[0]
                not in {"/cancel", "/back", "/skip", "/menu", "/restart"}
            )
        )
    )
    if navigation:
        if slot.run_id:
            run = await db.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.id == slot.run_id)
                .with_for_update()
            )
            if run and run.status not in TERMINAL:
                run.status = "suspended"
                run.updated_at = security.clock()
        await db.commit()
        return {"handled": False}
    inbox = await db.scalar(
        select(WorkflowInbox)
        .where(
            WorkflowInbox.bot_id == context.bot_id,
            WorkflowInbox.input_id == event.update_id,
        )
        .with_for_update()
    )
    if inbox is None:
        control = await control_input(
            db, context, event, run=active if has_active else None
        )
        if not control:
            recent = await db.scalar(
                select(func.count())
                .select_from(WorkflowInbox)
                .where(
                    WorkflowInbox.bot_id == context.bot_id,
                    WorkflowInbox.user_id == event.user_id,
                    WorkflowInbox.created_at > security.clock() - timedelta(seconds=60),
                )
            )
            pending = await db.scalar(
                select(func.count())
                .select_from(WorkflowInbox)
                .where(
                    WorkflowInbox.bot_id == context.bot_id,
                    WorkflowInbox.user_id == event.user_id,
                    WorkflowInbox.status == "pending",
                )
            )
            if recent >= INPUTS_PER_MINUTE or pending >= MAX_PENDING_INPUTS:
                await db.commit()
                return {"handled": True, "status": "rate_limited"}
        inbox = WorkflowInbox(
            id=str(uuid4()),
            store_id=context.store_id,
            bot_id=context.bot_id,
            user_id=event.user_id,
            input_id=event.update_id,
            sequence=slot.next_sequence + 1,
            run_id=active.id if has_active and binding is None else None,
            node_id=active.node_id if has_active and binding is None else None,
            epoch=active.state.get("epoch", 0)
            if has_active and binding is None
            else None,
            created_at=security.clock(),
            was_existing=was_existing,
            payload=event.model_dump(mode="json"),
        )
        slot.next_sequence += 1
        db.add(inbox)
        await db.flush()
        # Durability precedes processing; after a process crash a worker owns this input.
        await db.commit()
        slot = await _slot(db, context, event.user_id)
    elif inbox.status != "pending" or not resume_pending:
        # Another receiver may have accepted this update while we waited on
        # the Slot. It is still one incoming duplicate, never a new execution.
        return await replay_input(db, inbox, count_duplicate=not resume_pending)
    if await db.scalar(
        select(WorkflowEvent.id).where(
            WorkflowEvent.bot_id == context.bot_id,
            WorkflowEvent.input_id == event.update_id,
        )
    ):
        inbox.status = "processed"
        inbox.payload = {}
        return await finish_input(
            db, inbox, inbox.outcome or {"handled": True, "duplicate": True}
        )
    earlier = await db.scalar(
        select(WorkflowInbox.id).where(
            WorkflowInbox.bot_id == context.bot_id,
            WorkflowInbox.user_id == event.user_id,
            WorkflowInbox.status == "pending",
            WorkflowInbox.sequence < inbox.sequence,
        )
    )
    if (
        earlier
        and binding is None
        and not (
            event.kind == "command" and event.text in {"/cancel", "/menu", "/restart"}
        )
    ):
        return await finish_input(db, inbox, {"handled": True, "status": "queued"})
    try:
        return await _consume(
            db,
            context,
            event,
            slot=slot,
            inbox=inbox,
            binding=binding,
            principal=principal,
            file_verifier=file_verifier,
        )
    except InvalidStoredRun as invalid:
        await quarantine_run(db, invalid.run, invalid.code)
        inbox.status, inbox.payload, inbox.error_code = "rejected", {}, invalid.code
        return await finish_input(
            db, inbox, {"handled": True, "status": "failed", "run_id": invalid.run.id}
        )
