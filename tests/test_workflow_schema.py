"""Pin the portable Workflow boundary, safe expressions and graph findings."""

from copy import deepcopy

import pytest
from pydantic import ValidationError


def document():
    """Return a valid minimal graph without any renderer/session fields."""
    return {
        "schema_version": 1,
        "target_platforms": ["telegram", "bale"],
        "assignment": {"mode": "all_eligible", "bot_ids": []},
        "entry_points": [{"kind": "start", "key": "default", "node_id": "s"}],
        "nodes": [
            {"id": "s", "type": "start", "config": {}},
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"id": "e", "source": "s", "target": "end", "port": "next"}],
        "variables": [],
    }


def parsed(value=None):
    """Import the production definition only while a test actually runs."""
    from services.shop_workflow_schema import Definition

    return Definition.model_validate(value or document())


def findings(value):
    """Validate actual graph behavior rather than a duplicate test validator."""
    from services.shop_workflow_validation import validate_definition

    return validate_definition(parsed(value))


def codes(value):
    """Extract stable issue codes for the editor's centralized panel."""
    return {item.code for item in findings(value).issues}


def test_minimal_portable_graph_is_valid_but_never_live_executable():
    """A completed definition must not impersonate an installed Runtime."""
    result = findings(document())
    assert result.valid and result.can_simulate
    assert result.activation_available is False


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": 99},
        {"session": {"customer_id": 1}},
        {"target_platforms": ["unknown"]},
        {"assignment": {"mode": "all_eligible", "bot_ids": ["not-a-uuid"]}},
        {"nodes": [{"id": "s", "type": "execute_python", "config": {}}]},
        {
            "nodes": [
                {
                    "id": "s",
                    "type": "send_text",
                    "config": {"script": "import os"},
                }
            ]
        },
        {"nodes": [{"id": "s", "type": "delay", "config": {"seconds": True}}]},
    ],
)
def test_unknown_shapes_and_executable_configuration_are_rejected(changes):
    """Strict fields prevent renderer data, code and type coercion from entering storage."""
    with pytest.raises(ValidationError):
        parsed(document() | changes)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d.update(nodes=d["nodes"][1:]), "missing_start"),
        (
            lambda d: d["nodes"].append(
                {"id": "s2", "type": "start", "config": {}}
            ),
            "duplicate_start",
        ),
        (
            lambda d: d["nodes"].append(
                {"id": "orphan", "type": "end", "config": {}}
            ),
            "unreachable_node",
        ),
        (lambda d: d["edges"][0].update(target="missing"), "dangling_edge"),
        (lambda d: d["edges"][0].update(port="invented"), "invalid_port"),
        (
            lambda d: d["nodes"].append(deepcopy(d["nodes"][0])),
            "duplicate_node",
        ),
        (lambda d: d.update(edges=[]), "missing_terminal_path"),
    ],
)
def test_semantic_errors_are_located_without_losing_editable_drafts(
    mutate, expected
):
    """An incomplete draft remains parseable and returns meaningful graph diagnostics."""
    value = document()
    mutate(value)
    report = findings(value)
    assert not report.valid
    assert expected in {item.code for item in report.issues}


def test_uncontrolled_cycle_and_explicit_bounded_cycle():
    """A cycle requires an exit and explicit per-node visit budgets."""
    value = document()
    value["nodes"].insert(
        1,
        {
            "id": "loop",
            "type": "condition",
            "config": {
                "condition": {
                    "kind": "rule",
                    "variable": "again",
                    "operator": "eq",
                    "value": True,
                },
            },
        },
    )
    value["variables"] = [
        {"name": "again", "type": "boolean", "default": False}
    ]
    value["edges"] = [
        {"id": "a", "source": "s", "target": "loop", "port": "next"},
        {"id": "b", "source": "loop", "target": "loop", "port": "true"},
        {"id": "c", "source": "loop", "target": "end", "port": "false"},
    ]
    assert "unsafe_cycle" in codes(value)
    value["nodes"][1]["max_visits"] = 3
    assert findings(value).valid


def test_typed_condition_operators_and_unknown_variables():
    """Greater-than cannot compare text, secrets or undeclared references."""
    value = document()
    value["nodes"][0] = {"id": "s", "type": "start", "config": {}}
    value["nodes"].insert(
        1,
        {
            "id": "check",
            "type": "condition",
            "config": {
                "condition": {
                    "kind": "rule",
                    "variable": "name",
                    "operator": "gt",
                    "value": 4,
                },
            },
        },
    )
    value["variables"] = [{"name": "name", "type": "string"}]
    value["edges"] = [
        {"id": "a", "source": "s", "target": "check", "port": "next"},
        {"id": "b", "source": "check", "target": "end", "port": "true"},
        {"id": "c", "source": "check", "target": "end", "port": "false"},
    ]
    assert "condition_type_mismatch" in codes(value)
    value["nodes"][1]["config"]["condition"]["variable"] = "admin.token"
    assert "unknown_variable" in codes(value)


