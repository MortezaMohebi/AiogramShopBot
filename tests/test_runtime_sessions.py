"""Real database transitions pin versions and consume callback capabilities once."""

from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import func, select
from models.shop_staff import ShopStaff
from models.shop_workflow import ShopWorkflow
from models.shop_workflow_runtime import (
    PublishedWorkflow,
    RuntimeBinding,
    RuntimeGate,
    WorkflowRun,
    WorkflowOutbox,
)
from services import shop_admin_security as security
from services.shop_runtime.contracts import RuntimeInput
from services.shop_runtime.sessions import handle, enabled
from tests.test_action_security import buyer, db
from tests.test_runtime_interpreter import form


async def setup_runtime(db, principal, monkeypatch, definition=None):
    """Opt in only the test Store and Bot; no configured provider is contacted."""
    monkeypatch.setattr("config.SHOP_WORKFLOW_RUNTIME_ENABLED", True)
    staff = ShopStaff(
        username="runtime-test", password_hash="no-login", role="superadmin"
    )
    db.add(staff)
    await db.flush()
    workflow = ShopWorkflow(
        id=str(uuid4()),
        store_id=principal.store_id,
        key="wholesale",
        name="Form",
        created_by=staff.id,
    )
    db.add(workflow)
    await db.flush()
    published = PublishedWorkflow(
        id=str(uuid4()),
        store_id=principal.store_id,
        workflow_id=workflow.id,
        revision=1,
        definition=(definition or form()).model_dump(mode="json"),
        digest="a" * 64,
        published_by=staff.id,
    )
    db.add(published)
    await db.flush()
    db.add(
        RuntimeBinding(
            store_id=principal.store_id,
            bot_id=principal.bot_id,
            publication_id=published.id,
            workflow_id=workflow.id,
            kind="command",
            key="wholesale",
            node_id=next(
                n.id for n in (definition or form()).nodes if n.type == "start"
            ),
        )
    )
    for key, bot in [
        ("store:" + principal.store_id, None),
        ("bot:" + principal.bot_id, principal.bot_id),
    ]:
        db.add(
            RuntimeGate(
                store_id=principal.store_id, scope_key=key, bot_id=bot, enabled=True
            )
        )
    await db.commit()
    return published


def inbound(n, text, kind="text"):
    """Use literal authenticated update IDs and a private user/chat identity."""
    return RuntimeInput(
        platform="telegram",
        update_id=str(n),
        user_id=101,
        chat_id=101,
        kind=kind,
        text=text,
    )


@pytest.mark.asyncio
async def test_duplicate_inbound_does_not_repeat_transition_or_prompt(
    buyer, monkeypatch
):
    """A repeated transport update yields one Run, one answer and one next prompt."""
    db, p = buyer
    published = await setup_runtime(db, p, monkeypatch)
    first = await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    assert first["handled"]
    await handle(db, context=p.bot, event=inbound(2, "Alice"))
    again = await handle(db, context=p.bot, event=inbound(2, "Alice"))
    assert again["duplicate"]
    run = await db.scalar(select(WorkflowRun))
    assert run.node_id == "amount" and run.publication_id == published.id
    assert await db.scalar(select(func.count()).select_from(WorkflowRun)) == 1
    assert await db.scalar(select(func.count()).select_from(WorkflowOutbox)) == 2


@pytest.mark.asyncio
async def test_kill_switch_hands_inputs_to_legacy_without_deleting_run(
    buyer, monkeypatch
):
    """Disabling Runtime never consumes a customer's input or destroys pinned state."""
    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    gate = await db.scalar(
        select(RuntimeGate).where(RuntimeGate.scope_key == "bot:" + p.bot_id)
    )
    gate.killed = True
    await db.commit()
    result = await handle(db, context=p.bot, event=inbound(2, "Alice"))
    assert result["handled"] is False
    assert (await db.scalar(select(WorkflowRun))).node_id == "name"


