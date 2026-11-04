"""Exercise deterministic previews; commerce/provider executors must stay absent."""

from copy import deepcopy

import pytest
from pydantic import ValidationError


def conversation():
    """Hand-built branch fixture with two typed inputs and explicit cancellation."""
    from services.shop_workflow_schema import Definition

    return Definition.model_validate(
        {
            "variables": [{"name": "quantity", "type": "integer"}],
            "nodes": [
                {"id": "s", "type": "start", "config": {}},
                {
                    "id": "greet",
                    "type": "send_text",
                    "config": {"text": "سلام {{context.customer_name}}"},
                },
                {
                    "id": "qty",
                    "type": "ask_number",
                    "config": {
                        "prompt": "تعداد؟",
                        "variable": "quantity",
                        "max_attempts": 2,
                    },
                },
                {
                    "id": "check",
                    "type": "condition",
                    "config": {
                        "condition": {
                            "kind": "rule",
                            "variable": "quantity",
                            "operator": "gt",
                            "value": 1,
                        }
                    },
                },
                {
                    "id": "large",
                    "type": "send_text",
                    "config": {"text": "چند قلم: {{quantity}}"},
                },
                {
                    "id": "small",
                    "type": "send_text",
                    "config": {"text": "یک قلم"},
                },
                {
                    "id": "confirm",
                    "type": "confirm",
                    "config": {"prompt": "تأیید می‌کنید؟"},
                },
                {"id": "end", "type": "end", "config": {"message": "تمام شد"}},
                {
                    "id": "cancel",
                    "type": "cancel",
                    "config": {"message": "لغو شد"},
                },
            ],
            "edges": [
                {"id": "a", "source": "s", "target": "greet"},
                {"id": "b", "source": "greet", "target": "qty"},
                {"id": "c", "source": "qty", "target": "check"},
                {
                    "id": "d",
                    "source": "check",
                    "target": "large",
                    "port": "true",
                },
                {
                    "id": "e",
                    "source": "check",
                    "target": "small",
                    "port": "false",
                },
                {"id": "f", "source": "large", "target": "confirm"},
                {"id": "g", "source": "small", "target": "confirm"},
                {
                    "id": "h",
                    "source": "confirm",
                    "target": "end",
                    "port": "confirm",
                },
                {
                    "id": "i",
                    "source": "confirm",
                    "target": "cancel",
                    "port": "cancel",
                },
            ],
        }
    )


def run(definition=None, events=None, platform="telegram", context=None):
    """Invoke the real pure interpreter, without database or provider adapters."""
    from services.shop_workflow_simulator import simulate

    return simulate(
        definition or conversation(),
        platform=platform,
        context=context or {"customer_name": "آزمایشی"},
        events=events or [],
    )


@pytest.mark.parametrize("platform", ["telegram", "bale"])
def test_preview_is_deterministic_typed_and_platform_selectable(platform):
    """The same conversation and events reproduce the exact same branch/history."""
    events = [
        {"kind": "input", "value": "۲"},
        {"kind": "button", "key": "confirm"},
    ]
    result = run(events=events, platform=platform)
    assert result == run(events=deepcopy(events), platform=platform)
    assert result["status"] == "completed" and result["simulation_only"]
    assert result["values"]["quantity"] == 2
    assert "large" in result["visited"] and "small" not in result["visited"]
    assert any(
        message["text"] == "چند قلم: 2" for message in result["messages"]
    )


def test_back_restores_prior_values_and_cancel_ends_the_preview():
    """Back rolls back the accepted interaction rather than mutating stored drafts."""
    result = run(events=[{"kind": "input", "value": "2"}, {"kind": "back"}])
    assert result["status"] == "waiting" and result["active_node_id"] == "qty"
    assert result["values"].get("quantity") is None
    changed = run(
        events=[
            {"kind": "input", "value": "2"},
            {"kind": "back"},
            {"kind": "input", "value": "1"},
            {"kind": "button", "key": "cancel"},
        ]
    )
    assert changed["status"] == "cancelled"
    assert "small" in changed["visited"] and "large" not in changed["visited"]


