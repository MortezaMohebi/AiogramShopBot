"""Approve exact native intents with WPMCP proofs and real domain receipts."""

from __future__ import annotations

import importlib
import time
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import func, select

from models.shop_workflow import ShopWorkflow, ShopWorkflowRevision
from models.shop_workflow_runtime import PublishedWorkflow, RuntimeAudit
from services import shop_admin_security as security
from services.shop_mcp.contracts import McpRejected
from services.shop_mcp.proofs import ProofConfiguration
from tests.test_campaign_admin_store_scope import BOT_A, STORE_A, STORE_B
from tests.test_campaign_admin_store_scope import campaign_app as campaign_app
from tests.test_mcp_authority import (
    APPROVAL_PRIVATE,
    AUDIENCE,
    ISSUER,
    PRIVATE,
    signed,
)
from tests.test_mcp_workflows import client, creation
from tests.test_workflow_schema import document


def implementation(name):
    """Call production services; absent implementation is an observed RED."""
    try:
        return importlib.import_module("services.shop_mcp." + name)
    except ModuleNotFoundError:
        pytest.fail("The native approval intent service is missing.")


def configuration():
    """Pin separate public keys; neither a caller nor a tool chooses trust."""
    return ProofConfiguration(
        issuer=ISSUER,
        audience=AUDIENCE,
        delegation_keys={"wpmcp-delegation-test": PRIVATE.public_key()},
        approval_keys={"wpmcp-approval-test": APPROVAL_PRIVATE.public_key()},
    )


def approved(intent, principal, *, key=APPROVAL_PRIVATE, **overrides):
    """Sign only immutable intent identity, never a replacement effect payload."""
    identity = principal.delegation
    instant = int(time.time())
    claims = {
        "v": 1,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": identity.sub,
        "client_id": identity.client_id,
        "tenant_id": identity.tenant_id,
        "workspace_id": identity.workspace_id,
        "connection_id": identity.connection_id,
        "grant_id": identity.grant_id,
        "grant_version": identity.grant_version,
        "operation_id": intent["operation_id"],
        "approval_id": str(uuid5(NAMESPACE_URL, intent["intent_id"])),
        "intent_id": intent["intent_id"],
        "kind": intent["kind"],
        "store_id": STORE_A,
        "intent_sha256": intent["intent_sha256"],
        "iat": instant,
        "exp": instant + 90,
        "jti": str(uuid4()),
        **overrides,
    }
    return signed(
        claims,
        header={
            "alg": "EdDSA",
            "typ": "wpmcp-approval+jwt",
            "kid": "wpmcp-approval-test",
        },
        key=key,
    )


async def commit(db, principal, intent, token=None):
    """Use the exact native commit service with pinned operator configuration."""
    return await implementation("execution").commit(
        db,
        principal,
        intent_id=intent["intent_id"],
        approval_proof=token or approved(intent, principal),
        configuration=configuration(),
    )


async def publication(app):
    """Create a real inert draft and exact publication intent, with no send."""
    call, db, principal = await client(app)
    created = await call(
        "workflow.create_draft", **creation(name="پرسش مشتری")
    )
    await call(
        "workflow.replace_definition",
        workflow_id=created["id"],
        operation_id=str(uuid4()),
        expected_revision=1,
        definition=document(),
    )
    request = {
        "store_id": STORE_A,
        "operation_id": str(uuid4()),
        "workflow_id": created["id"],
        "expected_revision": 2,
        "revision": 2,
        "bindings": [
            {
                "bot_id": BOT_A,
                "kind": "start",
                "key": "default",
                "node_id": "s",
            }
        ],
    }
    intent = await implementation("preparations").prepare(
        db,
        principal,
        "workflow.publish",
        request,
    )
    return call, db, principal, request, intent


