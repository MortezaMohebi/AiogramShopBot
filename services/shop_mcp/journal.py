"""Exact-request idempotency and recovery through existing domain receipts."""

from __future__ import annotations

import hashlib
import hmac
import json

from sqlalchemy import select

from models.shop_mcp import McpRequest
from models.shop_workflow import ShopWorkflowRevision
from services import shop_workflows as workflows
from services.shop_mcp.contracts import McpRejected
from services.shop_workflow_schema import canonical_json


async def begin(db, principal, tool: str, arguments: dict):
    """Bind all normalized inputs before any service can commit its effect."""
    identity = arguments["operation_id"]
    encoded = canonical_json(arguments)
    digest = hashlib.sha256(
        canonical_json(
            {
                "tool": tool,
                "grant_id": principal.grant.id,
                "arguments": arguments,
            }
        ).encode()
    ).hexdigest()
    row = await db.scalar(
        select(McpRequest)
        .where(McpRequest.id == identity)
        .execution_options(populate_existing=True)
    )
    if row is not None:
        if (
            row.grant_id != principal.grant.id
            or row.store_id != arguments["store_id"]
            or not hmac.compare_digest(row.request_sha256, digest)
        ):
            raise McpRejected("mcp_operation_conflict", 409)
        return row, await recover(db, principal, row)
    # Every accepted MCP domain effect commits its journal row atomically.
    # A receipt without that row belongs to another entry point; adopting it
    # could make a different staged proposal appear already applied.
    existing = await db.scalar(
        select(ShopWorkflowRevision.id).where(
            ShopWorkflowRevision.store_id == arguments["store_id"],
            ShopWorkflowRevision.operation_id == identity,
        )
    )
    if existing is not None:
        raise McpRejected("mcp_operation_conflict", 409)
    row = McpRequest(
        id=identity,
        grant_id=principal.grant.id,
        store_id=arguments["store_id"],
        tool=tool,
        request_sha256=digest,
        arguments_json=encoded,
        state="pending",
    )
    db.add(row)
    await db.flush()
    return row, None


async def recover(db, principal, row: McpRequest):
    """Check immutable effects before interpreting a stale journal state.

    Existing domain services commit their own receipt. A crash immediately
    after that commit must never require repeating the write.
    """
    record = await db.scalar(
        select(ShopWorkflowRevision).where(
            ShopWorkflowRevision.store_id == row.store_id,
            ShopWorkflowRevision.operation_id == row.id,
        )
    )
    if record is not None:
        return await workflows.operation_result(
            db,
            scope=principal.scope,
            actor=principal.actor,
            workflow_id=record.workflow_id,
            operation_id=row.id,
        )
    if row.result_json is None:
        return None
    reference = json.loads(row.result_json)
    if reference["kind"] == "intent":
        from services.shop_mcp import execution, preparations

        status = await execution.receipt(db, principal, operation_id=row.id)
        if status["result"] is not None:
            return status["result"]
        intent = await preparations.owned(db, principal, row.id)
        return preparations.view(intent)
    if reference["kind"] == "changes":
        from services.shop_mcp.changes import get

        result = await get(
            db,
            principal,
            reference["id"],
            reference["version"],
        )
        if row.state == "awaiting_gateway":
            return result | {
                "requires_approval": True,
                "change_set_id": result["id"],
            }
        return result
    if reference["kind"] == "workflow":
        return await workflows.read_workflow(
            db,
            scope=principal.scope,
            actor=principal.actor,
            workflow_id=reference["id"],
            revision=reference["revision"],
        )
    raise McpRejected("mcp_operation_unreadable", 503)


async def finish(db, row, result: dict) -> dict:
    """Persist recovery references without duplicating graph snapshots."""
    if "intent_id" in result:
        reference = {"kind": "intent", "id": result["intent_id"]}
    elif "change_set_id" in result or "version" in result:
        reference = {
            "kind": "changes",
            "id": result.get("change_set_id", result["id"]),
            "version": result["version"],
        }
    else:
        reference = {
            "kind": "workflow",
            "id": result["id"],
            "revision": result["revision"],
        }
    row.result_json = canonical_json(reference)
    row.state = (
        "awaiting_gateway" if result.get("requires_approval") else "succeeded"
    )
    await db.commit()
    return result


async def status(db, principal, operation_id: str) -> dict:
    """Return owned operation state; absence does not mean failure."""
    row = await db.scalar(
        select(McpRequest).where(
            McpRequest.id == operation_id,
            McpRequest.grant_id == principal.grant.id,
            McpRequest.store_id == principal.scope.current_store_id,
        )
    )
    if row is None:
        return {"operation_id": operation_id, "status": "not_observed"}
    result = await recover(db, principal, row)
    state = row.state
    if result is not None and (
        "native_receipt" in result
        or "revision" in result and not result.get("requires_approval")
    ):
        state = "succeeded"
    return {
        "operation_id": row.id,
        "status": state,
        "result": result,
    }