def test_invalid_input_has_bounded_retries_and_never_executes_expressions():
    """Invalid text cannot become a number or execute a Python expression."""
    once = run(events=[{"kind": "input", "value": "__import__('os')"}])
    assert once["status"] == "waiting" and once["active_node_id"] == "qty"
    twice = run(
        events=[
            {"kind": "input", "value": "bad"},
            {"kind": "input", "value": True},
        ]
    )
    assert (
        twice["status"] == "error"
        and twice["code"] == "input_attempts_exhausted"
    )


def test_delay_and_wait_timeout_use_virtual_time_without_sleep():
    """Timeout policies are previewed deterministically and never schedule live jobs."""
    definition = conversation().model_dump(mode="json")
    definition["timeout_policy"] = {"seconds": 5, "outcome": "cancel"}
    from services.shop_workflow_schema import Definition

    result = run(
        Definition.model_validate(definition),
        events=[{"kind": "tick", "seconds": 6}],
    )
    assert result["status"] == "cancelled" and result["elapsed_seconds"] == 6


def test_controlled_cycle_stops_at_the_declared_visit_budget():
    """A valid bounded loop cannot spin indefinitely in the simulator."""
    from services.shop_workflow_schema import Definition

    definition = Definition.model_validate(
        {
            "variables": [
                {"name": "again", "type": "boolean", "default": True}
            ],
            "nodes": [
                {"id": "s", "type": "start", "config": {}},
                {
                    "id": "loop",
                    "type": "condition",
                    "max_visits": 3,
                    "config": {
                        "condition": {
                            "kind": "rule",
                            "variable": "again",
                            "operator": "eq",
                            "value": True,
                        }
                    },
                },
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "a", "source": "s", "target": "loop"},
                {
                    "id": "b",
                    "source": "loop",
                    "target": "loop",
                    "port": "true",
                },
                {
                    "id": "c",
                    "source": "loop",
                    "target": "end",
                    "port": "false",
                },
            ],
        }
    )
    result = run(definition)
    assert result["status"] == "error" and result["code"] == "node_visit_limit"
    assert result["visited"].count("loop") == 3


def test_action_stub_never_calls_real_commerce_or_provider_code(monkeypatch):
    """Even a valid commerce node produces only a labeled simulation action."""
    from services.shop_cart import ShopCartFlow
    from services.shop_workflow_schema import Definition

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Real commerce was called by a preview")

    monkeypatch.setattr(ShopCartFlow, "reply", forbidden)
    definition = Definition.model_validate(
        {
            "nodes": [
                {"id": "s", "type": "start", "config": {}},
                {"id": "cart", "type": "add_to_cart", "config": {}},
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "a", "source": "s", "target": "cart"},
                {"id": "b", "source": "cart", "target": "end"},
            ],
        }
    )
    result = run(definition)
    assert result["status"] == "completed" and result["stub_actions"] == [
        "add_to_cart"
    ]
    assert any(message["kind"] == "stub" for message in result["messages"])


@pytest.mark.parametrize("platform", ["telegram", "bale"])
def test_return_template_completes_as_an_explicit_nonpublished_stub(platform):
    """The acceptance example supports choices, branching, optional files and confirmation."""
    from services.shop_workflow_templates import return_request_template
    from services.shop_workflow_validation import validate_definition

    definition, _layout = return_request_template()
    assert validate_definition(definition).can_simulate
    result = run(
        definition,
        platform=platform,
        events=[
            {"kind": "button", "key": "order_1"},
            {"kind": "button", "key": "product_1"},
            {"kind": "button", "key": "damaged"},
            {"kind": "input", "value": "بسته آسیب دیده است"},
            {
                "kind": "input",
                "file": {
                    "name": "sample.jpg",
                    "mime_type": "image/jpeg",
                    "size_bytes": 1024,
                },
            },
            {"kind": "button", "key": "confirm"},
        ],
    )
    assert result["status"] == "completed", result
    assert result["values"]["order"]["id"] == 90001
    assert result["values"]["photo"] == "sample.jpg"
    assert "create_return_request" in result["stub_actions"]


