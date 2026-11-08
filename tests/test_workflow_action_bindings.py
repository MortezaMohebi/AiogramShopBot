"""Workflow Actions use typed field mappings and pure deterministic simulation."""

from copy import deepcopy
import subprocess
import sys

import pytest

from services.shop_action_bindings import resolve_inputs, write_outputs
from services.shop_workflow_schema import Definition
from services.shop_workflow_simulator import simulate
from services.shop_workflow_validation import validate_definition


def graph(**config):
    """Build a complete Action graph with all explicit outcome transitions."""
    return {
        "target_platforms": ["telegram", "bale"],
        "nodes": [
            {"id": "start", "type": "start"},
            {
                "id": "add",
                "type": "action",
                "config": {
                    "action_key": "cart.add_item",
                    "action_version": "1.0.0",
                    "input_mapping": {
                        "product_id": {"kind": "variable", "name": "product"},
                        "quantity": {"kind": "variable", "name": "count"},
                    },
                    "output_mapping": {"revision": "revision"},
                    **config,
                },
            },
            {"id": "end", "type": "end"},
        ],
        "edges": [{"id": "begin", "source": "start", "target": "add"}]
        + [
            {"id": "out_" + port, "source": "add", "target": "end", "port": port}
            for port in ("success", "error", "retry", "pending_approval", "unavailable")
        ],
        "variables": [
            {
                "name": "product",
                "type": "product_ref",
                "default": {"kind": "product", "id": 90011},
            },
            {"name": "count", "type": "integer", "default": 2},
            {"name": "revision", "type": "integer"},
        ],
    }


def codes(value):
    """Read semantic findings from the actual Layer 1 validator."""
    return {
        issue.code
        for issue in validate_definition(Definition.model_validate(value)).issues
    }


def test_valid_action_binding_is_portable_and_simulatable():
    document = Definition.model_validate(graph())
    report = validate_definition(document)
    assert report.valid and report.can_simulate, report.model_dump()
    assert document.nodes[1].config["action_version"] == "1.0.0"


@pytest.mark.parametrize(
    "config,expected",
    [
        ({"action_key": "backend.invoke_service"}, "action_unknown"),
        ({"action_version": "9.0.0"}, "action_version_unavailable"),
        ({"input_mapping": {}}, "action_input_required"),
        (
            {"input_mapping": {"product_id": {"kind": "variable", "name": "missing"}}},
            "action_unknown_variable",
        ),
        (
            {
                "input_mapping": {
                    "product_id": {"kind": "variable", "name": "count"},
                    "quantity": {"kind": "variable", "name": "product"},
                }
            },
            "action_input_type_mismatch",
        ),
        (
            {
                "input_mapping": {
                    "product_id": {"kind": "constant", "value": 1},
                    "quantity": {"kind": "constant", "value": 0},
                }
            },
            "action_constant_invalid",
        ),
        (
            {"input_mapping": {"store_id": {"kind": "constant", "value": "foreign"}}},
            "action_input_unknown",
        ),
        (
            {
                "input_mapping": {
                    "product_id": {"kind": "context", "name": "context.secret"}
                }
            },
            "action_context_forbidden",
        ),
        ({"output_mapping": {"items.0.id": "revision"}}, "action_output_unknown"),
        ({"output_mapping": {"revision": "missing"}}, "action_unknown_variable"),
        ({"output_mapping": {"items": "revision"}}, "action_output_type_mismatch"),
    ],
)
def test_binding_failures_are_structured_validation_findings(config, expected):
    assert expected in codes(graph(**config))


def test_action_requires_all_named_outcome_branches():
    value = graph()
    value["edges"] = [
        edge for edge in value["edges"] if edge.get("port") != "pending_approval"
    ]
    assert "action_transition_required" in codes(value)


def test_mapping_reads_only_explicit_variables_and_public_context():
    node = Definition.model_validate(graph()).nodes[1]
    values = {"product": {"kind": "product", "id": 12}, "count": 3}
    assert resolve_inputs(node.config, values) == {"product_id": 12, "quantity": 3}
    assert values["product"] == {"kind": "product", "id": 12}


