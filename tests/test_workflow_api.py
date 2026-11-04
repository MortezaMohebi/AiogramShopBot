"""Exercise Studio through real signed HTTP, Store rules and SQL transactions."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from models.shop_admin_control import AdminEvent
from models.shop_content import Product, ProductMedia
from models.shop_multibot import ShopBot
from models.shop_staff import ShopStaff
from models.shop_staff_store import ShopAdminSessionStore
from dashboard import next_api
from tests.test_campaign_admin_store_scope import (
    AsyncDb,
    BOT_A,
    BOT_B,
    STORE_A,
    STORE_B,
    campaign_app,
)
from tests.test_workflow_schema import document


@pytest.fixture
def studio(campaign_app):
    """Use the existing real session middleware with an ordinary content editor."""
    app = campaign_app
    app.db.get(ShopStaff, 7).role = "content"
    app.db.commit()
    app.app.dependency_overrides[next_api.database] = (
        app.legacy.dependency_overrides[next_api.database]
    )
    return app


def creation(**overrides):
    """Use client-generated UUIDs to reconcile an uncertain create response."""
    return {
        "id": str(uuid4()),
        "operation_id": str(uuid4()),
        "name": "فرایند مرجوعی",
        "key": "returns",
        "template": "blank",
        **overrides,
    }


async def create(app, **overrides):
    """Create one actual draft and return the authoritative Backend snapshot."""
    response = await app.request(
        "POST", "/workflows", payload=creation(**overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


def update(record, **overrides):
    """Retain the explicit optimistic base and exact operation identity."""
    return {
        "operation_id": str(uuid4()),
        "expected_revision": record["revision"],
        "name": record["name"],
        "description": record["description"],
        "definition": document(),
        "layout": record["layout"],
        **overrides,
    }


@pytest.mark.asyncio
async def test_persist_reload_version_compare_and_restore(studio):
    """Restoring definition one appends revision three and preserves immutable two."""
    first = await create(studio)
    assert first["store_id"] == STORE_A and first["revision"] == 1
    saved = await studio.request(
        "PATCH", "/workflows/" + first["id"], payload=update(first)
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    loaded = await studio.request("GET", "/workflows/" + first["id"])
    assert loaded.json()["definition"]["nodes"][0]["id"] == "s"
    comparison = await studio.request(
        "GET", f'/workflows/{first["id"]}/compare?left=1&right=2'
    )
    assert comparison.status_code == 200, comparison.text
    assert comparison.json()["nodes"]["added"] == ["end", "s"]
    restored = await studio.request(
        "POST",
        f'/workflows/{first["id"]}/restore',
        payload={
            "operation_id": str(uuid4()),
            "expected_revision": 2,
            "revision": 1,
        },
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["revision"] == 3
    assert restored.json()["definition"] == first["definition"]
    previous = await studio.request(
        "GET", f'/workflows/{first["id"]}/revisions/2'
    )
    assert previous.json()["definition"]["nodes"][0]["id"] == "s"
    assert (
        studio.db.scalar(
            select(func.count())
            .select_from(AdminEvent)
            .where(AdminEvent.action.like("workflow.%"))
        )
        == 3
    )


@pytest.mark.asyncio
async def test_exact_operation_replay_and_stale_tab_conflict(studio):
    """Unknown outcomes are recoverable; a distinct stale edit cannot overwrite them."""
    payload = creation()
    created = await studio.request("POST", "/workflows", payload=payload)
    assert created.status_code == 201, created.text
    first = created.json()
    replay = await studio.request("POST", "/workflows", payload=payload)
    assert (
        replay.json()["id"] == first["id"] and replay.json()["revision"] == 1
    )
    change = update(first, name="نسخهٔ دوم")
    saved = await studio.request(
        "PATCH", "/workflows/" + first["id"], payload=change
    )
    assert saved.status_code == 200, saved.text
    again = await studio.request(
        "PATCH", "/workflows/" + first["id"], payload=change
    )
    assert again.json()["revision"] == 2
    conflict = await studio.request(
        "PATCH",
        "/workflows/" + first["id"],
        payload=update(first, name="تغییر قدیمی"),
    )
    assert (
        conflict.status_code == 409
        and conflict.json()["detail"] == "workflow_revision_conflict"
    )
    different = await studio.request(
        "PATCH",
        "/workflows/" + first["id"],
        payload=change | {"name": "بدنهٔ متفاوت"},
    )
    assert (
        different.status_code == 409
        and different.json()["detail"] == "workflow_operation_conflict"
    )
    operation = await studio.request(
        "GET", f'/workflows/{first["id"]}/operations/{change["operation_id"]}'
    )
    assert operation.status_code == 200 and operation.json()["revision"] == 2
    assert (await studio.request("GET", "/workflows/" + first["id"])).json()[
        "name"
    ] == "نسخهٔ دوم"


@pytest.mark.asyncio
async def test_foreign_workflow_and_every_child_path_are_hidden(studio):
    """Neither cached parents nor child revision/operation IDs widen active scope."""
    studio.select_store(STORE_B)
    foreign = await create(studio, key="foreign")
    studio.select_store(STORE_A)
    for suffix in (
        "",
        "/revisions",
        "/revisions/1",
        "/compare?left=1&right=1",
        "/operations/" + foreign["operation_id"],
    ):
        response = await studio.request(
            "GET", "/workflows/" + foreign["id"] + suffix
        )
        assert response.status_code == 404, (suffix, response.text)
    for operation, payload in (
        ("validate", {}),
        ("publish", {}),
        (
            "restore",
            {
                "operation_id": str(uuid4()),
                "expected_revision": 1,
                "revision": 1,
            },
        ),
    ):
        response = await studio.request(
            "POST", f'/workflows/{foreign["id"]}/{operation}', payload=payload
        )
        assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_selected_read_store_does_not_become_a_write_owner(studio):
    """Multi-Store reads remain useful while noncurrent writes return409 before mutation."""
    studio.select_store(STORE_B)
    foreign = await create(studio, key="selected")
    studio.select_store(STORE_A)
    studio.db.add(
        ShopAdminSessionStore(session_id=studio.session_id, store_id=STORE_B)
    )
    studio.db.commit()
    assert (
        await studio.request("GET", "/workflows/" + foreign["id"])
    ).status_code == 200
    denied = await studio.request(
        "PATCH", "/workflows/" + foreign["id"], payload=update(foreign)
    )
    assert (
        denied.status_code == 409
        and denied.json()["detail"] == "store_switch_required"
    )


@pytest.mark.asyncio
async def test_assignment_and_media_ownership_are_checked_before_save(studio):
    """Definitions cannot smuggle another Store's Bot or private ProductMedia ID."""
    first = await create(studio)
    definition = document()
    definition["assignment"] = {"mode": "selected", "bot_ids": [BOT_B]}
    denied = await studio.request(
        "PATCH",
        "/workflows/" + first["id"],
        payload=update(first, definition=definition),
    )
    assert (
        denied.status_code == 422
        and denied.json()["detail"] == "workflow_bot_not_available"
    )
    from models.shop_uom import default_unit_id
    from services.shop_uom import seed_store_units

    seed_store_units(studio.db, STORE_B)
    product = Product(
        store_id=STORE_B,
        name="Private",
        sku="private",
        description="",
        price=100,
        stock_quantity=1,
        uom_id=default_unit_id(STORE_B),
    )
    studio.db.add(product)
    studio.db.flush()
    media = ProductMedia(
        product_id=product.id,
        kind="photo",
        storage_key="private.jpg",
        original_filename="private.jpg",
        mime_type="image/jpeg",
        size_bytes=10,
    )
    studio.db.add(media)
    studio.db.commit()
    definition = document()
    definition["nodes"].insert(
        1,
        {
            "id": "photo",
            "type": "send_photo",
            "config": {"media_id": media.id},
        },
    )
    denied = await studio.request(
        "PATCH",
        "/workflows/" + first["id"],
        payload=update(first, definition=definition),
    )
    assert (
        denied.status_code == 422
        and denied.json()["detail"] == "workflow_media_not_available"
    )
    studio.db.get(ShopBot, BOT_A).status = "disabled"
    studio.db.commit()
    definition = document()
    definition["assignment"] = {"mode": "selected", "bot_ids": [BOT_A]}
    denied = await studio.request(
        "PATCH",
        "/workflows/" + first["id"],
        payload=update(first, definition=definition),
    )
    assert denied.status_code == 422