@pytest.mark.asyncio
async def test_sensitive_change_set_is_applied_only_by_its_exact_gateway_proof(
    campaign_app,
):
    """The sole human authority is WPMCP; a proof never replaces reviewed data."""
    call, db, principal = await client(campaign_app)
    request = creation(template="wholesale_application")
    staged = await call("workflow.create_draft", **request)
    intent = await implementation("preparations").prepare(
        db,
        principal,
        "changes.apply",
        {
            "store_id": STORE_A,
            "operation_id": request["operation_id"],
            "change_set_id": staged["id"],
            "expected_version": 1,
        },
    )
    assert campaign_app.db.get(ShopWorkflow, request["id"]) is None
    with pytest.raises(McpRejected):
        await commit(
            db, principal, intent, approved(intent, principal, key=PRIVATE)
        )
    result = await commit(db, principal, intent)
    assert result["id"] == request["id"] and result["revision"] == 1
    assert result["native_receipt"] == request["operation_id"]
    replay = await commit(db, principal, intent)
    assert replay["revision"] == 1
    assert (
        campaign_app.db.scalar(
            select(func.count()).select_from(ShopWorkflowRevision)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_approval_identity_hash_expiry_and_purpose_cannot_be_substituted(
    campaign_app,
):
    """Even correctly signed foreign or altered approval claims have no effect."""
    _, db, principal, _, intent = await publication(campaign_app)
    for changed in (
        {"sub": "another-owner"},
        {"client_id": "another-client"},
        {"tenant_id": str(uuid4())},
        {"workspace_id": str(uuid4())},
        {"connection_id": str(uuid4())},
        {"grant_id": str(uuid4())},
        {"grant_version": 2},
        {"operation_id": str(uuid4())},
        {"intent_id": str(uuid4())},
        {"kind": "runtime.gate"},
        {"store_id": STORE_B},
        {"intent_sha256": "0" * 64},
        {"aud": "urn:bot-workflows:foreign"},
        {"exp": int(time.time()) - 1},
        {"approved": True},
    ):
        with pytest.raises(McpRejected):
            await commit(
                db, principal, intent, approved(intent, principal, **changed)
            )
    assert (
        campaign_app.db.scalar(
            select(func.count()).select_from(PublishedWorkflow)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_publish_and_rollback_use_pinned_real_publication_receipts(
    campaign_app,
):
    """Exact approved activation is idempotent and rollback is another review."""
    call, db, principal, request, intent = await publication(campaign_app)
    replay = await implementation("preparations").prepare(
        db,
        principal,
        "workflow.publish",
        request,
    )
    assert replay["intent_sha256"] == intent["intent_sha256"]
    first = await commit(db, principal, intent)
    assert (
        first["publication_id"]
        == (await commit(db, principal, intent))["publication_id"]
    )
    assert (
        campaign_app.db.scalar(
            select(func.count()).select_from(PublishedWorkflow)
        )
        == 1
    )
    await call(
        "workflow.update_metadata",
        workflow_id=request["workflow_id"],
        expected_revision=2,
        operation_id=str(uuid4()),
        name="New head",
    )
    rollback = await implementation("preparations").prepare(
        db,
        principal,
        "workflow.rollback",
        request
        | {
            "operation_id": str(uuid4()),
            "expected_revision": 3,
            "publication_id": first["publication_id"],
        },
    )
    assert rollback["kind"] == "workflow.rollback"
    assert (await commit(db, principal, rollback))["publication_id"] == first[
        "publication_id"
    ]


@pytest.mark.asyncio
async def test_changed_head_or_binding_requires_a_new_review(campaign_app):
    """A fresh signature cannot approve a proposal whose native base changed."""
    call, db, principal, request, intent = await publication(campaign_app)
    await call(
        "workflow.update_metadata",
        workflow_id=request["workflow_id"],
        expected_revision=2,
        operation_id=str(uuid4()),
        name="Other edit",
    )
    with pytest.raises(McpRejected) as conflict:
        await commit(db, principal, intent)
    assert conflict.value.status == 409
    assert (
        campaign_app.db.scalar(
            select(func.count()).select_from(PublishedWorkflow)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_gateway_proof_does_not_override_native_grant_revocation(
    campaign_app,
):
    """Native revocation fences effect admission even after a gateway decision."""
    _, db, principal, _, intent = await publication(campaign_app)
    principal.grant.revoked_at = security.clock()
    principal.grant.version += 1
    campaign_app.db.commit()
    with pytest.raises(McpRejected):
        await commit(db, principal, intent)
    assert (
        campaign_app.db.scalar(
            select(func.count()).select_from(PublishedWorkflow)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_gate_commit_crash_reconciles_runtime_audit_without_repeating(
    campaign_app, monkeypatch
):
    """Finalization can fail after a domain commit; its durable receipt wins."""
    _, db, principal = await client(campaign_app)
    request = {
        "store_id": STORE_A,
        "operation_id": str(uuid4()),
        "bot_id": None,
        "expected_version": 0,
        "enabled": True,
        "killed": False,
    }
    intent = await implementation("preparations").prepare(
        db,
        principal,
        "runtime.gate",
        request,
    )
    execution = implementation("execution")
    original = execution.finalize

    async def interrupted(*_args, **_kwargs):
        raise RuntimeError("simulated process loss after domain commit")

    monkeypatch.setattr(execution, "finalize", interrupted)
    with pytest.raises(RuntimeError):
        await commit(db, principal, intent)
    await db.rollback()
    monkeypatch.setattr(execution, "finalize", original)
    recovered = await execution.receipt(
        db,
        principal,
        operation_id=request["operation_id"],
    )
    assert recovered["status"] == "succeeded"
    assert recovered["result"]["native_receipt"] == request["operation_id"]
    assert (await commit(db, principal, intent))["native_receipt"] == request[
        "operation_id"
    ]
    assert (
        campaign_app.db.scalar(select(func.count()).select_from(RuntimeAudit))
        == 1
    )


@pytest.mark.asyncio
async def test_unknown_delivery_is_not_even_prepared_for_approval(
    campaign_app,
):
    """An approval cannot make an uncertain send safe to repeat."""
    from tests.test_runtime_api import delivery_fixture

    outbox, _ = await delivery_fixture(campaign_app, outcome="uncertain")
    _, db, principal = await client(campaign_app)
    with pytest.raises(McpRejected):
        await implementation("preparations").prepare(
            db,
            principal,
            "runtime.delivery_retry",
            {
                "store_id": STORE_A,
                "operation_id": str(uuid4()),
                "outbox_id": outbox.id,
                "expected_attempts": 1,
            },
        )


@pytest.mark.asyncio
async def test_sensitive_review_requires_current_native_manager_and_expires(
    campaign_app, monkeypatch
):
    """A gateway workspace role cannot replace native Store authority."""
    from models.shop_staff_store import ShopStaffStoreAccess

    _, db, principal, _, intent = await publication(campaign_app)
    member = campaign_app.db.get(ShopStaffStoreAccess, (7, STORE_A))
    member.access_level = "editor"
    campaign_app.db.commit()
    with pytest.raises(McpRejected):
        await implementation("preparations").review(
            db,
            principal,
            intent_id=intent["intent_id"],
        )
    member.access_level = "manager"
    campaign_app.db.commit()
    instant = security.clock()
    monkeypatch.setattr(
        security, "clock", lambda: instant + timedelta(minutes=6)
    )
    with pytest.raises(McpRejected):
        await commit(db, principal, intent)


def test_delegation_signing_key_cannot_also_be_an_approval_key():
    """A request-signing key must not be configured as human decision authority."""
    with pytest.raises(ValueError):
        ProofConfiguration(
            issuer=ISSUER,
            audience=AUDIENCE,
            delegation_keys={"request": PRIVATE.public_key()},
            approval_keys={"approval": PRIVATE.public_key()},
        )


@pytest.mark.asyncio
async def test_review_hash_covers_the_exact_rendered_utf8_bytes(campaign_app):
    """Preserve native float/Unicode serialization instead of rehashing JS data."""
    import base64
    import hashlib
    import json

    _, db, principal, _, intent = await publication(campaign_app)
    result = await implementation("preparations").review(
        db,
        principal,
        intent_id=intent["intent_id"],
    )
    raw = base64.b64decode(result["artifact_base64"], validate=True)
    assert hashlib.sha256(raw).hexdigest() == result["intent_sha256"]
    assert "پرسش مشتری" in raw.decode()
    assert b'"x":0.0' in raw
    assert json.loads(raw)["request"]["workflow_id"]


@pytest.mark.asyncio
async def test_bot_dependency_change_requires_new_publication_review(
    campaign_app,
):
    """Keeping the graph revision is insufficient when reviewed Bot policy changes."""
    from models.shop_multibot import ShopBot

    _, db, principal, _, intent = await publication(campaign_app)
    campaign_app.db.get(ShopBot, BOT_A).version += 1
    campaign_app.db.commit()
    with pytest.raises(McpRejected) as rejected:
        await commit(db, principal, intent)
    assert rejected.value.code == "mcp_dependency_changed"
    assert (
        campaign_app.db.scalar(
            select(func.count()).select_from(PublishedWorkflow)
        )
        == 0
    )


def test_python_accepts_the_exact_gateway_approval_wire_fixture(monkeypatch):
    """Check the same signed bytes and raw artifact hash in both languages."""
    import hashlib
    import json
    from datetime import datetime, timezone
    from pathlib import Path
    from types import SimpleNamespace

    from services.shop_mcp.approval_proofs import verify
    from services.shop_mcp.contracts import Delegation
    from tests.test_mcp_authority import delegation_claims

    fixture = json.loads(
        (
            Path(__file__).parents[1] / "contracts/wpmcp/approval-v1.json"
        ).read_text()
    )
    claims = fixture["claims"]
    principal = SimpleNamespace(
        delegation=Delegation.model_validate(
            delegation_claims(),
        )
    )
    row = SimpleNamespace(
        id=claims["operation_id"],
        kind=claims["kind"],
        store_id=claims["store_id"],
        grant_version=claims["grant_version"],
        evidence_sha256=claims["intent_sha256"],
    )
    monkeypatch.setattr(
        security,
        "clock",
        lambda: datetime.fromtimestamp(
            fixture["now"],
            timezone.utc,
        ),
    )
    assert (
        hashlib.sha256(fixture["artifact_utf8"].encode()).hexdigest()
        == claims["intent_sha256"]
    )
    assert (
        verify(
            fixture["token"],
            row=row,
            principal=principal,
            configuration=configuration(),
        ).approval_id
        == claims["approval_id"]
    )


@pytest.mark.asyncio
async def test_accepted_intent_evidence_cannot_be_edited_or_deleted(
    campaign_app,
):
    """Execution state may advance; exact reviewed evidence is append-only."""
    from models.shop_mcp import McpIntent

    _, _, _, _, intent = await publication(campaign_app)
    row = campaign_app.db.get(McpIntent, intent["intent_id"])
    row.evidence_json = "{}"
    with pytest.raises(ValueError, match="immutable"):
        campaign_app.db.flush()
    campaign_app.db.rollback()


@pytest.mark.asyncio
async def test_private_review_commit_and_receipt_are_signed_without_local_approve_api(
    campaign_app,
):
    """Run the exact private protocol and preserve nonce/domain retry separation."""
    import hashlib
    import json

    import httpx

    from dashboard import mcp_api as api
    from services.shop_mcp.settings import McpSettings

    _, db, principal, _, intent = await publication(campaign_app)
    campaign_app.app.state.mcp_settings = McpSettings(
        enabled=True,
        proofs=configuration(),
    )

    async def database():
        yield db

    campaign_app.app.dependency_overrides[api.database] = database
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=campaign_app.app),
        base_url="http://offline.test",
    ) as http:

        async def post(path, payload):
            body = json.dumps(payload, separators=(",", ":")).encode()
            target = "/internal/mcp/v1" + path
            instant = int(time.time())
            claims = principal.delegation.model_dump() | {
                "target": target,
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "jti": str(uuid4()),
                "iat": instant,
                "exp": instant + 45,
            }
            return await http.post(
                target,
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-wpmcp-delegation": signed(claims),
                },
            )

        review = await post(
            "/intents/review", {"intent_id": intent["intent_id"]}
        )
        assert review.status_code == 200, review.text
        assert review.json()["result"]["artifact_base64"]
        absent = await post(
            "/approve", {"intent_id": intent["intent_id"], "approved": True}
        )
        assert absent.status_code == 404
        accepted = await post(
            "/commit",
            {
                "intent_id": intent["intent_id"],
                "approval_proof": approved(intent, principal),
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert (
            accepted.json()["result"]["native_receipt"]
            == intent["operation_id"]
        )
        observed = await post(
            "/receipts/get", {"operation_id": intent["operation_id"]}
        )
        assert observed.status_code == 200
        assert observed.json()["result"]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_typed_public_preparation_replays_and_observes_automatic_execution(
    campaign_app,
):
    """A model can prepare and inspect; it has no commit or approve tool."""
    call, db, principal, request, _ = await publication(campaign_app)
    arguments = {
        key: value for key, value in request.items() if key != "store_id"
    }
    arguments["operation_id"] = str(uuid4())
    result = await call("workflow.prepare_publish", **arguments)
    assert result["requires_approval"] is True
    assert (await call("workflow.prepare_publish", **arguments))[
        "intent_id"
    ] == result["intent_id"]
    assert (
        await call(
            "workflow.get_operation_status",
            operation_id=arguments["operation_id"],
        )
    )["status"] == "prepared"
    await commit(db, principal, result)
    status = await call(
        "workflow.get_operation_status", operation_id=arguments["operation_id"]
    )
    assert status["status"] == "succeeded"
    with pytest.raises(McpRejected):
        await call("workflow.commit", intent_id=result["intent_id"])


@pytest.mark.asyncio
async def test_approved_run_cancel_uses_real_recovery_without_customer_input(
    campaign_app,
):
    """Cancellation is separately reviewed and keeps a stable recovery audit."""
    from models.shop_workflow_runtime import RuntimeSlot
    from tests.test_runtime_api import delivery_fixture

    _, run = await delivery_fixture(campaign_app, outcome="rejected")
    campaign_app.db.add(
        RuntimeSlot(
            store_id=STORE_A,
            bot_id=BOT_A,
            user_id=run.user_id,
            run_id=run.id,
        )
    )
    campaign_app.db.commit()
    _, db, principal = await client(campaign_app)
    result = await implementation("preparations").prepare(
        db,
        principal,
        "runtime.cancel",
        {
            "store_id": STORE_A,
            "operation_id": str(uuid4()),
            "run_id": run.id,
            "expected_version": run.lock_version,
        },
    )
    done = await commit(db, principal, result)
    assert done["status"] == "cancelled"
    assert (await commit(db, principal, result))["status"] == "cancelled"
    assert "private-personal-value" not in str(done)


@pytest.mark.asyncio
async def test_one_gateway_decision_cannot_be_reused_for_two_native_operations(
    campaign_app,
):
    """An approval reference belongs to one immutable operation, even if resigned."""
    _, db, principal = await client(campaign_app)
    prepare = implementation("preparations").prepare
    request = {
        "store_id": STORE_A,
        "expected_version": 0,
        "enabled": True,
        "killed": False,
    }
    first = await prepare(
        db,
        principal,
        "runtime.gate",
        request
        | {
            "operation_id": str(uuid4()),
            "bot_id": None,
        },
    )
    second = await prepare(
        db,
        principal,
        "runtime.gate",
        request
        | {
            "operation_id": str(uuid4()),
            "bot_id": BOT_A,
        },
    )
    decision = str(uuid4())
    await commit(
        db, principal, first, approved(first, principal, approval_id=decision)
    )
    with pytest.raises(McpRejected):
        await commit(
            db,
            principal,
            second,
            approved(second, principal, approval_id=decision),
        )
    assert (
        campaign_app.db.scalar(select(func.count()).select_from(RuntimeAudit))
        == 1
    )


@pytest.mark.asyncio
async def test_cached_bot_policy_cannot_hide_a_native_dependency_change(
    campaign_app,
):
    """Read live policy even when the ORM has previously loaded its older version."""
    from sqlalchemy import update

    from models.shop_store_commerce import ShopBotCommercePolicy

    policy = ShopBotCommercePolicy(bot_id=BOT_A, cart_enabled=True)
    campaign_app.db.add(policy)
    campaign_app.db.commit()
    _, db, principal, _, intent = await publication(campaign_app)
    campaign_app.db.execute(
        update(ShopBotCommercePolicy)
        .where(
            ShopBotCommercePolicy.bot_id == BOT_A,
        )
        .values(cart_enabled=False)
        .execution_options(synchronize_session=False)
    )
    campaign_app.db.commit()
    assert (
        policy.cart_enabled is True
    )  # The real ORM cache is deliberately old.
    with pytest.raises(McpRejected) as rejected:
        await commit(db, principal, intent)
    assert rejected.value.code == "mcp_dependency_changed"
