"""Admit exact WPMCP-approved intents and reconcile native domain receipts."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from models.shop_mcp import McpIntent
from models.shop_workflow import ShopWorkflowRevision
from models.shop_workflow_runtime import PublicationPreview, RuntimeAudit
from services import shop_admin_security as security
from services import shop_workflows as workflows
from services.shop_mcp import approval_proofs, changes, grants, preparations
from services.shop_mcp.contracts import McpRejected
from services.shop_runtime import admin, publication
from services.shop_runtime.contracts import RuntimeRejected
from services.shop_runtime.sessions import gate_key
from services.shop_store_context import bind_context
from services.shop_workflow_schema import canonical_json


async def commit(db, principal, *, intent_id, approval_proof, configuration):
    """Serialize native admission and use only the stored reviewed effect."""
    try:
        initial = await preparations.owned(db, principal, intent_id)
        current = await preparations.authority(
            db,
            principal,
            initial.kind,
            initial.store_id,
            write=True,
        )
        row = await db.scalar(
            select(McpIntent)
            .where(
                McpIntent.id == intent_id,
                McpIntent.grant_id == current.delegation.grant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise McpRejected("mcp_intent_not_found", 404)
        approval = approval_proofs.verify(
            approval_proof,
            row=row,
            principal=current,
            configuration=configuration,
        )
        if row.approval_id not in (None, approval.approval_id):
            raise McpRejected("mcp_approval_conflict", 409)
        with bind_context(current.scope):
            result = await reconcile(db, current, row)
            if result is not None:
                return await finalize(db, row, result)
            await preparations.current(db, current, row)
            row.state, row.approval_id = "admitted", approval.approval_id
            try:
                await db.flush()
            except IntegrityError:
                # The unique decision binding is checked before entering any
                # domain service, including concurrent operations in Stores.
                raise McpRejected("mcp_approval_conflict", 409) from None
            # Authority SHARE locks remain held through the domain commit.
            # Native revocation before admission prevents this point; after
            # commit, finalization only reports the already completed effect.
            result = await _execute(db, current, row)
            return await finalize(db, row, _receipt(row, result))
    except (security.SecurityRejected, RuntimeRejected) as error:
        await db.rollback()
        raise McpRejected(error.code, error.status) from None
    except Exception:
        await db.rollback()
        raise


def _receipt(row, result):
    """Bind a safe receipt to the preparation and gateway decision."""
    operational_fields = {
        "id",
        "store_id",
        "workflow_id",
        "revision",
        "head_revision",
        "operation_id",
        "publication_id",
        "preview_id",
        "replayed",
        "status",
        "scope_key",
        "enabled",
        "killed",
        "version",
        "target_id",
        "lock_version",
        "error_code",
    }
    return {
        key: value
        for key, value in result.items()
        if key in operational_fields
    } | {
        "native_receipt": row.id,
        "intent_id": row.id,
        "intent_sha256": row.evidence_sha256,
    }


async def _execute(db, principal, row):
    """Map an intent kind to a domain service without new input."""
    data = json.loads(row.request_json)
    internal = json.loads(row.execution_json)
    common = {"scope": principal.scope, "actor": principal.actor}
    if row.kind in {"workflow.publish", "workflow.rollback"}:
        return await publication.activate(
            db,
            **common,
            preview_id=internal["preview_id"],
            approved=True,
        )
    if row.kind == "changes.apply":
        parent = await changes.owned(db, principal, internal["change_set_id"])
        _, proposal = await changes.revision(db, parent)
        return await changes.effect(db, principal, parent, proposal, row.id)
    if row.kind == "runtime.gate":
        return await admin.set_gate(
            db,
            **common,
            bot_id=data["bot_id"],
            expected_version=data["expected_version"],
            enabled_value=data["enabled"],
            killed=data["killed"],
            operation_id=row.id,
        )
    if row.kind in {"runtime.retry", "runtime.cancel"}:
        return await admin.recover(
            db,
            **common,
            run_id=data["run_id"],
            expected_version=data["expected_version"],
            operation="cancel"
            if row.kind == "runtime.cancel"
            else "retry_failed",
            operation_id=row.id,
        )
    if row.kind == "runtime.delivery_retry":
        return await admin.retry_delivery(
            db,
            **common,
            outbox_id=data["outbox_id"],
            expected_attempts=data["expected_attempts"],
            operation_id=row.id,
        )
    raise McpRejected("mcp_intent_kind_not_found", 404)


async def finalize(db, row, result):
    """Store a receipt after its domain service commits."""
    row.state, row.result_json = "succeeded", canonical_json(result)
    await db.commit()
    return result


async def reconcile(db, principal, row):
    """Inspect immutable receipts before considering another execution."""
    if row.result_json is not None:
        return json.loads(row.result_json)
    data, internal = (
        json.loads(row.request_json),
        json.loads(row.execution_json),
    )
    if row.kind == "changes.apply":
        record = await db.scalar(
            select(ShopWorkflowRevision).where(
                ShopWorkflowRevision.operation_id == row.id,
                ShopWorkflowRevision.store_id == row.store_id,
            )
        )
        if record is None:
            return None
        artifact = preparations.evidence(row)
        if record.workflow_id != artifact["review"]["proposed"]["id"]:
            raise McpRejected("mcp_receipt_unreadable", 503)
        return _receipt(
            row,
            await workflows.operation_result(
                db,
                scope=principal.scope,
                actor=principal.actor,
                workflow_id=record.workflow_id,
                operation_id=row.id,
            ),
        )
    if row.kind.startswith("workflow."):
        preview = await db.scalar(
            select(PublicationPreview)
            .where(
                PublicationPreview.id == internal["preview_id"],
                PublicationPreview.store_id == row.store_id,
                PublicationPreview.session_id == row.grant_id,
            )
            .execution_options(populate_existing=True)
        )
        if preview is None:
            raise McpRejected("mcp_receipt_unreadable", 503)
        if preview.publication_id is None:
            return None
        return _receipt(
            row,
            {
                "publication_id": preview.publication_id,
                "revision": preview.revision,
                "preview_id": preview.id,
                "replayed": True,
            },
        )
    audit = await db.scalar(
        select(RuntimeAudit).where(
            RuntimeAudit.id == row.id,
            RuntimeAudit.store_id == row.store_id,
            RuntimeAudit.staff_id == principal.actor.id,
        )
    )
    if audit is None:
        return None
    if row.kind == "runtime.gate":
        action, target = "gate", gate_key(row.store_id, data["bot_id"])
        request = {
            key: data[key]
            for key in (
                "bot_id",
                "expected_version",
                "enabled",
                "killed",
            )
        }
    elif row.kind == "runtime.delivery_retry":
        action, target = "retry_delivery", data["outbox_id"]
        request = {"expected_attempts": data["expected_attempts"]}
    else:
        action, target = "recover", data["run_id"]
        request = {
            "expected_version": data["expected_version"],
            "operation": "cancel"
            if row.kind == "runtime.cancel"
            else "retry_failed",
        }
    if (
        audit.action != action
        or audit.target_id != target
        or audit.summary.get("request_digest") != publication.digest(request)
    ):
        raise McpRejected("mcp_receipt_unreadable", 503)
    return _receipt(
        row,
        {
            "operation_id": row.id,
            "target_id": target,
            "replayed": True,
        },
    )


async def receipt(db, principal, *, operation_id):
    """Reconcile after expiry without requiring a fresh human approval."""
    row = await preparations.owned(db, principal, operation_id)
    requested = (
        "runtime:read" if row.kind.startswith("runtime.") else "workflow:read"
    )
    current = await grants.resolve_grant(
        db,
        delegation=principal.delegation,
        store_id=row.store_id,
        required_scope=requested,
    )
    with bind_context(current.scope):
        result = await reconcile(db, current, row)
    return {
        "operation_id": row.id,
        "status": "succeeded" if result is not None else row.state,
        "result": result,
    }
