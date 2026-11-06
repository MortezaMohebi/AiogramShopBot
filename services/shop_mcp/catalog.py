"""Closed discovery: typed tools, scoped resources and safe prompts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache

from services.shop_mcp import approval_contracts as a
from services.shop_mcp import tool_contracts as c


@dataclass(frozen=True, slots=True)
class Tool:
    """Declare input and authorization before invoking an explicit handler."""

    name: str
    request: type
    scopes: tuple[str, ...]
    write: bool = False


_READ = ("workflow:read",)
_WRITE = ("workflow:write", "workflow:read")
TOOLS = (
    Tool("context.get_profile", c.ContextRequest, _READ),
    Tool("context.list_stores", c.ContextRequest, _READ),
    Tool("platforms.get_capabilities", c.StoreRequest, _READ),
    Tool("bots.list", c.PageRequest, ("bots:read",)),
    Tool("actions.list", c.ActionList, ("actions:read",)),
    Tool("actions.get", c.ActionDetail, ("actions:read",)),
    Tool("workflow.list", c.WorkflowList, _READ),
    Tool("workflow.get", c.WorkflowGet, _READ),
    Tool("workflow.list_revisions", c.WorkflowPage, _READ),
    Tool("workflow.compare_revisions", c.CompareRevisions, _READ),
    Tool("workflow.create_draft", c.CreateWorkflow, _WRITE, True),
    Tool("workflow.duplicate", c.DuplicateWorkflow, _WRITE, True),
    Tool("workflow.update_metadata", c.MetadataEdit, _WRITE, True),
    Tool("workflow.replace_definition", c.DefinitionEdit, _WRITE, True),
    Tool("workflow.apply_patches", c.PatchEdit, _WRITE, True),
    Tool("workflow.assign_bots", c.AssignmentEdit, _WRITE, True),
    Tool("workflow.restore_draft", c.RestoreWorkflow, _WRITE, True),
    Tool("workflow.archive_draft", c.WorkflowMutation, _WRITE, True),
    Tool("workflow.validate", c.ValidateWorkflow, ("workflow:validate",)),
    Tool("workflow.simulate", c.SimulateWorkflow, ("workflow:simulate",)),
    Tool("changes.create", c.ChangeSetCreate, _WRITE, True),
    Tool("changes.get", c.ChangeSetGet, _READ),
    Tool("changes.update", c.ChangeSetUpdate, _WRITE, True),
    Tool("changes.apply", c.ChangeSetMutation, _WRITE, True),
    Tool("changes.cancel", c.ChangeSetMutation, _WRITE, True),
    Tool(
        "workflow.validate_change_set",
        c.ChangeSetRequest,
        ("workflow:validate",),
    ),
    Tool(
        "workflow.simulate_change_set",
        c.SimulateChangeSet,
        ("workflow:simulate",),
    ),
    Tool("operations.get_status", c.OperationStatus, _READ),
    Tool("runtime.list_runs", c.RuntimeList, ("runtime:read",)),
    Tool("runtime.get_run", c.RuntimeRun, ("runtime:read",)),
    Tool("runtime.diagnose_failure", c.RuntimeRun, ("runtime:read",)),
    Tool("catalog.list_categories", c.CatalogPage, ("catalog:read",)),
    Tool("catalog.search_products", c.CatalogSearch, ("catalog:read",)),
    Tool("catalog.get_product", c.CatalogProduct, ("catalog:read",)),
    Tool("catalog.get_price_uom", c.CatalogProduct, ("catalog:read",)),
    Tool(
        "workflow.prepare_publish",
        a.PreparePublication,
        ("workflow:publish", "workflow:read"),
        True,
    ),
    Tool(
        "workflow.prepare_rollback",
        a.PrepareRollback,
        ("workflow:rollback", "workflow:read"),
        True,
    ),
    Tool(
        "runtime.prepare_gate",
        a.PrepareGate,
        ("runtime:control", "runtime:read"),
        True,
    ),
    Tool(
        "runtime.prepare_retry",
        a.PrepareRun,
        ("runtime:control", "runtime:read"),
        True,
    ),
    Tool(
        "runtime.prepare_cancel",
        a.PrepareRun,
        ("runtime:control", "runtime:read"),
        True,
    ),
    Tool(
        "runtime.prepare_delivery_retry",
        a.PrepareDelivery,
        ("runtime:control", "runtime:read"),
        True,
    ),
    Tool("workflow.get_operation_status", c.OperationStatus, _READ),
    Tool("runtime.get_operation_status", c.OperationStatus, ("runtime:read",)),
)
BY_NAME = {tool.name: tool for tool in TOOLS}


def input_schema(model) -> dict:
    """Publish each node's concrete configuration schema."""
    from services.shop_workflow_catalog import CONFIG_MODELS

    schema = model.model_json_schema()
    definitions = schema.setdefault("$defs", {})
    node = definitions.get("WorkflowNode")
    if node is not None:
        node["properties"]["type"]["enum"] = sorted(CONFIG_MODELS)
        node["allOf"] = []
        for key, config_model in CONFIG_MODELS.items():
            config = config_model.model_json_schema()
            for name, value in config.pop("$defs", {}).items():
                if name in definitions and definitions[name] != value:
                    raise ValueError("mcp_schema_definition_collision")
                definitions[name] = value
            node["allOf"].append(
                {
                    "if": {"properties": {"type": {"const": key}}},
                    "then": {"properties": {"config": config}},
                }
            )
    if not definitions:
        schema.pop("$defs")
    return schema


@lru_cache(maxsize=1)
def _catalog() -> list[dict]:
    """Emit concrete schemas for actual SDK registration."""
    return [
        {
            "name": "bot." + tool.name,
            "native_name": tool.name,
            "description": tool.request.__doc__ or tool.name,
            "input_schema": input_schema(tool.request),
            "required_scopes": list(tool.scopes),
            "annotations": {
                "readOnlyHint": not tool.write,
                "destructiveHint": tool.name == "workflow.archive_draft",
                "idempotentHint": True,
                "openWorldHint": False,
            },
        }
        for tool in TOOLS
    ]


def tool_catalog() -> list[dict]:
    """Keep callers from modifying globally registered tool contracts."""
    return deepcopy(_catalog())
