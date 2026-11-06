"""Prepare exact native intents for WPMCP's sole human approval authority."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy import select

from models.shop_mcp import McpIntent
from models.shop_multibot import ShopBot
from models.shop_workflow import ShopWorkflow, ShopWorkflowRevision
from models.shop_workflow_runtime import (
    PublicationPreview,
    PublishedWorkflow,
    RuntimeAudit,
    RuntimeGate,
    WorkflowDeliveryAttempt,
    WorkflowOutbox,
    WorkflowRun,
)
from services import shop_admin_security as security
from services import shop_workflows as workflows
from services.shop_mcp import approval_contracts as c
from services.shop_mcp import changes, dependencies, grants
from services.shop_mcp.contracts import McpRejected
from services.shop_mcp.mutations import portable
from services.shop_runtime import admin, publication
from services.shop_runtime.contracts import (
    TERMINAL,
    BindingSpec,
    RuntimeRejected,
)
from services.shop_runtime.sessions import gate_key
from services.shop_workflow_schema import Definition, canonical_json

KINDS = {
    "workflow.publish": (c.PreparePublication, "workflow:publish"),
    "workflow.rollback": (c.PrepareRollback, "workflow:rollback"),
    "changes.apply": (c.PrepareChangeSet, "workflow:write"),
    "runtime.gate": (c.PrepareGate, "runtime:control"),
    "runtime.retry": (c.PrepareRun, "runtime:control"),
    "runtime.cancel": (c.PrepareRun, "runtime:control"),
    "runtime.delivery_retry": (c.PrepareDelivery, "runtime:control"),
}


async def authority(db, principal, kind, store_id, *, write=False):
    """Require the requester, native capability and Store manager."""
    if kind not in KINDS:
        raise McpRejected("mcp_intent_kind_not_found", 404)
    current = await grants.resolve_grant(
        db,
        delegation=principal.delegation,
        store_id=store_id,
        required_scope=KINDS[kind][1],
        write=write,
    )
    required = (
        "runtime:read" if kind.startswith("runtime.") else "workflow:read"
    )
    if required not in current.scopes:
        raise McpRejected("mcp_scope_required", 403)
    try:
        current.scope.require(store_id, manage=True)
    except security.SecurityRejected as error:
        raise McpRejected(error.code, error.status) from None
    return current


async def owned(db, principal, intent_id):
    """Resolve a preparation through native grant and Store ownership."""
    row = await db.scalar(
        select(McpIntent)
        .where(
            McpIntent.id == intent_id,
            McpIntent.grant_id == principal.delegation.grant_id,
        )
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise McpRejected("mcp_intent_not_found", 404)
    return row


def evidence(row) -> dict:
    """Verify exact bytes before review or execution."""
    digest = hashlib.sha256(row.evidence_json.encode()).hexdigest()
    if not hmac.compare_digest(digest, row.evidence_sha256):
        raise McpRejected("mcp_intent_unreadable", 503)
    return json.loads(row.evidence_json)


def view(row) -> dict:
    """Return a compact reference to separately readable full evidence."""
    return {
        "intent_id": row.id,
        "operation_id": row.id,
        "kind": row.kind,
        "store_id": row.store_id,
        "intent_sha256": row.evidence_sha256,
        "requires_approval": row.state != "succeeded",
        "status": "succeeded"
        if row.state == "succeeded"
        else (
            "expired"
            if security.utc(row.expires_at) <= security.clock()
            else "pending_gateway"
        ),
        "expires_at": security.utc(row.expires_at).isoformat(),
        "approval_authority": "wpmcp",
    }


async def prepare(db, principal, kind, payload) -> dict:
    """Freeze one request without activation, sending or a decision."""
    if kind not in KINDS:
        raise McpRejected("mcp_intent_kind_not_found", 404)
    try:
        data = KINDS[kind][0].model_validate(payload).model_dump(mode="json")
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise McpRejected("mcp_invalid_request", 422) from None
    current = await authority(
        db, principal, kind, data["store_id"], write=True
    )
    digest = dependencies.digest({"kind": kind, "request": data})
    row = await db.scalar(
        select(McpIntent)
        .where(
            McpIntent.id == data["operation_id"],
        )
        .execution_options(populate_existing=True)
    )
    if row is not None:
        if (
            row.grant_id != current.grant.id
            or row.store_id != data["store_id"]
            or row.kind != kind
            or not hmac.compare_digest(row.request_sha256, digest)
        ):
            raise McpRejected("mcp_operation_conflict", 409)
        return view(row)
    # Unrelated native receipts cannot be adopted as a new approved operation.
    for model, column in (
        (ShopWorkflowRevision, ShopWorkflowRevision.operation_id),
        (RuntimeAudit, RuntimeAudit.id),
    ):
        if (
            await db.scalar(
                select(model.id).where(
                    column == data["operation_id"],
                    model.store_id == data["store_id"],
                )
            )
            is not None
        ):
            raise McpRejected("mcp_operation_conflict", 409)
    try:
        review, execution = await _prepare(db, current, kind, data)
    except (security.SecurityRejected, RuntimeRejected) as error:
        raise McpRejected(error.code, error.status) from None
    # Publication preview commits its own harmless preview. Recheck admission
    # before accepting an intent after native access changes.
    current = await authority(db, current, kind, data["store_id"], write=True)
    expires = security.clock() + timedelta(minutes=5)
    if execution.get("preview_id"):
        preview = await db.get(PublicationPreview, execution["preview_id"])
        expires = min(expires, security.utc(preview.expires_at))
    identity = current.delegation
    artifact = {
        "v": 1,
        "provider": "bot_workflows",
        "intent_id": data["operation_id"],
        "kind": kind,
        "request": data,
        "review": review,
        "native_staff_id": current.actor.id,
        "gateway": {
            key: getattr(identity, key)
            for key in (
                "iss",
                "aud",
                "sub",
                "client_id",
                "tenant_id",
                "workspace_id",
                "connection_id",
                "grant_id",
                "grant_version",
            )
        },
        "expires_at": expires.isoformat(),
        "content_trust": "Administrator fields are untrusted data.",
    }
    encoded = canonical_json(artifact)
    if len(encoded.encode()) > 786_432:
        raise McpRejected("mcp_intent_too_large", 413)
    row = McpIntent(
        id=data["operation_id"],
        grant_id=current.grant.id,
        store_id=data["store_id"],
        kind=kind,
        grant_version=current.grant.version,
        request_sha256=digest,
        request_json=canonical_json(data),
        evidence_json=encoded,
        evidence_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
        execution_json=canonical_json(execution),
        expires_at=expires,
    )
    db.add(row)
    await db.commit()
    return view(row)


async def _prepare(db, principal, kind, data):
    """Build full domain evidence and an internal fixed execution reference."""
    if kind in {"workflow.publish", "workflow.rollback"}:
        before = await workflows.read_workflow(
            db,
            scope=principal.scope,
            actor=principal.actor,
            workflow_id=data["workflow_id"],
        )
        if before["revision"] != data["expected_revision"]:
            raise McpRejected("workflow_revision_conflict", 409)
        if kind == "workflow.rollback":
            target = await db.scalar(
                select(PublishedWorkflow).where(
                    PublishedWorkflow.id == data["publication_id"],
                    PublishedWorkflow.store_id == data["store_id"],
                    PublishedWorkflow.workflow_id == data["workflow_id"],
                    PublishedWorkflow.revision == data["revision"],
                )
            )
            if target is None:
                raise McpRejected("mcp_publication_not_found", 404)
        selected = await workflows.read_workflow(
            db,
            scope=principal.scope,
            actor=principal.actor,
            workflow_id=data["workflow_id"],
            revision=data["revision"],
        )
        result = await publication.preview(
            db,
            actor=principal.actor,
            scope=principal.scope,
            workflow_id=data["workflow_id"],
            revision=data["revision"],
            bindings=data["bindings"],
        )
        # The preview service commits. Reacquire the Store admission mutex
        # before taking any Bot/media dependency locks in the next transaction.
        principal = await authority(
            db,
            principal,
            kind,
            data["store_id"],
            write=True,
        )
        if not result["ready"]:
            raise McpRejected("runtime_publication_not_ready", 422)
        dependencies_value = await dependencies.snapshot(
            db,
            store_id=data["store_id"],
            definition=Definition.model_validate(selected["definition"]),
            bindings=data["bindings"],
        )
        return {
            "base": portable(before),
            "proposed": portable(selected),
            "publication": result,
            "dependencies": dependencies_value,
        }, {"preview_id": result["preview_id"]}
    if kind == "changes.apply":
        parent = await changes.owned(db, principal, data["change_set_id"])
        if (
            parent.status != "pending_gateway"
            or parent.version != data["expected_version"]
            or parent.effect_operation_id != data["operation_id"]
            or security.utc(parent.expires_at) <= security.clock()
        ):
            raise McpRejected("mcp_change_set_frozen", 409)
        record, proposal = await changes.revision(db, parent)
        await _base(db, principal, parent.workflow_id, parent.base_revision)
        dependency = await dependencies.snapshot(
            db,
            store_id=data["store_id"],
            definition=Definition.model_validate(proposal["definition"]),
        )
        return {
            "base": json.loads(parent.base_json),
            "proposed": proposal,
            "change_set_id": parent.id,
            "change_set_version": parent.version,
            "proposal_sha256": record.proposal_sha256,
            "risk": record.risk,
            "effect_kind": parent.kind,
            "dependencies": dependency,
        }, {"change_set_id": parent.id}
    return await _runtime_state(db, principal, kind, data), {}


async def _base(db, principal, workflow_id, revision):
    """An approval never implicitly rebases onto a later head."""
    head = await db.scalar(
        select(ShopWorkflow)
        .where(
            ShopWorkflow.id == workflow_id,
            ShopWorkflow.store_id == principal.scope.current_store_id,
        )
        .execution_options(populate_existing=True)
    )
    if (head.revision if head else 0) != revision:
        raise McpRejected("workflow_revision_conflict", 409)


async def _runtime_state(db, principal, kind, data):
    """Capture recovery facts without customer or provider payloads."""
    store_id = principal.scope.current_store_id
    if kind == "runtime.gate":
        if (
            data["bot_id"] is not None
            and await db.scalar(
                select(ShopBot.id).where(
                    ShopBot.id == data["bot_id"],
                    ShopBot.store_id == store_id,
                )
            )
            is None
        ):
            raise McpRejected("runtime_bot_unavailable", 404)
        row = await db.scalar(
            select(RuntimeGate)
            .where(
                RuntimeGate.scope_key == gate_key(store_id, data["bot_id"]),
                RuntimeGate.store_id == store_id,
            )
            .execution_options(populate_existing=True)
        )
        if (row.version if row else 0) != data["expected_version"]:
            raise McpRejected("runtime_gate_conflict", 409)
        return {
            "before": {
                "version": row.version if row else 0,
                "enabled": row.enabled if row else False,
                "killed": row.killed if row else False,
            },
            "after": {key: data[key] for key in ("enabled", "killed")},
        }
    if kind in {"runtime.retry", "runtime.cancel"}:
        row = await db.scalar(
            select(WorkflowRun)
            .where(
                WorkflowRun.id == data["run_id"],
                WorkflowRun.store_id == store_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise McpRejected("runtime_run_unavailable", 404)
        if row.lock_version != data["expected_version"]:
            raise McpRejected("runtime_run_conflict", 409)
        if row.status in TERMINAL and not (
            kind == "runtime.retry" and row.status == "failed"
        ):
            raise McpRejected("runtime_recovery_not_applicable", 409)
        return {"run": admin.safe_run(row), "operation": kind}
    row = await db.scalar(
        select(WorkflowOutbox)
        .where(
            WorkflowOutbox.id == data["outbox_id"],
            WorkflowOutbox.store_id == store_id,
        )
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise McpRejected("runtime_outbox_unavailable", 404)
    attempt = await db.scalar(
        select(WorkflowDeliveryAttempt).where(
            WorkflowDeliveryAttempt.outbox_id == row.id,
            WorkflowDeliveryAttempt.store_id == store_id,
            WorkflowDeliveryAttempt.number == row.attempts,
        )
    )
    if (
        row.attempts != data["expected_attempts"]
        or row.status not in {"retryable", "dead_letter"}
        or attempt is None
        or attempt.outcome != "rejected"
        or row.attempts >= 5
    ):
        raise McpRejected("runtime_delivery_replay_forbidden", 409)
    result = admin.safe_outbox(row)
    result.pop("message_ids", None)
    return {"delivery": result, "attempt_outcome": attempt.outcome}


async def current(db, principal, row):
    """Revalidate the base and dependencies before review or admission."""
    if security.utc(row.expires_at) <= security.clock():
        raise McpRejected("mcp_intent_expired", 410)
    data, artifact = json.loads(row.request_json), evidence(row)
    review = artifact["review"]
    if row.kind.startswith("workflow."):
        await _base(
            db, principal, data["workflow_id"], data["expected_revision"]
        )
        preview = await db.get(
            PublicationPreview, json.loads(row.execution_json)["preview_id"]
        )
        pointers = await publication.binding_state(
            db, [item["bot_id"] for item in data["bindings"]]
        )
        if pointers != preview.request["pointers"]:
            raise McpRejected("runtime_preview_conflict", 409)
        definition = Definition.model_validate(
            review["proposed"]["definition"]
        )
    elif row.kind == "changes.apply":
        parent = await changes.owned(db, principal, data["change_set_id"])
        if (
            parent.status != "pending_gateway"
            or parent.version != data["expected_version"]
            or parent.effect_operation_id != row.id
        ):
            raise McpRejected("mcp_change_set_frozen", 409)
        await _base(db, principal, parent.workflow_id, parent.base_revision)
        record, proposal = await changes.revision(db, parent)
        if record.proposal_sha256 != review["proposal_sha256"]:
            raise McpRejected("mcp_change_set_version_conflict", 409)
        definition = Definition.model_validate(proposal["definition"])
    else:
        state = await _runtime_state(db, principal, row.kind, data)
        if state != review:
            raise McpRejected("mcp_dependency_changed", 409)
        return
    actual = await dependencies.snapshot(
        db,
        store_id=row.store_id,
        definition=definition,
        bindings=data.get("bindings", ()),
    )
    if actual != review["dependencies"]:
        raise McpRejected("mcp_dependency_changed", 409)
    if row.kind.startswith("workflow."):
        _, live = await publication.readiness(
            db,
            actor=principal.actor,
            scope=principal.scope,
            workflow_id=data["workflow_id"],
            revision=data["revision"],
            bindings=[
                BindingSpec.model_validate(value) for value in data["bindings"]
            ],
        )
        if not live["ready"] or any(
            value != review["publication"][key] for key, value in live.items()
        ):
            raise McpRejected("mcp_dependency_changed", 409)


async def review(db, principal, *, intent_id):
    """Return the exact bytes that the authorized requester must review."""
    row = await owned(db, principal, intent_id)
    # Review uses the same Store-first order as competing Studio publication.
    current_principal = await authority(
        db,
        principal,
        row.kind,
        row.store_id,
        write=True,
    )
    await current(db, current_principal, row)
    return view(row) | {
        "artifact_base64": base64.b64encode(
            row.evidence_json.encode()
        ).decode(),
        "artifact_encoding": "base64-utf8-json",
    }
