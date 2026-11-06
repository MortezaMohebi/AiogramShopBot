"""Versioned proposals over existing Workflow persistence."""

from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from datetime import timedelta

from sqlalchemy import select

from models.shop_mcp import McpChangeSet, McpChangeSetRevision
from models.shop_workflow import ShopWorkflowRevision
from services import shop_admin_security as security
from services import shop_workflows as workflows
from services.shop_mcp.contracts import McpRejected
from services.shop_mcp.patches import apply_patches
from services.shop_mcp.risk import mutation_risk
from services.shop_workflow_schema import (
    Definition,
    EditorLayout,
    canonical_json,
)


async def owned(db, principal, identity: str) -> McpChangeSet:
    """Filter both grant and Store even when a row is identity-map cached."""
    row = await db.scalar(
        select(McpChangeSet)
        .where(
            McpChangeSet.id == identity,
            McpChangeSet.grant_id == principal.grant.id,
            McpChangeSet.store_id == principal.scope.current_store_id,
        )
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise McpRejected("mcp_change_set_not_found", 404)
    return row


async def revision(db, row, version=None):
    """Verify immutable proposal evidence before rendering or applying it."""
    record = await db.get(
        McpChangeSetRevision,
        (row.id, version or row.version),
    )
    if record is None:
        raise McpRejected("mcp_change_set_version_not_found", 404)
    digest = hashlib.sha256(record.proposal_json.encode()).hexdigest()
    if not hmac.compare_digest(digest, record.proposal_sha256):
        raise McpRejected("mcp_change_set_unreadable", 503)
    return record, json.loads(record.proposal_json)


async def _effect_receipt(db, row):
    """Read an immutable receipt without changing request state."""
    if row.effect_operation_id is None:
        return None
    return await db.scalar(
        select(ShopWorkflowRevision).where(
            ShopWorkflowRevision.store_id == row.store_id,
            ShopWorkflowRevision.workflow_id == row.workflow_id,
            ShopWorkflowRevision.operation_id == row.effect_operation_id,
        )
    )


async def _reconcile(db, row):
    """A domain receipt wins over a stale pending/cancelled projection."""
    if row.effect_operation_id is None or row.status == "applied":
        return
    record = await _effect_receipt(db, row)
    if record is not None:
        row.status, row.applied_revision = "applied", record.revision
        await db.flush()


async def get(db, principal, identity: str, version=None) -> dict:
    """Return exact content history and separately identify current state."""
    row = await owned(db, principal, identity)
    receipt = await _effect_receipt(db, row)
    record, proposal = await revision(db, row, version)
    return {
        "id": row.id,
        "store_id": row.store_id,
        "workflow_id": row.workflow_id,
        "base_revision": row.base_revision,
        "version": record.version,
        "current_version": row.version,
        "status": "applied" if receipt else row.status,
        "kind": row.kind,
        "risk": record.risk,
        "sha256": record.proposal_sha256,
        "proposal": proposal,
        "base": json.loads(row.base_json),
        "expires_at": security.utc(row.expires_at).isoformat(),
        "applied_revision": receipt.revision
        if receipt
        else row.applied_revision,
    }


def edit(base: dict, arguments: dict) -> dict:
    """Apply one typed request to a copy without touching stored evidence."""
    proposed = deepcopy(base)
    if arguments.get("definition") is not None:
        proposed["definition"] = arguments["definition"]
        if arguments.get("layout") is None:
            ids = {node["id"] for node in proposed["definition"]["nodes"]}
            proposed["layout"]["positions"] = {
                key: value
                for key, value in proposed["layout"]["positions"].items()
                if key in ids
            }
    if arguments.get("layout") is not None:
        proposed["layout"] = arguments["layout"]
    if arguments.get("patches") is not None:
        patched = apply_patches(
            proposed["definition"],
            proposed["layout"],
            arguments["patches"],
        )
        proposed["definition"] = patched.definition.model_dump(mode="json")
        proposed["layout"] = patched.layout.model_dump(mode="json")
    for field in ("name", "description"):
        if arguments.get(field) is not None:
            proposed[field] = arguments[field]
    if arguments.get("assignment") is not None:
        proposed["definition"]["assignment"] = arguments["assignment"]
    return proposed


async def _append(db, row, proposal, operation_id):
    """Check native bindings and append a hashed proposal version."""
    await workflows._check_document(
        db,
        row.store_id,
        Definition.model_validate(proposal["definition"]),
        EditorLayout.model_validate(proposal["layout"]),
    )
    encoded = canonical_json(proposal)
    if len(encoded.encode()) > 262_144:
        raise McpRejected("mcp_request_too_large", 413)
    db.add(
        McpChangeSetRevision(
            change_set_id=row.id,
            version=row.version,
            operation_id=operation_id,
            proposal_json=encoded,
            proposal_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
            risk=mutation_risk(
                json.loads(row.base_json), proposal, kind=row.kind
            ),
        )
    )
    await db.flush()


async def create(
    db,
    principal,
    *,
    identity,
    workflow_id,
    base,
    proposal,
    operation_id,
    kind="save",
    pending=False,
) -> dict:
    """Persist a prospective creation or edit without a domain mutation."""
    if await db.get(McpChangeSet, identity) is not None:
        raise McpRejected("mcp_change_set_exists", 409)
    row = McpChangeSet(
        id=identity,
        store_id=principal.scope.current_store_id,
        grant_id=principal.grant.id,
        workflow_id=workflow_id,
        base_revision=base.get("revision", 0),
        kind=kind,
        version=1,
        status="pending_gateway" if pending else "draft",
        base_json=canonical_json(base),
        effect_operation_id=operation_id if pending else None,
        expires_at=security.clock() + timedelta(hours=24),
    )
    db.add(row)
    await db.flush()
    await _append(db, row, proposal, operation_id)
    await db.commit()
    result = await get(db, principal, row.id)
    return result | (
        {
            "requires_approval": True,
            "change_set_id": row.id,
        }
        if pending
        else {}
    )


def _editable(row, expected_version):
    """Only unfrozen current unexpired proposals can be changed or applied."""
    if row.version != expected_version:
        raise McpRejected("mcp_change_set_version_conflict", 409)
    if row.status != "draft":
        raise McpRejected("mcp_change_set_frozen", 409)
    if security.utc(row.expires_at) <= security.clock():
        raise McpRejected("mcp_change_set_expired", 410)


async def update(db, principal, arguments) -> dict:
    """Version incremental edits while keeping the source revision fixed."""
    row = await owned(db, principal, arguments["change_set_id"])
    await _reconcile(db, row)
    _editable(row, arguments["expected_version"])
    _, previous = await revision(db, row)
    proposed = edit(previous, arguments)
    row.version += 1
    await _append(db, row, proposed, arguments["operation_id"])
    await db.commit()
    return await get(db, principal, row.id)


async def effect(db, principal, row, proposal, operation_id):
    """Invoke an existing domain service with a stable idempotency receipt."""
    common = {"scope": principal.scope, "actor": principal.actor}
    row.effect_operation_id = operation_id
    await db.flush()
    if row.kind in {"create", "duplicate"}:
        result = await workflows._create_draft(
            db,
            **common,
            payload={
                "id": row.workflow_id,
                "operation_id": operation_id,
                "key": proposal["key"],
                "name": proposal["name"],
                "description": proposal["description"],
                "definition": proposal["definition"],
                "layout": proposal["layout"],
            },
            definition=Definition.model_validate(proposal["definition"]),
            layout=EditorLayout.model_validate(proposal["layout"]),
            action=row.kind,
        )
    elif row.kind == "restore":
        result = await workflows.restore_revision(
            db,
            **common,
            workflow_id=row.workflow_id,
            payload={
                "operation_id": operation_id,
                "expected_revision": row.base_revision,
                "revision": proposal["source_revision"],
            },
        )
    elif row.kind == "archive":
        result = await workflows.set_status(
            db,
            **common,
            workflow_id=row.workflow_id,
            status="archived",
            payload={
                "operation_id": operation_id,
                "expected_revision": row.base_revision,
            },
        )
    else:
        result = await workflows.save_draft(
            db,
            **common,
            workflow_id=row.workflow_id,
            payload={
                "operation_id": operation_id,
                "expected_revision": row.base_revision,
                **{
                    key: proposal[key]
                    for key in (
                        "name",
                        "description",
                        "definition",
                        "layout",
                    )
                },
            },
        )
    row.status, row.applied_revision = "applied", result["revision"]
    await db.commit()
    return result


async def apply(db, principal, arguments) -> dict:
    """Low-risk proposals save now; sensitive ones freeze for WPMCP review."""
    row = await owned(db, principal, arguments["change_set_id"])
    await _reconcile(db, row)
    _editable(row, arguments["expected_version"])
    record, proposal = await revision(db, row)
    if row.base_revision:
        head = await workflows._head(
            db,
            principal.scope,
            principal.actor,
            row.workflow_id,
            write=True,
        )
        if head.revision != row.base_revision:
            raise McpRejected("workflow_revision_conflict", 409)
    if record.risk != "low":
        row.status = "pending_gateway"
        row.effect_operation_id = arguments["operation_id"]
        await db.commit()
        return await get(db, principal, row.id) | {
            "requires_approval": True,
            "change_set_id": row.id,
        }
    return await effect(
        db,
        principal,
        row,
        proposal,
        arguments["operation_id"],
    )


async def cancel(db, principal, arguments) -> dict:
    """Cancel only an unexecuted proposal, never hide a committed receipt."""
    row = await owned(db, principal, arguments["change_set_id"])
    await _reconcile(db, row)
    if row.version != arguments["expected_version"]:
        raise McpRejected("mcp_change_set_version_conflict", 409)
    if row.status not in {"draft", "pending_gateway", "cancelled"}:
        raise McpRejected("mcp_change_set_frozen", 409)
    row.status = "cancelled"
    await db.commit()
    return await get(db, principal, row.id)
