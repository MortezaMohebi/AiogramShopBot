"""Apply bounded typed patches to a portable graph without side effects."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Annotated, Literal, Union

from pydantic import Field, JsonValue, ValidationError

from services.shop_mcp.contracts import McpRejected
from services.shop_workflow_schema import (
    BotAssignment,
    BotId,
    Definition,
    EditorLayout,
    EntryPoint,
    Identifier,
    Platform,
    Position,
    StrictModel,
    Variable,
    WorkflowEdge,
    WorkflowNode,
)

EntryKind = Literal["start", "command", "menu", "internal"]


class NodeChanges(StrictModel):
    """Update declared node fields without changing its type or identity."""

    label: str | None = Field(default=None, max_length=120)
    config: dict[str, JsonValue] | None = None
    max_visits: int | None = Field(default=None, ge=1, le=25)


class EdgeChanges(StrictModel):
    """Edit a transition through explicit domain fields, never object paths."""

    source: Identifier | None = None
    target: Identifier | None = None
    port: str | None = Field(default=None, min_length=1, max_length=64)


class AddNode(StrictModel):
    """Insert a new typed node and optional independent editor geometry."""

    op: Literal["add_node"]
    node: WorkflowNode
    position: Position | None = None


class UpdateNode(StrictModel):
    """Merge configuration through the existing node's specific schema."""

    op: Literal["update_node"]
    node_id: Identifier
    changes: NodeChanges


class RemoveNode(StrictModel):
    """Remove a node, edges and layout; retain repairable references."""

    op: Literal["remove_node"]
    node_id: Identifier


class AddEdge(StrictModel):
    """Append an explicitly named domain transition."""

    op: Literal["add_edge"]
    edge: WorkflowEdge


class UpdateEdge(StrictModel):
    """Select one transition by its stable identity."""

    op: Literal["update_edge"]
    edge_id: Identifier
    changes: EdgeChanges


class RemoveEdge(StrictModel):
    """Delete one identified transition."""

    op: Literal["remove_edge"]
    edge_id: Identifier


class AddVariable(StrictModel):
    """Add a declared typed workflow variable."""

    op: Literal["add_variable"]
    variable: Variable


class UpdateVariable(StrictModel):
    """Replace a variable declaration while preserving its selected name."""

    op: Literal["update_variable"]
    variable_name: Identifier
    variable: Variable


class RemoveVariable(StrictModel):
    """Remove a declaration; validation still reports remaining references."""

    op: Literal["remove_variable"]
    variable_name: Identifier


class AddEntry(StrictModel):
    """Add a draft routing declaration without changing live bindings."""

    op: Literal["add_entry"]
    entry: EntryPoint


class EntrySelector(StrictModel):
    """Identify a routing declaration by both kind and key."""

    entry_kind: EntryKind
    entry_key: Identifier


class UpdateEntry(EntrySelector):
    """Edit an entry without silently retargeting its selector."""

    op: Literal["update_entry"]
    entry: EntryPoint


class RemoveEntry(EntrySelector):
    """Delete one exact draft routing declaration."""

    op: Literal["remove_entry"]


class AssignBots(StrictModel):
    """Change draft assignment; persistence separately verifies ownership."""

    op: Literal["assign_bots"]
    assignment: BotAssignment


class UnassignBots(StrictModel):
    """Remove explicit selections without introducing an all-Bot wildcard."""

    op: Literal["unassign_bots"]
    bot_ids: list[BotId] = Field(min_length=1, max_length=1000)


class PlatformOverride(StrictModel):
    """Set or clear partial presentation fields for one platform."""

    op: Literal["update_platform_override"]
    node_id: Identifier
    platform: Platform
    values: dict[str, JsonValue] | None


Patch = Annotated[
    Union[
        AddNode,
        UpdateNode,
        RemoveNode,
        AddEdge,
        UpdateEdge,
        RemoveEdge,
        AddVariable,
        UpdateVariable,
        RemoveVariable,
        AddEntry,
        UpdateEntry,
        RemoveEntry,
        AssignBots,
        UnassignBots,
        PlatformOverride,
    ],
    Field(discriminator="op"),
]


class PatchBatch(StrictModel):
    """Bound one atomic edit request independently of registered Bot count."""

    operations: list[Patch] = Field(min_length=1, max_length=128)


@dataclass(frozen=True, slots=True)
class PatchResult:
    """A normalized proposal whose graph can still contain editable errors."""

    definition: Definition
    layout: EditorLayout


def _index(items, selected, *, key="id") -> int:
    """Require an unambiguous selector even in a semantically invalid draft."""
    found = [i for i, item in enumerate(items) if item[key] == selected]
    if not found:
        raise McpRejected("mcp_patch_target_not_found", 404)
    if len(found) != 1:
        raise McpRejected("mcp_patch_ambiguous", 409)
    return found[0]


def _new(items, value, *, key="id") -> None:
    """Reject ID collisions to preserve existing work."""
    if any(item[key] == value[key] for item in items):
        raise McpRejected("mcp_patch_target_exists", 409)
    items.append(value)


