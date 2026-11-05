"""Publication must reject unsafe graphs before persistent customer execution."""

import pytest
from pydantic import ValidationError
from services.shop_runtime.contracts import BindingSpec, publication_findings
from services.shop_workflow_schema import Definition
from tests.test_workflow_schema import document
from tests.test_campaign_admin_store_scope import campaign_app
from tests.test_workflow_api import studio


def test_runtime_rejects_simulation_only_commerce_node():
    """An old service-path wrapper must never be treated as an executable Action."""
    data = document()
    data["nodes"].insert(
        1, {"id": "old", "type": "view_cart", "label": "Cart", "config": {}}
    )
    findings = publication_findings(Definition.model_validate(data))
    assert any(
        x["code"] == "runtime_node_unsupported" and x["node_id"] == "old"
        for x in findings
    )


def test_entry_conflicts_and_scope_are_explicit():
    """Command keys and version policy cannot smuggle callback payloads or revisions."""
    with pytest.raises(ValidationError):
        BindingSpec(bot_id="not-a-uuid", kind="command", key="cart;exec", node_id="s")
    with pytest.raises(ValidationError):
        BindingSpec(
            bot_id="20000000-0000-4000-8000-000000000001",
            kind="command",
            key="/cart",
            node_id="s",
        )


def test_runtime_rejects_unbounded_dynamic_simulator_choices():
    """A synthetic preview order list cannot be published as customer data."""
    data = document()
    data["variables"] = [{"name": "choice", "type": "string"}]
    data["nodes"].insert(
        1,
        {
            "id": "choice",
            "type": "ask_choice",
            "label": "Choice",
            "config": {
                "prompt": "Choose",
                "variable": "choice",
                "choices_source": "simulation_orders",
            },
        },
    )
    assert any(
        x["code"] == "runtime_choice_source_unsupported"
        for x in publication_findings(Definition.model_validate(data))
    )


def test_set_variable_requires_declared_typed_value():
    """An integer assignment cannot persist a string or write trusted context."""
    data = document()
    data["variables"] = [{"name": "count", "type": "integer"}]
    data["nodes"].insert(
        1,
        {
            "id": "set",
            "type": "set_variable",
            "label": "Set",
            "config": {"variable": "count", "value": "wrong"},
        },
    )
    findings = publication_findings(Definition.model_validate(data))
    assert any(x["code"] == "runtime_variable_invalid" for x in findings)


def test_category_reference_checks_its_reference_kind():
    """Category identity stays typed instead of borrowing an arbitrary product ID."""
    from services.shop_workflow_conditions import cast_value
    from services.shop_workflow_schema import Variable

    variable = Variable(name="category", type="category_ref")
    assert cast_value(variable, {"kind": "category", "id": 3}) == {
        "kind": "category",
        "id": 3,
    }
    with pytest.raises(ValueError):
        cast_value(variable, {"kind": "product", "id": 3})


@pytest.mark.asyncio
async def test_publish_exact_preview_replay_and_binding_cas(studio):
    """Review binds activation to one session and rejects a stale entry-pointer diff."""
    from models.shop_staff import ShopStaff
    from models.shop_workflow_runtime import RuntimeBinding, PublishedWorkflow
    from services.shop_runtime.publication import preview, activate
    from services.shop_runtime.contracts import RuntimeRejected
    from services.shop_store_context import resolve_context
    from tests.test_campaign_admin_store_scope import AsyncDb, BOT_A
    from tests.test_workflow_api import create, update
    from sqlalchemy import select

    app = studio
    actor = app.db.get(ShopStaff, 7)
    actor.role = "content"
    app.db.commit()
    made = await create(app)
    saved = await app.request("PATCH", "/workflows/" + made["id"], payload=update(made))
    assert saved.status_code == 200, saved.text
    actor.role = "superadmin"
    app.db.commit()
    db = AsyncDb(app.db)
    scope = await resolve_context(db, staff_id=7, session_id=app.session_id)
    request = {
        "actor": actor,
        "scope": scope,
        "workflow_id": made["id"],
        "revision": 2,
        "bindings": [
            {"bot_id": BOT_A, "kind": "start", "key": "default", "node_id": "s"}
        ],
    }
    first = await preview(db, **request)
    assert first["ready"], first
    activated = await activate(
        db, actor=actor, scope=scope, preview_id=first["preview_id"], approved=True
    )
    replay = await activate(
        db, actor=actor, scope=scope, preview_id=first["preview_id"], approved=True
    )
    assert (
        activated["publication_id"] == replay["publication_id"] and replay["replayed"]
    )
    from uuid import uuid4

    app.db.add(
        RuntimeBinding(
            id=str(uuid4()),
            store_id=scope.current_store_id,
            bot_id=BOT_A,
            publication_id=activated["publication_id"],
            workflow_id=made["id"],
            kind="command",
            key="old",
            node_id="s",
        )
    )
    app.db.commit()
    selected = await preview(db, **request)
    assert selected["diff"]["unchanged_bindings"][0]["bot_id"] == BOT_A
    assert selected["diff"]["unchanged_bindings"][0]["key"] == "old"
    assert selected["diff"]["retains_unselected_bindings"] is True
    next_preview = await preview(db, **request)
    binding = app.db.scalar(select(RuntimeBinding))
    binding.version += 1
    app.db.commit()
    with pytest.raises(RuntimeRejected, match="runtime_preview_conflict"):
        await activate(
            db,
            actor=actor,
            scope=scope,
            preview_id=next_preview["preview_id"],
            approved=True,
        )
    await db.rollback()
    immutable = app.db.scalar(select(PublishedWorkflow))
    immutable.definition = {}
    with pytest.raises(ValueError, match="runtime_immutable_record"):
        await db.commit()
    await db.rollback()
