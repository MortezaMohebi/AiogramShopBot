"""Recover durable proposal receipts after interrupted journal finalization."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from models.shop_mcp import McpChangeSetRevision, McpRequest
from services.shop_mcp import journal
from services.shop_workflow_templates import wholesale_application_template
from tests.test_campaign_admin_store_scope import (
    campaign_app as campaign_app,  # noqa: PLC0414
)
from tests.test_mcp_workflows import client, creation
from tests.test_workflow_schema import document


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["sensitive_create", "create", "update", "sensitive_apply"]
)
async def test_committed_proposal_recovers_without_repeating_a_write(
    campaign_app, monkeypatch, kind
):
    """A crash cannot turn an exact durable request into a conflict or new edit."""
    call, db, _ = await client(campaign_app)
    if kind == "sensitive_create":
        name = "workflow.create_draft"
        arguments = creation(template="wholesale_application")
    else:
        draft = await call("workflow.create_draft", **creation())
        name = "changes.create"
        arguments = {
            "id": str(uuid4()),
            "operation_id": str(uuid4()),
            "workflow_id": draft["id"],
            "expected_revision": draft["revision"],
            "definition": document(),
        }
        if kind in {"update", "sensitive_apply"}:
            if kind == "sensitive_apply":
                definition, _ = wholesale_application_template()
                arguments["definition"] = definition.model_dump(mode="json")
            proposal = await call(name, **arguments)
            name = "changes.update" if kind == "update" else "changes.apply"
            arguments = {
                "change_set_id": proposal["id"],
                "expected_version": proposal["version"],
                "operation_id": str(uuid4()),
            }
            if kind == "update":
                arguments["patches"] = [
                    {
                        "op": "update_node",
                        "node_id": "end",
                        "changes": {"label": "Recovered proposal"},
                    }
                ]
    captured = {}

    async def interrupt(_db, _row, result):
        """Fail at the actual boundary after the proposal's database commit."""
        captured.update(result)
        raise RuntimeError("qa_crash_before_journal_finish")

    with monkeypatch.context() as patch:
        patch.setattr(journal, "finish", interrupt)
        with pytest.raises(RuntimeError, match="qa_crash_before"):
            await call(name, **arguments)
    await db.rollback()
    row = campaign_app.db.get(McpRequest, arguments["operation_id"])
    assert row.state == "pending" and row.result_json is None
    if kind == "create":
        # A different edit may arrive before the lost original response is
        # reconciled. Recovery must still return the original hashed version.
        await call(
            "changes.update",
            change_set_id=captured["id"],
            expected_version=1,
            operation_id=str(uuid4()),
            patches=[
                {
                    "op": "update_node",
                    "node_id": "end",
                    "changes": {"label": "A later, independent edit"},
                }
            ],
        )
        captured["current_version"] = 2
    before = campaign_app.db.scalar(
        select(func.count()).select_from(McpChangeSetRevision)
    )
    recovered = await call(name, **arguments)
    assert recovered == captured
    assert campaign_app.db.scalar(
        select(func.count()).select_from(McpChangeSetRevision)
    ) == before
    status = await call(
        "operations.get_status", operation_id=arguments["operation_id"]
    )
    assert status["result"] == captured
    assert status["status"] == (
        "awaiting_gateway" if captured.get("requires_approval") else "succeeded"
    )