def _entry_index(entries, kind, key) -> int:
    """Entry keys are scoped to their actual routing kind."""
    found = [
        i
        for i, item in enumerate(entries)
        if item["kind"] == kind and item["key"] == key
    ]
    if len(found) != 1:
        raise McpRejected(
            "mcp_patch_target_not_found"
            if not found
            else "mcp_patch_ambiguous",
            404 if not found else 409,
        )
    return found[0]


def _apply(value: dict, geometry: dict, patch: Patch) -> None:
    """Apply one already typed domain edit only to the private working copy."""
    nodes, edges = value["nodes"], value["edges"]
    variables, entries = value["variables"], value["entry_points"]
    if isinstance(patch, AddNode):
        _new(nodes, patch.node.model_dump(mode="json"))
        if patch.position is not None:
            geometry["positions"][patch.node.id] = patch.position.model_dump()
    elif isinstance(patch, UpdateNode):
        node = nodes[_index(nodes, patch.node_id)]
        for field in patch.changes.model_fields_set:
            changed = getattr(patch.changes, field)
            if field == "config":
                if changed is None:
                    raise McpRejected("mcp_patch_invalid", 422)
                node["config"] |= changed
            else:
                node[field] = changed
    elif isinstance(patch, RemoveNode):
        nodes.pop(_index(nodes, patch.node_id))
        value["edges"] = [
            edge
            for edge in edges
            if patch.node_id not in (edge["source"], edge["target"])
        ]
        geometry["positions"].pop(patch.node_id, None)
    elif isinstance(patch, AddEdge):
        _new(edges, patch.edge.model_dump(mode="json"))
    elif isinstance(patch, UpdateEdge):
        edge = edges[_index(edges, patch.edge_id)]
        edge.update(patch.changes.model_dump(exclude_unset=True))
    elif isinstance(patch, RemoveEdge):
        edges.pop(_index(edges, patch.edge_id))
    elif isinstance(patch, AddVariable):
        _new(variables, patch.variable.model_dump(mode="json"), key="name")
    elif isinstance(patch, UpdateVariable):
        index = _index(variables, patch.variable_name, key="name")
        if patch.variable.name != patch.variable_name:
            raise McpRejected("mcp_patch_selector_changed", 422)
        variables[index] = patch.variable.model_dump(mode="json")
    elif isinstance(patch, RemoveVariable):
        variables.pop(_index(variables, patch.variable_name, key="name"))
    elif isinstance(patch, AddEntry):
        if any(
            item["kind"] == patch.entry.kind and item["key"] == patch.entry.key
            for item in entries
        ):
            raise McpRejected("mcp_patch_target_exists", 409)
        entries.append(patch.entry.model_dump(mode="json"))
    elif isinstance(patch, UpdateEntry):
        index = _entry_index(entries, patch.entry_kind, patch.entry_key)
        if (patch.entry.kind, patch.entry.key) != (
            patch.entry_kind,
            patch.entry_key,
        ):
            raise McpRejected("mcp_patch_selector_changed", 422)
        entries[index] = patch.entry.model_dump(mode="json")
    elif isinstance(patch, RemoveEntry):
        entries.pop(_entry_index(entries, patch.entry_kind, patch.entry_key))
    elif isinstance(patch, AssignBots):
        value["assignment"] = patch.assignment.model_dump(mode="json")
    elif isinstance(patch, UnassignBots):
        assigned = value["assignment"]
        if assigned["mode"] != "selected":
            raise McpRejected("mcp_assignment_requires_selection", 409)
        if set(patch.bot_ids) - set(assigned["bot_ids"]):
            raise McpRejected("mcp_patch_target_not_found", 404)
        assigned["bot_ids"] = [
            item for item in assigned["bot_ids"] if item not in patch.bot_ids
        ]
        if not assigned["bot_ids"]:
            raise McpRejected("mcp_assignment_empty", 422)
    elif isinstance(patch, PlatformOverride):
        node = nodes[_index(nodes, patch.node_id)]
        if patch.values is None:
            node["platform_overrides"].pop(patch.platform, None)
        else:
            current = node["platform_overrides"].get(patch.platform, {})
            node["platform_overrides"][patch.platform] = current | patch.values


def apply_patches(definition, layout, operations: list[dict]) -> PatchResult:
    """Validate a batch and return a normalized immutable proposal."""
    try:
        source = (
            definition.model_dump(mode="json")
            if isinstance(definition, Definition)
            else deepcopy(definition)
        )
        positions = (
            layout.model_dump(mode="json")
            if isinstance(layout, EditorLayout)
            else deepcopy(layout)
        )
        value = Definition.model_validate(source).model_dump(mode="json")
        geometry = EditorLayout.model_validate(positions).model_dump(
            mode="json"
        )
        batch = PatchBatch.model_validate({"operations": operations})
        for patch in batch.operations:
            _apply(value, geometry, patch)
        return PatchResult(
            Definition.model_validate(value),
            EditorLayout.model_validate(geometry),
        )
    except McpRejected:
        raise
    except (ValidationError, ValueError, TypeError, RecursionError, KeyError):
        raise McpRejected("mcp_patch_invalid", 422) from None