def test_catalog_configurations_and_platform_overrides_are_typed():
    """The inspector's catalog and the Backend use one configuration schema."""
    from services.shop_workflow_catalog import node_catalog

    catalog = node_catalog()
    names = {item["type"] for item in catalog["nodes"]}
    assert {
        "send_text",
        "ask_photo",
        "start_checkout",
        "create_return_request",
    } <= names
    value = document()
    value["nodes"].insert(
        1,
        {
            "id": "message",
            "type": "send_text",
            "config": {"text": "hello"},
            "platform_overrides": {"bale": {"text": 4}},
        },
    )
    with pytest.raises(ValidationError):
        parsed(value)


def test_platform_caption_and_missing_executor_are_distinct_findings():
    """Official Bale support must not hide the current adapter's shorter caption."""
    value = document()
    value["nodes"].insert(
        1,
        {
            "id": "photo",
            "type": "send_photo",
            "config": {
                "media_id": 1,
                "caption": "x" * 1100,
            },
        },
    )
    value["edges"] = [
        {"id": "a", "source": "s", "target": "photo", "port": "next"},
        {"id": "b", "source": "photo", "target": "end", "port": "next"},
    ]
    assert {"platform_caption_limit", "adapter_caption_limit"} <= codes(value)
    value["nodes"][1] = {
        "id": "photo",
        "type": "create_return_request",
        "config": {},
    }
    assert "action_contract_unavailable" in codes(value)


def test_conditions_evaluate_exact_decimals_dates_and_nested_boolean_rules():
    """The interpreter evaluates only declared typed operators, without eval."""
    from services.shop_workflow_conditions import evaluate_condition
    from services.shop_workflow_schema import Variable

    declarations = {
        v.name: v
        for v in [
            Variable(name="amount", type="decimal"),
            Variable(name="date", type="date"),
        ]
    }
    condition = {
        "kind": "all",
        "terms": [
            {
                "kind": "rule",
                "variable": "amount",
                "operator": "gt",
                "value": "0.10",
            },
            {
                "kind": "rule",
                "variable": "date",
                "operator": "lt",
                "value": "2027-01-01",
            },
        ],
    }
    assert evaluate_condition(
        condition, declarations, {"amount": "0.11", "date": "2026-11-05"}
    )
    assert not evaluate_condition(
        condition, declarations, {"amount": "0.10", "date": "2026-11-05"}
    )


def test_deterministic_canonical_serialization_never_stores_layout_or_session():
    """Equivalent dictionary order yields identical bytes and no renderer coupling."""
    from services.shop_workflow_schema import canonical_json

    first = parsed().model_dump(mode="json")
    assert canonical_json(first) == canonical_json(
        dict(reversed(list(first.items())))
    )
    assert "position" not in canonical_json(first)
    with pytest.raises(ValidationError):
        parsed(document() | {"runtime_state": {"current_node": "s"}})


def test_buttons_resolve_targets_and_reject_ambiguous_keys_and_actions():
    """Inspector-selected targets form real graph paths and cannot alias two actions."""
    value = document()
    value["nodes"].insert(
        1,
        {
            "id": "menu",
            "type": "show_buttons",
            "config": {
                "text": "انتخاب کنید",
                "buttons": [
                    {"key": "done", "label": "پایان", "target": "end"}
                ],
            },
        },
    )
    value["edges"] = [
        {"id": "a", "source": "s", "target": "menu", "port": "next"}
    ]
    assert findings(value).valid
    value["nodes"][1]["config"]["buttons"] *= 2
    assert "duplicate_button_key" in codes(value)
    value["nodes"][1]["config"]["buttons"] = [
        {
            "key": "unsafe",
            "label": "عملیات",
            "type": "action",
            "action": "os.system",
        }
    ]
    assert "unknown_action_contract" in codes(value)


def test_switch_requires_a_default_and_every_named_branch():
    """One successful branch cannot conceal a dead end on another choice."""
    value = document()
    value["variables"] = [
        {"name": "reason", "type": "enum", "choices": ["damage", "other"]}
    ]
    value["nodes"].insert(
        1,
        {
            "id": "pick",
            "type": "switch",
            "config": {
                "variable": "reason",
                "cases": [
                    {"key": "damage", "label": "آسیب", "value": "damage"}
                ],
            },
        },
    )
    value["edges"] = [
        {"id": "a", "source": "s", "target": "pick", "port": "next"},
        {"id": "b", "source": "pick", "target": "end", "port": "damage"},
    ]
    assert "missing_branch" in codes(value)


def test_references_and_condition_literals_must_have_the_declared_types():
    """An Order reference cannot populate a Product or a numeric comparison."""
    value = document()
    value["variables"] = [{"name": "item", "type": "order_ref"}]
    value["nodes"].insert(
        1,
        {
            "id": "add",
            "type": "add_to_cart",
            "config": {"product_variable": "item"},
        },
    )
    value["edges"] = [
        {"id": "a", "source": "s", "target": "add", "port": "next"},
        {"id": "b", "source": "add", "target": "end", "port": "next"},
    ]
    assert "action_variable_type_mismatch" in codes(value)
    from services.shop_workflow_conditions import condition_errors
    from services.shop_workflow_schema import Variable

    assert condition_errors(
        {
            "kind": "rule",
            "variable": "amount",
            "operator": "gt",
            "value": None,
        },
        {"amount": Variable(name="amount", type="integer")},
    )