def test_unknown_context_and_oversized_rendered_messages_are_rejected():
    """Inputs cannot introduce secret context or silently truncate expanded text."""
    with pytest.raises(ValidationError):
        run(context={"customer_name": "آزمایشی", "admin_password": "secret"})
    from services.shop_workflow_schema import Definition

    value = {
        "variables": [
            {"name": "long", "type": "string", "default": "x" * 3000}
        ],
        "nodes": [
            {"id": "s", "type": "start", "config": {}},
            {
                "id": "text",
                "type": "send_text",
                "config": {"text": "{{long}}{{long}}"},
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "a", "source": "s", "target": "text"},
            {"id": "b", "source": "text", "target": "end"},
        ],
    }
    result = run(Definition.model_validate(value))
    assert (
        result["status"] == "error"
        and result["code"] == "platform_text_limit_after_render"
    )


@pytest.mark.parametrize("kind", ["ask_text", "confirm", "show_buttons"])
def test_oversized_interaction_prompt_cannot_overwrite_the_error_state(kind):
    """An interaction must stop when template expansion exceeds provider limits."""
    from services.shop_workflow_schema import Definition

    config = (
        {"prompt": "{{long}}{{long}}", "variable": "answer"}
        if kind == "ask_text"
        else (
            {"prompt": "{{long}}{{long}}"}
            if kind == "confirm"
            else {
                "text": "{{long}}{{long}}",
                "buttons": [
                    {"key": "done", "label": "پایان", "target": "end"}
                ],
            }
        )
    )
    edges = [{"id": "a", "source": "s", "target": "question"}]
    if kind == "confirm":
        edges.extend(
            [
                {
                    "id": "b",
                    "source": "question",
                    "target": "end",
                    "port": "confirm",
                },
                {
                    "id": "c",
                    "source": "question",
                    "target": "end",
                    "port": "cancel",
                },
            ]
        )
    elif kind == "ask_text":
        edges.append({"id": "b", "source": "question", "target": "end"})
    definition = Definition.model_validate(
        {
            "variables": [
                {"name": "long", "type": "string", "default": "x" * 3000},
                {"name": "answer", "type": "string"},
            ],
            "nodes": [
                {"id": "s", "type": "start", "config": {}},
                {"id": "question", "type": kind, "config": config},
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": edges,
        }
    )
    result = run(definition)
    assert (
        result["status"] == "error"
        and result["code"] == "platform_text_limit_after_render"
    )


def test_user_input_is_echoed_literally_instead_of_becoming_a_template():
    """Only authored message templates interpolate variables, never customer input."""
    from services.shop_workflow_schema import Definition

    definition = Definition.model_validate(
        {
            "variables": [{"name": "answer", "type": "string"}],
            "nodes": [
                {"id": "s", "type": "start", "config": {}},
                {
                    "id": "ask",
                    "type": "ask_text",
                    "config": {"prompt": "پاسخ؟", "variable": "answer"},
                },
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "a", "source": "s", "target": "ask"},
                {"id": "b", "source": "ask", "target": "end"},
            ],
        }
    )
    result = run(
        definition,
        events=[{"kind": "input", "value": "{{context.customer_name}}"}],
    )
    assert (
        next(
            item["text"]
            for item in result["messages"]
            if item["kind"] == "input"
        )
        == "{{context.customer_name}}"
    )


def test_delay_node_advances_only_the_preview_clock():
    """A delay finishes synchronously with virtual elapsed time, without a job."""
    from services.shop_workflow_schema import Definition

    definition = Definition.model_validate(
        {
            "nodes": [
                {"id": "s", "type": "start", "config": {}},
                {"id": "delay", "type": "delay", "config": {"seconds": 2}},
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "a", "source": "s", "target": "delay"},
                {"id": "b", "source": "delay", "target": "end"},
            ],
        }
    )
    result = run(definition)
    assert result["status"] == "completed" and result["elapsed_seconds"] == 2