@pytest.mark.asyncio
async def test_action_scope_uses_pinned_publication_after_draft_deleted(
    buyer, monkeypatch
):
    """Deleting an editable head cannot invalidate an already confirmed published Run."""
    from models.shop_workflow_runtime import WorkflowActionJob
    from services.shop_actions.contracts import Invocation
    from services.shop_actions.execution import invoke
    from services.shop_actions.approvals import issue_authorization
    from services.shop_actions.catalog import actions
    from services.shop_workflow_schema import Definition

    data = form().model_dump(mode="json")
    data["nodes"].append(
        {
            "id": "apply",
            "type": "action",
            "config": {
                "action_key": "wholesale.create_application",
                "action_version": "1.0.0",
                "input_mapping": {
                    "company": {"kind": "constant", "value": "QA Company"}
                },
                "output_mapping": {},
            },
        }
    )
    next(
        x for x in data["edges"] if x["source"] == "review" and x["port"] == "confirm"
    )["target"] = "apply"
    data["edges"].append(
        {"id": "success", "source": "apply", "port": "success", "target": "done"}
    )
    db, p = buyer
    published = await setup_runtime(db, p, monkeypatch, Definition.model_validate(data))
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    await handle(db, context=p.bot, event=inbound(2, "Alice"))
    await handle(db, context=p.bot, event=inbound(3, "12"))
    out = (
        await db.scalars(
            select(WorkflowOutbox).order_by(WorkflowOutbox.sequence.desc())
        )
    ).first()
    token = out.payload["buttons"][0]["callback_data"]
    await handle(
        db,
        context=p.bot,
        event=RuntimeInput(
            platform="telegram",
            update_id="4",
            user_id=101,
            chat_id=101,
            kind="callback",
            callback=token,
        ),
    )
    job = await db.scalar(select(WorkflowActionJob))
    run = await db.scalar(select(WorkflowRun))
    head = await db.get(ShopWorkflow, published.workflow_id)
    head.status = "deleted"
    await db.commit()
    invocation = Invocation(
        invocation_id=job.invocation_id,
        action_key=job.action_key,
        action_version=job.action_version,
        input=job.input,
        idempotency_key="runtime-" + job.id,
        workflow_id=run.workflow_id,
        workflow_revision=published.revision,
        workflow_run_id=run.id,
        node_id=job.node_id,
    )
    proof = await issue_authorization(
        db,
        subject=p,
        approver=p,
        invocation=invocation,
        purpose="customer_confirmation",
        registry=actions(),
    )
    result = await invoke(
        db, p, invocation.model_copy(update={"confirmation_receipt": proof})
    )
    assert result.status == "succeeded", result.model_dump()


@pytest.mark.asyncio
async def test_cancel_during_action_wait_is_immediate_not_lost_in_queue(
    buyer, monkeypatch
):
    """An unstarted pending Action cannot prevent the customer from cancelling."""
    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    run = await db.scalar(select(WorkflowRun))
    run.status = "waiting_action"
    await db.commit()
    result = await handle(db, context=p.bot, event=inbound(2, "/cancel", "command"))
    assert result["status"] == "cancelled" and run.status == "cancelled"


@pytest.mark.asyncio
async def test_terminal_slot_does_not_capture_future_legacy_text(buyer, monkeypatch):
    """A finished Workflow must release ordinary messages back to the old storefront."""
    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    await handle(db, context=p.bot, event=inbound(2, "/cancel", "command"))
    result = await handle(db, context=p.bot, event=inbound(3, "ordinary search"))
    assert result["handled"] is False


@pytest.mark.asyncio
async def test_restart_creates_new_run_and_keeps_previous_version_pinned(
    buyer, monkeypatch
):
    """Restart is a new invocation, while the cancelled Run keeps its original snapshot."""
    db, p = buyer
    first = await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    old = await db.scalar(select(WorkflowRun))
    result = await handle(db, context=p.bot, event=inbound(2, "/restart", "command"))
    assert result["run_id"] != old.id
    assert old.publication_id == first.id and old.status == "cancelled"
    assert await db.scalar(select(func.count()).select_from(WorkflowRun)) == 2


