"""Translate designer requests into guarded existing domain operations."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from services import shop_workflows as workflows
from services.shop_mcp import changes
from services.shop_mcp.contracts import McpRejected
from services.shop_mcp.risk import mutation_risk
from services.shop_workflow_schema import Definition, EditorLayout


def portable(snapshot):
    """Retain only reviewed domain content, not live readiness projections."""
    return {
        key: snapshot[key]
        for key in (
            "id",
            "store_id",
            "key",
            "name",
            "description",
            "status",
            "revision",
            "definition",
            "layout",
        )
    }


async def base(db, principal, identity, expected_revision):
    """Read and compare the current owned head before composing any edit."""
    value = await workflows.read_workflow(
        db,
        scope=principal.scope,
        actor=principal.actor,
        workflow_id=identity,
    )
    if value["revision"] != expected_revision:
        raise McpRejected("workflow_revision_conflict", 409)
    return portable(value)


async def _stage(db, principal, tool, arguments, before, proposal, kind):
    """Freeze exact high-risk content before it can change a domain draft."""
    return await changes.create(
        db,
        principal,
        identity=str(
            uuid5(NAMESPACE_URL, "bot-mcp:" + arguments["operation_id"])
        ),
        workflow_id=proposal["id"],
        base=before,
        proposal=proposal,
        operation_id=arguments["operation_id"],
        kind=kind,
        pending=True,
    )


async def mutate(db, principal, tool: str, arguments: dict) -> dict:
    """Apply one approval policy to create, copy, restore and edits."""
    kind = "save"
    if tool in {"workflow.create_draft", "workflow.duplicate"}:
        kind = "create" if tool.endswith("create_draft") else "duplicate"
        if kind == "duplicate":
            await base(
                db,
                principal,
                arguments["source_workflow_id"],
                arguments["expected_source_revision"],
            )
            source = await workflows.read_workflow(
                db,
                scope=principal.scope,
                actor=principal.actor,
                workflow_id=arguments["source_workflow_id"],
                revision=arguments["source_revision"],
            )
            definition = Definition.model_validate(source["definition"])
            layout = EditorLayout.model_validate(source["layout"])
        elif arguments["template"] == "return_request":
            from services.shop_workflow_templates import (
                return_request_template,
            )

            definition, layout = return_request_template()
        elif arguments["template"] == "wholesale_application":
            from services.shop_workflow_templates import (
                wholesale_application_template,
            )

            definition, layout = wholesale_application_template()
        else:
            definition, layout = Definition(), EditorLayout()
        before = {
            "id": arguments["id"],
            "store_id": principal.scope.current_store_id,
            "key": arguments["key"],
            "name": arguments["name"],
            "description": arguments["description"],
            "status": "draft",
            "revision": 0,
            "definition": Definition().model_dump(mode="json"),
            "layout": EditorLayout().model_dump(mode="json"),
        }
        proposal = before | {
            "definition": definition.model_dump(mode="json"),
            "layout": layout.model_dump(mode="json"),
        }
    else:
        before = await base(
            db,
            principal,
            arguments["workflow_id"],
            arguments["expected_revision"],
        )
        proposal = changes.edit(before, arguments)
        if tool == "workflow.restore_draft":
            kind = "restore"
            source = await workflows.read_workflow(
                db,
                scope=principal.scope,
                actor=principal.actor,
                workflow_id=arguments["workflow_id"],
                revision=arguments["revision"],
            )
            proposal = portable(source)
            proposal["revision"] = before["revision"]
            proposal["status"] = "draft"
            proposal["source_revision"] = arguments["revision"]
        if tool == "workflow.archive_draft":
            kind, proposal["status"] = "archive", "archived"
    definition = Definition.model_validate(proposal["definition"])
    layout = EditorLayout.model_validate(proposal["layout"])
    await workflows._check_document(
        db,
        principal.scope.current_store_id,
        definition,
        layout,
    )
    if mutation_risk(before, proposal, kind=kind) != "low":
        return await _stage(
            db,
            principal,
            tool,
            arguments,
            before,
            proposal,
            kind,
        )
    common = {"scope": principal.scope, "actor": principal.actor}
    if kind == "restore":
        return await workflows.restore_revision(
            db,
            **common,
            workflow_id=arguments["workflow_id"],
            payload={
                "operation_id": arguments["operation_id"],
                "expected_revision": arguments["expected_revision"],
                "revision": arguments["revision"],
            },
        )
    if kind in {"create", "duplicate"}:
        return await workflows._create_draft(
            db,
            **common,
            payload={
                "id": proposal["id"],
                "operation_id": arguments["operation_id"],
                "key": proposal["key"],
                "name": proposal["name"],
                "description": proposal["description"],
                "definition": proposal["definition"],
                "layout": proposal["layout"],
            },
            definition=definition,
            layout=layout,
            action=kind,
        )
    return await workflows.save_draft(
        db,
        **common,
        workflow_id=arguments["workflow_id"],
        payload={
            "operation_id": arguments["operation_id"],
            "expected_revision": arguments["expected_revision"],
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