def test_provider_secrets_cannot_hide_in_variable_defaults():
    """The complete definition is checked, not only message configuration."""
    value = document()
    value["variables"] = [
        {
            "name": "setting",
            "type": "string",
            "default": "123456789:" + "a" * 32,
        }
    ]
    with pytest.raises(ValidationError):
        parsed(value)


def test_platform_override_cannot_change_topology_or_variable_binding():
    """Per-platform copy/media may vary; structural contracts stay shared."""
    value = document()
    value["nodes"].insert(
        1,
        {
            "id": "ask",
            "type": "ask_text",
            "config": {"variable": "name", "prompt": "نام"},
            "platform_overrides": {"bale": {"variable": "other"}},
        },
    )
    with pytest.raises(ValidationError):
        parsed(value)


def test_action_button_port_and_implicit_target_are_real_transitions():
    """An action stub with a target must have the same graph semantics as a callback."""
    value = document()
    value["nodes"][0] = {"id": "s", "type": "start", "config": {}}
    value["nodes"].insert(
        1,
        {
            "id": "menu",
            "type": "show_buttons",
            "config": {
                "text": "سبد",
                "buttons": [
                    {
                        "key": "cart",
                        "label": "سبد",
                        "type": "action",
                        "action": "view_cart",
                        "target": "end",
                    }
                ],
            },
        },
    )
    value["edges"] = [
        {"id": "first", "source": "s", "target": "menu", "port": "next"},
        {"id": "second", "source": "menu", "target": "end", "port": "cart"},
    ]
    assert findings(value).can_simulate
    value["edges"].pop()
    assert findings(value).can_simulate


def test_each_target_platform_needs_a_visible_button_and_supported_input_size():
    """Catch deterministic platform failures before the user enters Preview."""
    value = document()
    value["nodes"].insert(
        1,
        {
            "id": "menu",
            "type": "show_buttons",
            "config": {
                "text": "منو",
                "buttons": [
                    {
                        "key": "go",
                        "label": "ادامه",
                        "target": "end",
                        "platforms": ["telegram"],
                    }
                ],
            },
        },
    )
    value["edges"] = [
        {"id": "first", "source": "s", "target": "menu", "port": "next"}
    ]
    assert "platform_buttons_empty" in codes(value)
    value["nodes"][1] = {
        "id": "menu",
        "type": "ask_document",
        "config": {
            "prompt": "فایل",
            "variable": "file",
            "max_bytes": 50_000_000,
        },
    }
    value["variables"] = [{"name": "file", "type": "string"}]
    value["edges"].append(
        {"id": "last", "source": "menu", "target": "end", "port": "next"}
    )
    assert "platform_input_file_limit" in codes(value)


@pytest.mark.parametrize(
    ("kind", "config", "variable", "expected"),
    [
        (
            "ask_choice",
            {
                "prompt": "انتخاب",
                "variable": "answer",
                "choices": [
                    {"key": "a", "label": "گزینه", "value": "not-an-integer"}
                ],
            },
            {"name": "answer", "type": "integer"},
            "choice_type_mismatch",
        ),
        (
            "ask_number",
            {"prompt": "عدد", "variable": "answer", "minimum": "abc"},
            {"name": "answer", "type": "integer"},
            "invalid_number_bounds",
        ),
        (
            "ask_number",
            {
                "prompt": "عدد",
                "variable": "answer",
                "minimum": "10",
                "maximum": "2",
            },
            {"name": "answer", "type": "integer"},
            "invalid_number_bounds",
        ),
        (
            "ask_text",
            {
                "prompt": "متن",
                "variable": "answer",
                "min_length": 10,
                "max_length": 2,
            },
            {"name": "answer", "type": "string"},
            "invalid_text_bounds",
        ),
    ],
)
def test_input_literals_and_bounds_must_admit_valid_typed_answers(
    kind, config, variable, expected
):
    """A graph must not claim simulation readiness when every answer is rejected."""
    value = document()
    value["nodes"].insert(
        1, {"id": "question", "type": kind, "config": config}
    )
    value["variables"] = [variable]
    value["edges"] = [
        {"id": "first", "source": "s", "target": "question"},
        {"id": "last", "source": "question", "target": "end"},
    ]
    assert expected in codes(value)


def test_goto_destination_cannot_invent_a_terminal_exit():
    """The validator and simulator must resolve exactly the same goto destination."""
    value = document()
    value["nodes"].insert(
        1,
        {
            "id": "jump",
            "type": "go_to_step",
            "config": {"target": "jump"},
            "max_visits": 2,
        },
    )
    value["edges"] = [
        {"id": "first", "source": "s", "target": "jump"},
        {"id": "last", "source": "jump", "target": "end"},
    ]
    assert "ambiguous_transition" in codes(value)