def test_output_mapping_writes_only_the_declared_typed_variable():
    definition = Definition.model_validate(graph())
    values = {"count": 3}
    write_outputs(
        definition.nodes[1].config,
        {"revision": 8},
        values,
        {item.name: item for item in definition.variables},
    )
    assert values == {"count": 3, "revision": 8}


@pytest.mark.parametrize("platform", ["telegram", "bale"])
def test_real_simulator_replays_typed_action_without_live_adapter(platform):
    result = simulate(graph(), platform=platform)
    assert result["status"] == "completed", result
    assert result["values"]["revision"] == 2
    assert "cart.add_item@1.0.0" in result["stub_actions"]
    assert all(item["simulation_only"] for item in result["messages"])
    assert any(item["kind"] == "stub" for item in result["messages"])


def test_simulator_import_does_not_load_live_adapters_or_db():
    """A future refactor cannot silently route previews into execution adapters."""
    code = "import sys; import services.shop_workflow_simulator; assert 'services.shop_actions.adapters' not in sys.modules; assert 'db' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_incomplete_mapping_remains_an_editable_invalid_draft():
    """Selecting a source before its variable must not make autosave return 422."""
    value = graph()
    value["nodes"][1]["config"]["input_mapping"]["product_id"]["name"] = ""
    parsed = Definition.model_validate(value)
    report = validate_definition(parsed)
    assert not report.valid
    assert "action_unknown_variable" in {issue.code for issue in report.issues}


def test_synthetic_order_uses_selected_platform():
    """Bale simulation must not silently produce a Telegram order context."""
    from services.shop_actions.simulation import simulate_action

    result = simulate_action(
        "order.get_status", "1.0.0", {"order_id": 12}, platform="bale"
    )
    assert result["platform"] == "bale" and result["order_id"] == 12


def test_unavailable_action_follows_its_unavailable_branch_in_preview():
    """A placeholder service must not preview the success path or assign outputs."""
    value = graph(
        action_key="returns.create_request",
        input_mapping={
            "order_id": {"kind": "constant", "value": 90001},
            "reason": {"kind": "constant", "value": "sample"},
        },
        output_mapping={},
    )
    value["nodes"] += [
        {"id": "success", "type": "send_text", "config": {"text": "WRONG_SUCCESS"}},
        {
            "id": "unavailable",
            "type": "send_text",
            "config": {"text": "SAFE_UNAVAILABLE"},
        },
    ]
    for edge in value["edges"]:
        if edge.get("port") in {"success", "unavailable"}:
            edge["target"] = edge["port"]
    value["edges"] += [
        {"id": "done_" + port, "source": port, "target": "end"}
        for port in ("success", "unavailable")
    ]
    result = simulate(value, platform="telegram")
    assert result["status"] == "completed", result
    text = str(result["messages"])
    assert "SAFE_UNAVAILABLE" in text and "WRONG_SUCCESS" not in text


@pytest.mark.parametrize("target_type", ["date", "datetime", "enum"])
def test_unconstrained_string_output_cannot_narrow_into_typed_variable(target_type):
    """Successful validation must not promise a conversion that Preview rejects."""
    value = graph(
        action_key="catalog.get_product",
        input_mapping={"product_id": {"kind": "variable", "name": "product"}},
        output_mapping={"name": "typed_target"},
    )
    value["variables"].append(
        {
            "name": "typed_target",
            "type": target_type,
            "choices": ["allowed"] if target_type == "enum" else [],
        }
    )
    assert "action_output_type_mismatch" in codes(value)


@pytest.mark.parametrize(
    "choices,valid", [(["IRR"], False), (["IRR", "XTR", "USD"], True)]
)
def test_literal_output_requires_all_source_values_in_target_enum(choices, valid):
    """An enum target may widen, but cannot discard a legal Action result."""
    value = graph(
        action_key="order.get_status",
        input_mapping={"order_id": {"kind": "constant", "value": 90001}},
        output_mapping={"currency": "currency"},
    )
    value["variables"].append({"name": "currency", "type": "enum", "choices": choices})
    assert ("action_output_type_mismatch" not in codes(value)) == valid
