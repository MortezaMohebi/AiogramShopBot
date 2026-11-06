"""Exercise typed graph patches without persistence or customer execution."""

import importlib
from copy import deepcopy

import pytest

from services.shop_mcp.contracts import McpRejected
from services.shop_workflow_validation import validate_definition
from tests.test_campaign_admin_store_scope import BOT_A, BOT_B
from tests.test_workflow_schema import document


def edit(operations, *, definition=None, layout=None):
    """Call the actual pure patch service and report an absent feature as RED."""
    try:
        module = importlib.import_module("services.shop_mcp.patches")
    except ModuleNotFoundError:
        pytest.fail("The typed workflow patch engine is missing.")
    return module.apply_patches(
        definition or document(),
        layout or {"positions": {}},
        operations,
    )


def test_typed_edits_add_update_and_connect_without_mutating_the_input():
    """Node configuration stays typed while the caller's base remains intact."""
    original = document()
    before = deepcopy(original)
    result = edit(
        [
            {
                "op": "add_variable",
                "variable": {"name": "answer", "type": "string"},
            },
            {
                "op": "add_node",
                "node": {
                    "id": "ask",
                    "type": "ask_text",
                    "config": {"prompt": "Name?", "variable": "answer"},
                },
                "position": {"x": 150.0, "y": 20.0},
            },
            {
                "op": "update_node",
                "node_id": "ask",
                "changes": {
                    "label": "Name",
                    "config": {"prompt": "Your name?"},
                },
            },
            {
                "op": "update_edge",
                "edge_id": "e",
                "changes": {"target": "ask"},
            },
            {
                "op": "add_edge",
                "edge": {
                    "id": "finish",
                    "source": "ask",
                    "target": "end",
                },
            },
        ],
        definition=original,
    )
    ask = next(node for node in result.definition.nodes if node.id == "ask")
    assert ask.config["prompt"] == "Your name?"
    assert ask.config["variable"] == "answer"
    assert ask.label == "Name"
    assert result.layout.positions["ask"].x == 150.0
    assert result.definition.edges[0].target == "ask"
    assert original == before
    assert validate_definition(result.definition).can_simulate


def test_node_removal_cleans_edges_and_layout_but_preserves_editable_errors():
    """Deleting a terminal keeps a repairable draft rather than stale edges."""
    result = edit(
        [{"op": "remove_node", "node_id": "end"}],
        layout={
            "positions": {
                "s": {"x": 0.0, "y": 0.0},
                "end": {"x": 200.0, "y": 0.0},
            }
        },
    )
    assert [node.id for node in result.definition.nodes] == ["s"]
    assert result.definition.edges == []
    assert set(result.layout.positions) == {"s"}
    assert not validate_definition(result.definition).can_simulate


def test_variable_and_entry_changes_have_explicit_stable_selectors():
    """An entry key identifies its kind; variable names cannot be retargeted."""
    result = edit(
        [
            {
                "op": "add_variable",
                "variable": {
                    "name": "answer",
                    "type": "string",
                    "default": "first",
                },
            },
            {
                "op": "update_variable",
                "variable_name": "answer",
                "variable": {
                    "name": "answer",
                    "type": "string",
                    "default": "second",
                },
            },
            {
                "op": "add_entry",
                "entry": {
                    "kind": "command",
                    "key": "help",
                    "node_id": "s",
                    "command": "help",
                },
            },
            {
                "op": "update_entry",
                "entry_kind": "command",
                "entry_key": "help",
                "entry": {
                    "kind": "command",
                    "key": "help",
                    "node_id": "end",
                    "command": "help",
                },
            },
            {
                "op": "remove_entry",
                "entry_kind": "start",
                "entry_key": "default",
            },
        ]
    )
    assert result.definition.variables[0].default == "second"
    assert len(result.definition.entry_points) == 1
    assert result.definition.entry_points[0].node_id == "end"
    removed = edit(
        [{"op": "remove_variable", "variable_name": "answer"}],
        definition=result.definition,
    )
    assert removed.definition.variables == []


def test_platform_overrides_do_not_replace_the_shared_node_contract():
    """Bale text can differ while Telegram and the variable binding stay fixed."""
    data = document()
    data["nodes"].insert(
        1,
        {
            "id": "message",
            "type": "send_text",
            "config": {"text": "Shared"},
        },
    )
    result = edit(
        [
            {
                "op": "update_platform_override",
                "node_id": "message",
                "platform": "bale",
                "values": {"text": "متن بله"},
            }
        ],
        definition=data,
    )
    node = result.definition.nodes[1]
    assert node.config["text"] == "Shared"
    assert node.platform_overrides == {"bale": {"text": "متن بله"}}
    cleared = edit(
        [
            {
                "op": "update_platform_override",
                "node_id": "message",
                "platform": "bale",
                "values": None,
            }
        ],
        definition=result.definition,
    )
    assert cleared.definition.nodes[1].platform_overrides == {}


def test_bot_assignment_is_explicit_and_unassignment_never_grants_all_bots():
    """Removing one selected Bot retains only the explicitly remaining Bot."""
    result = edit(
        [
            {
                "op": "assign_bots",
                "assignment": {
                    "mode": "selected",
                    "bot_ids": [BOT_A, BOT_B],
                },
            },
            {"op": "unassign_bots", "bot_ids": [BOT_B]},
        ]
    )
    assert result.definition.assignment.mode == "selected"
    assert result.definition.assignment.bot_ids == [BOT_A]
    with pytest.raises(McpRejected):
        edit([{"op": "unassign_bots", "bot_ids": [BOT_A]}])


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "set_path", "path": "staff.role", "value": "superadmin"},
        {"op": "update_node", "node_id": "s", "changes": {"type": "python"}},
        {
            "op": "update_node",
            "node_id": "s",
            "changes": {"config": {"script": "pass"}},
        },
        {
            "op": "add_node",
            "node": {"id": "shell", "type": "execute_python", "config": {}},
        },
        {
            "op": "update_platform_override",
            "node_id": "s",
            "platform": "bale",
            "values": {"action_key": "cart.clear"},
        },
    ],
)
def test_unknown_paths_types_and_contract_overrides_are_rejected(operation):
    """Typed patching cannot become a generic object or execution editor."""
    with pytest.raises(McpRejected):
        edit([operation])


def test_conflicting_patch_batches_are_atomic_and_bounded():
    """A late ID conflict or excess operations cannot partly mutate the base."""
    data = document()
    original = deepcopy(data)
    with pytest.raises(McpRejected):
        edit(
            [
                {"op": "remove_edge", "edge_id": "e"},
                {
                    "op": "add_node",
                    "node": {"id": "s", "type": "end", "config": {}},
                },
            ],
            definition=data,
        )
    assert data == original
    with pytest.raises(McpRejected):
        edit(
            [
                {
                    "op": "update_node",
                    "node_id": "s",
                    "changes": {"label": "X"},
                }
            ]
            * 129,
            definition=data,
        )
    assert data == original