@pytest.mark.asyncio
async def test_reader_can_inspect_but_not_mutate_or_publish(studio):
    """Role checks apply in addition to Store grants and valid graph state."""
    first = await create(studio)
    studio.db.get(ShopStaff, 7).role = "viewer"
    studio.db.commit()
    assert (
        await studio.request("GET", "/workflows/" + first["id"])
    ).status_code == 200
    assert (
        await studio.request(
            "PATCH", "/workflows/" + first["id"], payload=update(first)
        )
    ).status_code == 403
    studio.db.get(ShopStaff, 7).role = "content"
    studio.db.commit()
    denied = await studio.request(
        "POST", f'/workflows/{first["id"]}/publish', payload={}
    )
    assert (
        denied.status_code == 409
        and denied.json()["detail"] == "workflow_runtime_unavailable"
    )


@pytest.mark.asyncio
async def test_duplicate_archive_delete_and_restore_are_versioned(studio):
    """Draft lifecycle changes retain history rather than deleting customer data."""
    first = await create(studio)
    duplicate = await studio.request(
        "POST",
        f'/workflows/{first["id"]}/duplicate',
        payload={
            "id": str(uuid4()),
            "operation_id": str(uuid4()),
            "name": "رونوشت",
            "key": "copy",
        },
    )
    assert (
        duplicate.status_code == 201 and duplicate.json()["id"] != first["id"]
    )
    archived = await studio.request(
        "POST",
        f'/workflows/{first["id"]}/archive',
        payload={
            "operation_id": str(uuid4()),
            "expected_revision": 1,
        },
    )
    assert (
        archived.status_code == 200 and archived.json()["status"] == "archived"
    )
    deleted = await studio.request(
        "DELETE",
        "/workflows/" + first["id"],
        payload={
            "operation_id": str(uuid4()),
            "expected_revision": 2,
        },
    )
    assert deleted.status_code == 200 and deleted.json()["status"] == "deleted"
    recovered = await studio.request(
        "POST",
        f'/workflows/{first["id"]}/restore',
        payload={
            "operation_id": str(uuid4()),
            "expected_revision": 3,
            "revision": 1,
        },
    )
    assert (
        recovered.status_code == 200 and recovered.json()["status"] == "draft"
    )
    assert recovered.json()["revision"] == 4


