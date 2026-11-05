"""Runtime administrative data remains behind real signed Store permissions."""

import pytest
from datetime import timedelta
from models.shop_staff import ShopStaff
from models.shop_admin_control import AdminSession
from services import shop_admin_security as security
from tests.test_workflow_api import studio
from tests.test_campaign_admin_store_scope import campaign_app, STORE_A


@pytest.mark.asyncio
async def test_reader_sees_global_off_but_cannot_enable_runtime(studio):
    """Draft editors cannot turn their content changes into customer-facing effects."""
    result = await studio.request("GET", "/workflow-runtime")
    assert result.status_code == 200, result.text
    assert result.json()["global_enabled"] is False
    assert result.json()["can_manage"] is False
    denied = await studio.request(
        "POST",
        "/workflow-runtime/gates",
        payload={
            "bot_id": None,
            "expected_version": 0,
            "enabled": True,
            "killed": False,
            "operation_id": "a0000000-0000-4000-8000-000000000001",
        },
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_cross_store_run_is_not_disclosed(studio):
    """An opaque Run ID never acts as authority to read another Store's state."""
    missing = await studio.request(
        "GET", "/workflow-runtime/runs/a0000000-0000-4000-8000-000000000002"
    )
    assert missing.status_code == 404, missing.text


@pytest.fixture
def runtime_manager(studio, monkeypatch):
    """Provide an enrolled operator and an actually revocable signed device session."""
    from cryptography.fernet import Fernet

    monkeypatch.setenv("SHOP_SECURITY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    actor = studio.db.get(ShopStaff, 7)
    actor.role = "superadmin"
    profile = security.profile_for(studio.db, 7)
    profile.mfa_secret = security.cipher().encrypt(b"JBSWY3DPEHPK3PXP").decode()
    studio.db.commit()
    return studio


@pytest.mark.asyncio
async def test_gate_requires_recent_auth_and_exact_retry_is_safe(runtime_manager):
    """A stale session cannot enable effects; a lost successful response is replayable."""
    from sqlalchemy import select, func
    from models.shop_workflow_runtime import RuntimeAudit, RuntimeGate

    app = runtime_manager
    session = app.db.get(AdminSession, app.session_id)
    session.reauthenticated_at = security.clock() - timedelta(minutes=6)
    app.db.commit()
    body = {
        "bot_id": None,
        "expected_version": 0,
        "enabled": True,
        "killed": False,
        "operation_id": "a0000000-0000-4000-8000-000000000003",
    }
    denied = await app.request("POST", "/workflow-runtime/gates", payload=body)
    assert (
        denied.status_code == 403
        and denied.json()["detail"] == "reauthentication_required"
    )
    assert app.db.scalar(select(func.count()).select_from(RuntimeGate)) == 0
    session.reauthenticated_at = security.clock()
    app.db.commit()
    saved = await app.request("POST", "/workflow-runtime/gates", payload=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["operation_id"] == body["operation_id"]
    replay = await app.request("POST", "/workflow-runtime/gates", payload=body)
    assert replay.status_code == 200 and replay.json()["replayed"]
    assert replay.json()["operation_id"] == body["operation_id"]
    assert replay.json()["scope_key"] == "store:" + STORE_A
    assert app.db.scalar(select(func.count()).select_from(RuntimeAudit)) == 1


@pytest.mark.asyncio
async def test_gate_cannot_select_foreign_bot(runtime_manager):
    """Manager membership in several Stores still requires an explicit Store switch."""
    from tests.test_campaign_admin_store_scope import BOT_B

    denied = await runtime_manager.request(
        "POST",
        "/workflow-runtime/gates",
        payload={
            "bot_id": BOT_B,
            "expected_version": 0,
            "enabled": True,
            "killed": False,
            "operation_id": "a0000000-0000-4000-8000-000000000004",
        },
    )
    assert denied.status_code == 404, denied.text


async def delivery_fixture(app, *, outcome, definition=None):
    """Stage a synthetic failed provider attempt in the same real scoped database."""
    from uuid import uuid4
    from models.shop_workflow import ShopWorkflow
    from models.shop_workflow_runtime import (
        PublishedWorkflow,
        RuntimeBinding,
        WorkflowRun,
        WorkflowOutbox,
        WorkflowDeliveryAttempt,
    )
    from models.shop_content import ShopIdentity
    from models.shop_store_commerce import ShopStoreCustomer
    from tests.test_campaign_admin_store_scope import BOT_A
    from tests.test_workflow_schema import document

    workflow = ShopWorkflow(
        id=str(uuid4()), store_id=STORE_A, key="test-send", name="Send"
    )
    app.db.add(workflow)
    app.db.flush()
    publication = PublishedWorkflow(
        id=str(uuid4()),
        store_id=STORE_A,
        workflow_id=workflow.id,
        revision=1,
        definition=definition or document(),
        digest="f" * 64,
        published_by=7,
    )
    app.db.add(publication)
    app.db.flush()
    binding = RuntimeBinding(
        id=str(uuid4()),
        store_id=STORE_A,
        bot_id=BOT_A,
        publication_id=publication.id,
        workflow_id=workflow.id,
        kind="command",
        key="delivery",
        node_id="s",
    )
    customer = ShopStoreCustomer(store_id=STORE_A, display_name="private-display")
    app.db.add_all([binding, customer])
    app.db.flush()
    identity = ShopIdentity(
        store_id=STORE_A,
        customer_id=customer.id,
        bot_id=BOT_A,
        platform="telegram",
        platform_user_id=909,
    )
    app.db.add(identity)
    app.db.flush()
    run = WorkflowRun(
        id=str(uuid4()),
        store_id=STORE_A,
        bot_id=BOT_A,
        customer_id=customer.id,
        identity_id=identity.id,
        user_id=909,
        chat_id=909,
        platform="telegram",
        workflow_id=workflow.id,
        publication_id=publication.id,
        binding_id=binding.id,
        node_id="s",
        status="waiting_input",
        values={"name": "private-personal-value"},
        state={"epoch": 1},
        expires_at=security.clock() + timedelta(hours=1),
    )
    app.db.add(run)
    app.db.flush()
    outbox = WorkflowOutbox(
        id=str(uuid4()),
        store_id=STORE_A,
        bot_id=BOT_A,
        run_id=run.id,
        node_id="s",
        epoch=1,
        sequence=1,
        payload={"kind": "text", "text": "private-contact-value", "buttons": []},
        status="dead_letter",
        attempts=1,
        error_code="runtime_delivery_unknown"
        if outcome == "uncertain"
        else "runtime_provider_rejected",
    )
    app.db.add(outbox)
    app.db.flush()
    app.db.add(
        WorkflowDeliveryAttempt(
            store_id=STORE_A, outbox_id=outbox.id, number=1, outcome=outcome
        )
    )
    app.db.commit()
    return outbox, run


@pytest.mark.asyncio
async def test_unknown_delivery_is_never_retried_and_trace_hides_private_data(
    runtime_manager,
):
    """Fresh manager approval cannot turn an ambiguous send into a duplicate message."""
    app = runtime_manager
    outbox, run = await delivery_fixture(app, outcome="uncertain")
    denied = await app.request(
        "POST",
        f"/workflow-runtime/outbox/{outbox.id}/retry",
        payload={
            "expected_attempts": 1,
            "operation_id": "a0000000-0000-4000-8000-000000000005",
        },
    )
    assert (
        denied.status_code == 409
        and denied.json()["detail"] == "runtime_delivery_replay_forbidden"
    )
    assert outbox.status == "dead_letter"
    metadata = await app.request("GET", f"/workflow-runtime/runs/{run.id}")
    assert metadata.status_code == 200, metadata.text
    assert "private-" not in metadata.text
    assert metadata.json()["outbox"][0]["can_retry"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("competing_run", [False, True])
async def test_resume_serializes_the_customer_slot(runtime_manager, monkeypatch, competing_run):
    """Recovery restores the routing pointer only if it cannot create two active Runs."""
    from uuid import uuid4
    from models.shop_multibot import ShopBot
    from models.shop_workflow_runtime import RuntimeGate, RuntimeSlot, WorkflowRun
    from tests.test_campaign_admin_store_scope import BOT_A
    from tests.test_runtime_interpreter import form

    app = runtime_manager
    monkeypatch.setattr("config.SHOP_WORKFLOW_RUNTIME_ENABLED", True)
    app.db.get(ShopBot, BOT_A).credential_version = 1
    _, run = await delivery_fixture(app, outcome="rejected", definition=form().model_dump(mode="json"))
    run.status, run.node_id, run.values = "suspended", "name", {}
    run.state = {"epoch": 1, "outbound_sequence": 1}
    other = None
    if competing_run:
        other = WorkflowRun(
            id=str(uuid4()), store_id=run.store_id, bot_id=run.bot_id,
            customer_id=run.customer_id, identity_id=run.identity_id,
            user_id=run.user_id, chat_id=run.chat_id, platform=run.platform,
            workflow_id=run.workflow_id, publication_id=run.publication_id,
            binding_id=run.binding_id, node_id="name", status="waiting_input",
            values={}, state={"epoch": 1}, expires_at=run.expires_at)
        app.db.add(other)
        app.db.flush()
    slot = RuntimeSlot(store_id=STORE_A, bot_id=BOT_A, user_id=run.user_id,
                       run_id=other.id if other else None)
    app.db.add_all([
        slot,
        RuntimeGate(store_id=STORE_A, scope_key="store:" + STORE_A, enabled=True),
        RuntimeGate(store_id=STORE_A, bot_id=BOT_A, scope_key="bot:" + BOT_A, enabled=True),
    ])
    app.db.commit()
    result = await app.request("POST", f"/workflow-runtime/runs/{run.id}/recover", payload={
        "operation": "resume", "expected_version": run.lock_version,
        "operation_id": str(uuid4()),
    })
    if competing_run:
        assert result.status_code == 409, result.text
        assert result.json()["detail"] == "runtime_session_conflict"
        app.db.refresh(run)
        assert run.status == "suspended" and slot.run_id == other.id
    else:
        assert result.status_code == 200, result.text
        app.db.refresh(slot)
        assert slot.run_id == run.id
        assert result.json()["status"] == "waiting_input"


@pytest.mark.asyncio
async def test_overview_has_bounded_private_free_store_metrics(runtime_manager):
    """Operational SQL groups contain no identities, private values or payloads."""
    from models.shop_workflow_runtime import WorkflowInbox, WorkflowOutbox

    app = runtime_manager
    output, run = await delivery_fixture(app, outcome="rejected")
    run.status = "waiting_input"
    run.state = {"node_transitions": 7, "validation_errors": 2}
    run.values = {"secret": "must-never-appear"}
    output.status, output.attempts = "dead_letter", 3
    app.db.add(WorkflowOutbox(
        store_id=run.store_id, bot_id=run.bot_id, run_id=run.id,
        node_id=run.node_id, epoch=1, sequence=2, payload={},
        status="cancelled", attempts=0, error_code="runtime_prompt_obsolete",
    ))
    app.db.add(WorkflowInbox(
        store_id=run.store_id, bot_id=run.bot_id, user_id=run.user_id,
        input_id="metrics", sequence=1, payload={}, status="processed", duplicate_count=4,
    ))
    app.db.commit()
    response = await app.request("GET", "/workflow-runtime")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metrics"]["runs_started"] == 1
    assert body["metrics"]["node_transitions"] == 7
    assert body["metrics"]["input_validation_errors"] == 2
    assert body["metrics"]["duplicate_events"] == 4
    assert body["metrics"]["outbox_retries"] == 2
    assert body["metrics"]["outbox_deadletters"] == 1
    assert body["metrics"]["delivery_failures_by_platform"] == {"telegram": 1}
    assert body["active_groups"] == [{
        "workflow_id": run.workflow_id, "publication_id": run.publication_id,
        "revision": 1, "active_runs": 1,
    }]
    assert body["active_groups_has_more"] is False
    assert body["metrics_scope"]["window"] == "all_retained_history"
    assert "must-never-appear" not in response.text
    assert "user_id" not in response.text and "chat_id" not in response.text


@pytest.mark.asyncio
async def test_overview_timeouts_include_action_timeout_once(runtime_manager):
    """SQL timeout totals cover Action deadlines and wait/Run expiry separately."""
    from uuid import uuid4
    from models.shop_workflow_runtime import WorkflowEvent

    app = runtime_manager
    _, run = await delivery_fixture(app, outcome="rejected")
    for kind, error in [("action", "action_timeout"), ("timeout", "action_timeout"), ("action", "action_busy")]:
        app.db.add(WorkflowEvent(
            store_id=run.store_id, run_id=run.id, bot_id=run.bot_id,
            input_id=str(uuid4()), kind=kind, node_id=run.node_id,
            status="failed", error_code=error, summary={}, correlation_id=run.correlation_id,
        ))
    app.db.commit()
    response = await app.request("GET", "/workflow-runtime")
    assert response.status_code == 200, response.text
    assert response.json()["metrics"]["timeouts"] == 2
    assert response.json()["metrics"]["action_failures"] == 2
