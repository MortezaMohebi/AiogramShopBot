"""Persistent interpreter boundaries never execute commerce or provider calls."""

import pytest
from services.shop_runtime.interpreter import Machine
from services.shop_runtime.contracts import RuntimeRejected
from services.shop_workflow_schema import Definition


def form():
    """Build a literal reviewable two-question graph with one explicit terminal."""
    return Definition.model_validate(
        {
            "nodes": [
                {"id": "s", "type": "start"},
                {
                    "id": "name",
                    "type": "ask_text",
                    "config": {"prompt": "Name?", "variable": "name", "max_length": 20},
                },
                {
                    "id": "amount",
                    "type": "ask_number",
                    "config": {
                        "prompt": "Amount?",
                        "variable": "amount",
                        "minimum": "1",
                    },
                },
                {
                    "id": "review",
                    "type": "confirm",
                    "config": {"prompt": "{{name}} / {{amount}}"},
                },
                {"id": "done", "type": "end", "config": {"message": "Done"}},
                {"id": "cancel", "type": "cancel"},
            ],
            "variables": [
                {"name": "name", "type": "string"},
                {"name": "amount", "type": "integer"},
            ],
            "edges": [
                {"id": "e" + str(i), "source": a, "port": p, "target": b}
                for i, (a, p, b) in enumerate(
                    [
                        ("s", "next", "name"),
                        ("name", "next", "amount"),
                        ("amount", "next", "review"),
                        ("review", "confirm", "done"),
                        ("review", "cancel", "cancel"),
                    ]
                )
            ],
        }
    )


def test_interpreter_waits_and_renders_pinned_values():
    """Each valid input advances only to the next durable interaction boundary."""
    machine = Machine(form(), platform="telegram", node_id="s")
    machine.advance()
    assert machine.status == "waiting_input" and machine.node_id == "name"
    assert machine.outbound[0]["text"] == "Name?"
    machine.accept("Alice")
    assert machine.node_id == "amount"
    machine.accept("۱۲")
    assert machine.values == {"name": "Alice", "amount": 12}
    assert machine.outbound[-1]["text"] == "Alice / 12"
    machine.choose("confirm")
    assert machine.status == "completed"


def test_invalid_number_does_not_consume_wait_or_change_value():
    """Bad input cannot silently move past its question or overwrite typed state."""
    m = Machine(form(), platform="bale", node_id="s")
    m.advance()
    m.accept("Alice")
    m.accept("0")
    assert m.node_id == "amount" and m.status == "waiting_input"
    assert "amount" not in m.values and m.state["attempts"] == 1


def test_back_restores_previous_question_and_cancel_is_terminal():
    """Back can revisit unanswered UI state; Cancel emits no Action intent."""
    m = Machine(form(), platform="telegram", node_id="s")
    m.advance()
    m.accept("Alice")
    m.choose("back")
    assert m.node_id == "name" and "name" not in m.values
    m.choose("cancel")
    assert m.status == "cancelled" and m.action is None


def test_cycle_stops_at_bounded_visit_budget():
    """A graph loop cannot spin a worker or create unbounded outbound intents."""
    d = Definition.model_validate(
        {
            "nodes": [{"id": "s", "type": "start", "max_visits": 2}],
            "edges": [{"id": "e", "source": "s", "target": "s"}],
        }
    )
    m = Machine(d, platform="telegram", node_id="s")
    m.advance()
    assert m.status == "failed" and m.error == "runtime_visit_budget"


def test_switch_compares_typed_choice_values():
    """Switch consumes its catalog value contract rather than a nonexistent condition."""
    d = Definition.model_validate(
        {
            "nodes": [
                {"id": "s", "type": "start"},
                {
                    "id": "sw",
                    "type": "switch",
                    "config": {
                        "variable": "amount",
                        "cases": [{"key": "twelve", "label": "12", "value": 12}],
                    },
                },
                {"id": "yes", "type": "end", "config": {"message": "matched"}},
                {"id": "no", "type": "cancel"},
            ],
            "variables": [{"name": "amount", "type": "integer", "default": 12}],
            "edges": [
                {"id": "e1", "source": "s", "target": "sw"},
                {"id": "e2", "source": "sw", "port": "twelve", "target": "yes"},
                {"id": "e3", "source": "sw", "port": "default", "target": "no"},
            ],
        }
    )
    m = Machine(d, platform="telegram", node_id="s")
    m.advance()
    assert m.status == "completed" and m.outbound[0]["text"] == "matched"


def test_set_variable_is_shared_with_safe_simulator():
    """The newly declared primitive behaves identically before and after publication."""
    from services.shop_workflow_simulator import PreviewInterpreter, SimulationContext

    d = Definition.model_validate(
        {
            "nodes": [
                {"id": "s", "type": "start"},
                {
                    "id": "set",
                    "type": "set_variable",
                    "config": {"variable": "count", "value": 9},
                },
                {"id": "done", "type": "end"},
            ],
            "variables": [{"name": "count", "type": "integer"}],
            "edges": [
                {"id": "e1", "source": "s", "target": "set"},
                {"id": "e2", "source": "set", "target": "done"},
            ],
        }
    )
    preview = PreviewInterpreter(d, "telegram", SimulationContext())
    preview.pump()
    assert preview.state.values["count"] == 9 and preview.state.status == "completed"


def test_main_menu_ends_run_and_emits_server_menu_intent():
    """Main menu releases workflow input while requesting the actual storefront menu."""
    m = Machine(form(), platform="telegram", node_id="s")
    m.advance()
    m.choose("main_menu")
    assert m.status == "cancelled"
    assert m.outbound[-1]["kind"] == "legacy_menu" and m.outbound[-1]["notice"] is True


def test_native_contact_cannot_fill_a_text_question():
    """A typed interaction checks the native input kind before assigning a variable."""
    m = Machine(form(), platform="telegram", node_id="s")
    m.advance()
    m.accept("+989121234567", kind="contact", contact_owner=101, user_id=101)
    assert m.node_id == "name" and "name" not in m.values