@pytest.mark.asyncio
async def test_existing_customer_entry_does_not_enroll_new_user_into_eligibility(
    buyer, monkeypatch
):
    """Enrollment for identity isolation does not grant a pre-existing-customer entry."""
    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    binding = await db.scalar(select(RuntimeBinding))
    binding.eligibility = "existing_customer"
    await db.commit()
    result = await handle(
        db, context=p.bot, event=inbound(1, "/wholesale", "command"), was_existing=False
    )
    assert result["handled"] is False
    assert await db.scalar(select(func.count()).select_from(WorkflowRun)) == 0


@pytest.mark.asyncio
async def test_bot_id_equal_to_store_id_cannot_reuse_store_opt_in(buyer, monkeypatch):
    """Store and Bot gates have separate authority even if their UUIDs collide."""
    from dataclasses import replace
    from models.shop_multibot import ShopBot

    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    db.add(
        ShopBot(
            id=p.store_id,
            store_id=p.store_id,
            slug="same-uuid",
            name="Same UUID",
            platform="telegram",
            status="active",
            runtime_owner="registry",
            credential_version=1,
        )
    )
    await db.commit()
    other = replace(p.bot, bot_id=p.store_id, status="active", runtime_owner="registry")
    assert await enabled(db, other) is False


@pytest.mark.asyncio
async def test_answer_after_wait_deadline_expires_without_advancing(buyer, monkeypatch):
    """A delayed scheduler cannot make a late answer valid again."""
    from models.shop_workflow_runtime import WorkflowWait

    db, p = buyer
    await setup_runtime(db, p, monkeypatch)
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))
    wait = await db.scalar(select(WorkflowWait))
    wait.deadline = security.clock() - timedelta(seconds=2)
    await db.commit()
    result = await handle(db, context=p.bot, event=inbound(2, "Late Name"))
    run = await db.scalar(select(WorkflowRun))
    assert run.status == "expired" and run.node_id == "name"
    assert "name" not in run.values


@pytest.mark.asyncio
async def test_two_queued_texts_cannot_answer_two_different_wait_generations(
    buyer, monkeypatch
):
    """Inputs accepted for one question cannot become unreviewed answers to the next."""
    from services.shop_runtime import sessions
    from services.shop_runtime.workers import inbox_once
    from tests.test_runtime_workers import factory
    from services.shop_workflow_schema import Definition
    from models.shop_workflow_runtime import WorkflowInbox

    data = form().model_dump(mode="json")
    data["nodes"][2] = {
        "id": "amount",
        "type": "ask_text",
        "config": {"prompt": "Company?", "variable": "amount"},
    }
    data["variables"][1] = {"name": "amount", "type": "string"}
    db, p = buyer
    await setup_runtime(db, p, monkeypatch, Definition.model_validate(data))
    await handle(db, context=p.bot, event=inbound(1, "/wholesale", "command"))

    async def crash(*args, **kwargs):
        raise RuntimeError("synthetic crash after inbox commit")

    with monkeypatch.context() as fault:
        fault.setattr(sessions, "_consume", crash)
        with pytest.raises(RuntimeError):
            await handle(db, context=p.bot, event=inbound(2, "Alice"))
    await db.rollback()
    result = await handle(db, context=p.bot, event=inbound(3, "Bob"))
    assert result["status"] == "queued"
    await inbox_once(factory(db))
    await inbox_once(factory(db))
    db.session.expire_all()
    run = await db.scalar(select(WorkflowRun))
    assert run.values == {"name": "Alice"} and run.node_id == "amount"
    rejected = await db.scalar(
        select(WorkflowInbox).where(WorkflowInbox.input_id == "3")
    )
    assert rejected.status == "rejected" and rejected.payload == {}