@pytest.mark.asyncio
async def test_structural_errors_and_body_limits_do_not_append_revisions(
    studio,
):
    """Malformed definitions fail closed without leaking raw validation inputs."""
    first = await create(studio)
    invalid = document() | {
        "runtime_state": {"admin_password": "should-not-echo"}
    }
    denied = await studio.request(
        "PATCH",
        "/workflows/" + first["id"],
        payload=update(first, definition=invalid),
    )
    assert denied.status_code == 422 and "should-not-echo" not in denied.text
    huge = await studio.request(
        "PATCH",
        "/workflows/" + first["id"],
        payload=update(first, description="x" * 300_000),
    )
    assert huge.status_code == 413
    loaded = await studio.request("GET", "/workflows/" + first["id"])
    assert loaded.json()["revision"] == 1


@pytest.mark.asyncio
async def test_revisions_cannot_be_updated_through_the_orm(studio):
    """Immutable revision evidence survives ordinary application write paths."""
    from models.shop_workflow import ShopWorkflowRevision

    first = await create(studio)
    row = studio.db.scalar(
        select(ShopWorkflowRevision).where(
            ShopWorkflowRevision.workflow_id == first["id"]
        )
    )
    row.snapshot_json = "{}"
    with pytest.raises(ValueError, match="workflow_revision_immutable"):
        studio.db.flush()
    studio.db.rollback()


@pytest.mark.asyncio
async def test_duplicate_receipt_is_bound_to_the_source_workflow(studio):
    """Reusing one copy operation for another source must conflict, not return the first copy."""
    first = await create(studio)
    second = await create(studio, key="second")
    payload = {
        "id": str(uuid4()),
        "operation_id": str(uuid4()),
        "name": "رونوشت",
        "key": "copied",
    }
    copied = await studio.request(
        "POST", f'/workflows/{first["id"]}/duplicate', payload=payload
    )
    assert copied.status_code == 201, copied.text
    wrong = await studio.request(
        "POST", f'/workflows/{second["id"]}/duplicate', payload=payload
    )
    assert (
        wrong.status_code == 409
        and wrong.json()["detail"] == "workflow_operation_conflict"
    )


@pytest.mark.asyncio
async def test_shared_service_rejects_unvalidated_future_mcp_payload(studio):
    """The HTTP model cannot be the only place that enforces the portable contract."""
    from services.shop_store_context import resolve_context
    from services import shop_admin_security as security
    from services.shop_workflows import create_draft

    adapter = AsyncDb(studio.db)
    scope = await resolve_context(
        adapter, staff_id=7, session_id=studio.session_id
    )
    with pytest.raises(
        security.SecurityRejected, match="workflow_invalid_request"
    ):
        await create_draft(
            adapter,
            scope=scope,
            actor=studio.db.get(ShopStaff, 7),
            payload=creation(key="arbitrary.key"),
        )


@pytest.mark.asyncio
async def test_uppercase_uuid_request_remains_readable_through_uuid_routes(
    studio,
):
    """Canonical identity formatting prevents a saved draft from becoming unreachable."""
    first = await create(studio, id=str(uuid4()).upper())
    loaded = await studio.request("GET", "/workflows/" + first["id"])
    assert loaded.status_code == 200, loaded.text


@pytest.mark.asyncio
async def test_read_only_membership_can_validate_without_appending_a_revision(
    studio,
):
    """Pure validation needs read access, even though it uses a POST request body."""
    from models.shop_staff_store import ShopStaffStoreAccess

    first = await create(studio)
    grant = studio.db.scalar(
        select(ShopStaffStoreAccess).where(
            ShopStaffStoreAccess.staff_id == 7,
            ShopStaffStoreAccess.store_id == STORE_A,
        )
    )
    grant.access_level = "viewer"
    studio.db.get(ShopStaff, 7).role = "viewer"
    studio.db.commit()
    result = await studio.request(
        "POST",
        f'/workflows/{first["id"]}/validate',
        payload={"definition": document()},
    )
    assert result.status_code == 200 and result.json()["valid"]
    assert (await studio.request("GET", "/workflows/" + first["id"])).json()[
        "revision"
    ] == 1
