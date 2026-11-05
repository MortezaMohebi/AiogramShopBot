"""Action Catalog and safe dry-run use actual signed sessions and Store scope."""

import pytest

from dashboard import next_api, shop_action_api
from models.shop_content import Product
from models.shop_multibot import ShopBot
from models.shop_staff import ShopStaff
from models.shop_staff_store import ShopStaffStoreAccess
from models.shop_uom import default_unit_id
from tests.schema_support import seed_test_units
from tests.test_campaign_admin_store_scope import (
    BOT_A,
    BOT_B,
    STORE_A,
    STORE_B,
    campaign_app,
)


class RateRedis:
    """A local Redis counter boundary; HTTP authorization/business services remain real."""

    def __init__(self):
        self.values = {}

    async def eval(self, _script, count, *args):
        keys, limits = args[:count], args[count : count * 2]
        blocked = False
        for key, limit in zip(keys, limits):
            self.values[key] = self.values.get(key, 0) + 1
            blocked = blocked or self.values[key] > int(limit)
        return int(blocked)


@pytest.fixture
def action_app(campaign_app):
    app = campaign_app
    app.db.get(ShopStaff, 7).role = "content"
    for bot_id in (BOT_A, BOT_B):
        app.db.get(ShopBot, bot_id).credential_version = 1
    seed_test_units(app.db)
    app.db.add(
        Product(
            store_id=STORE_A,
            uom_id=default_unit_id(STORE_A),
            name="QA visible product",
            sku="QA-ACTION",
            description="sample",
            price=1200,
            stock_quantity=5,
            is_published=True,
        )
    )
    from models.shop_bot_catalog_acl import ShopBotProductRule

    app.db.flush()
    product = app.db.query(Product).filter_by(store_id=STORE_A).one()
    app.db.add(ShopBotProductRule(bot_id=BOT_A, product_id=product.id, effect="allow"))
    app.db.commit()
    app.app.dependency_overrides[next_api.database] = app.legacy.dependency_overrides[
        next_api.database
    ]
    rate = RateRedis()

    async def redis():
        yield rate

    app.app.dependency_overrides[shop_action_api.rate_client] = redis
    return app


@pytest.mark.asyncio
async def test_real_catalog_lists_versioned_policies_and_context(action_app):
    response = await action_app.request("GET", f"/actions?bot_id={BOT_A}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 19 and data["runtime_available"] is False
    search = next(
        item for item in data["items"] if item["key"] == "catalog.search_products"
    )
    assert search["version"] == "1.0.0" and search["side_effect"] == "read_only"
    assert search["availability"]["available"] and search["can_dry_run"]
    assert (
        "services.shop_" not in response.text
        and "credential_version" not in response.text
    )


@pytest.mark.asyncio
async def test_catalog_filters_and_detail_are_actual_http(action_app):
    filtered = await action_app.request(
        "GET", "/actions?category=cart&side_effect=business_mutation"
    )
    assert filtered.status_code == 200, filtered.text
    assert {item["key"] for item in filtered.json()["items"]} == {
        "cart.add_item",
        "cart.update_quantity",
        "cart.remove_item",
        "cart.clear",
    }
    detail = await action_app.request("GET", "/actions/cart.clear/1.0.0")
    assert detail.status_code == 200
    assert detail.json()["confirmation"] == "customer_confirmation"
    assert detail.json()["idempotency"] == "required"
    unknown = await action_app.request("GET", "/actions/cart.clear/9.0.0")
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_inspection_never_borrows_foreign_bot_from_active_store_set(action_app):
    # Both Stores are visible, but the default inspection owner is current Store A.
    response = await action_app.request("GET", f"/actions?bot_id={BOT_B}")
    assert response.status_code == 404, response.text
    action_app.select_store(STORE_B)
    allowed = await action_app.request("GET", f"/actions?bot_id={BOT_B}")
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_catalog_dry_run_uses_real_acl_without_customer_impersonation(action_app):
    response = await action_app.request(
        "POST",
        "/actions/dry-run",
        payload={
            "action_key": "catalog.search_products",
            "action_version": "1.0.0",
            "bot_id": BOT_A,
            "platform": "telegram",
            "input": {"query": "QA"},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded" and response.json()["dry_run"]
    assert response.json()["output"]["items"][0]["name"] == "QA visible product"
    assert response.json()["execution_receipt"] is None


@pytest.mark.asyncio
async def test_dry_run_does_not_require_write_store_membership(action_app):
    grant = action_app.db.get(ShopStaffStoreAccess, (7, STORE_A))
    grant.access_level = "viewer"
    action_app.db.commit()
    response = await action_app.request(
        "POST",
        "/actions/dry-run",
        payload={
            "action_key": "catalog.search_products",
            "bot_id": BOT_A,
            "platform": "telegram",
            "input": {},
        },
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra", [{"customer_id": 99}, {"approved": True}, {"store_id": STORE_B}]
)
async def test_dry_run_rejects_authority_fields(action_app, extra):
    response = await action_app.request(
        "POST",
        "/actions/dry-run",
        payload={
            "action_key": "catalog.search_products",
            "bot_id": BOT_A,
            "platform": "telegram",
            "input": {},
            **extra,
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_dry_run_cannot_be_used_as_business_execution(action_app):
    response = await action_app.request(
        "POST",
        "/actions/dry-run",
        payload={
            "action_key": "cart.clear",
            "bot_id": BOT_A,
            "platform": "telegram",
            "input": {"expected_cart_revision": 1},
        },
    )
    assert response.status_code == 403, response.text
    assert (
        await action_app.request("POST", "/actions/invoke", payload={})
    ).status_code == 404


@pytest.mark.asyncio
async def test_viewer_can_inspect_but_cannot_read_catalog_business_data(action_app):
    action_app.db.get(ShopStaff, 7).role = "viewer"
    action_app.db.commit()
    catalog = await action_app.request("GET", f"/actions?bot_id={BOT_A}")
    assert catalog.status_code == 200
    assert catalog.json()["can_inspect_data"] is False
    assert all(not item["can_dry_run"] for item in catalog.json()["items"])
    response = await action_app.request(
        "POST",
        "/actions/dry-run",
        payload={
            "action_key": "catalog.search_products",
            "bot_id": BOT_A,
            "platform": "telegram",
            "input": {},
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_dry_run_quota_is_enforced_per_verified_context(action_app):
    payload = {
        "action_key": "catalog.search_products",
        "bot_id": BOT_A,
        "platform": "telegram",
        "input": {},
    }
    for _ in range(15):
        assert (
            await action_app.request("POST", "/actions/dry-run", payload=payload)
        ).status_code == 200
    response = await action_app.request("POST", "/actions/dry-run", payload=payload)
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_platform_identity_and_unknown_query_cannot_be_smuggled(action_app):
    wrong = await action_app.request(
        "POST",
        "/actions/dry-run",
        payload={
            "action_key": "catalog.search_products",
            "bot_id": BOT_A,
            "platform": "bale",
            "input": {},
        },
    )
    assert wrong.status_code == 422
    assert (
        await action_app.request("GET", "/actions?customer_id=99")
    ).status_code == 422


@pytest.mark.asyncio
async def test_workflow_validation_queries_live_action_availability(action_app):
    """Changing Bot commerce flags immediately changes the Workflow validation report."""
    from tests.test_workflow_api import creation
    from tests.test_workflow_action_bindings import graph
    from models.shop_store_commerce import ShopBotCommercePolicy

    created = await action_app.request("POST", "/workflows", payload=creation())
    assert created.status_code == 201, created.text
    target = "/workflows/" + created.json()["id"] + "/validate"
    first = await action_app.request("POST", target, payload={"definition": graph()})
    assert first.status_code == 200, first.text
    assert "action_cart_disabled" in {item["code"] for item in first.json()["issues"]}
    action_app.db.add(ShopBotCommercePolicy(bot_id=BOT_A, cart_enabled=True))
    action_app.db.commit()
    second = await action_app.request("POST", target, payload={"definition": graph()})
    assert "action_cart_disabled" not in {
        item["code"] for item in second.json()["issues"]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["expired", "version_changed"])
async def test_internal_staff_principal_rechecks_session_expiry_and_version(
    action_app, revocation
):
    """Internal callers receive the same session revocation rules as signed HTTP."""
    from datetime import timedelta
    from models.shop_admin_control import AdminSession
    from services.shop_actions.context import staff_principal, refresh_principal
    from services.shop_actions.contracts import ActionRejected
    from services.shop_store_context import resolve_context
    from services import shop_admin_security as security
    from tests.test_campaign_admin_store_scope import AsyncDb

    db = AsyncDb(action_app.db)
    staff = action_app.db.get(ShopStaff, 7)
    scope = await resolve_context(db, staff_id=7, session_id=action_app.session_id)
    principal = await staff_principal(db, scope=scope, actor=staff, bot_id=BOT_A)
    if revocation == "expired":
        action_app.db.get(AdminSession, action_app.session_id).expires_at = (
            security.clock() - timedelta(seconds=1)
        )
    else:
        staff.session_version += 1
    action_app.db.commit()
    with pytest.raises(ActionRejected, match="action_actor_unavailable"):
        await refresh_principal(db, principal)


@pytest.mark.asyncio
async def test_both_proofs_are_required_and_consumed_atomically(action_app):
    """Customer confirmation never substitutes for the verified operator decision."""
    from dataclasses import replace
    from models.shop_action import ShopActionAuthorization
    from models.shop_content import ShopIdentity
    from models.shop_store_commerce import ShopStoreCustomer, ShopBotCommercePolicy
    from services.shop_actions.approvals import issue_authorization
    from services.shop_actions.context import customer_principal, staff_principal
    from services.shop_actions.execution import invoke
    from services.shop_bot_context import resolve_bot_context
    from services.shop_store_context import resolve_context
    from services import shop_admin_security as security
    from channels.contracts import Platform
    from sqlalchemy import select
    from tests.test_campaign_admin_store_scope import AsyncDb
    from tests.test_action_execution import registry, invocation

    action_app.db.get(ShopStaff, 7).role = "superadmin"
    assert security.has_permission("superadmin", "actions.approve")
    action_app.db.add(ShopBotCommercePolicy(bot_id=BOT_A, cart_enabled=True))
    customer = ShopStoreCustomer(store_id=STORE_A, display_name="QA proof owner")
    action_app.db.add(customer)
    action_app.db.flush()
    action_app.db.add(
        ShopIdentity(
            store_id=STORE_A,
            bot_id=BOT_A,
            platform="telegram",
            platform_user_id=202,
            customer_id=customer.id,
        )
    )
    action_app.db.commit()
    db = AsyncDb(action_app.db)
    # AsyncDb used by the signed-HTTP fixture intentionally has no savepoint method.
    from tests.test_shared_cart import AsyncDatabase

    execution_db = AsyncDatabase(action_app.db)
    bot = await resolve_bot_context(
        db, authenticated_bot_id=BOT_A, authenticated_platform=Platform.TELEGRAM
    )
    subject = await customer_principal(db, verified_bot=bot, platform_user_id=202)
    scope = await resolve_context(db, staff_id=7, session_id=action_app.session_id)
    operator = await staff_principal(
        db, scope=scope, actor=action_app.db.get(ShopStaff, 7), bot_id=BOT_A
    )
    product = action_app.db.query(Product).filter_by(store_id=STORE_A).one()
    operation = invocation(product.id)
    catalog = registry(confirmation="both")
    customer_proof = await issue_authorization(
        execution_db,
        subject=subject,
        approver=subject,
        invocation=operation,
        purpose="customer_confirmation",
        registry=catalog,
    )
    partial = operation.model_copy(update={"confirmation_receipt": customer_proof})
    waiting = await invoke(execution_db, subject, partial, registry=catalog)
    assert waiting.status == "pending_approval"
    proof = await execution_db.scalar(select(ShopActionAuthorization))
    assert proof.consumed_invocation_id is None and product.stock_quantity == 5
    operator_proof = await issue_authorization(
        execution_db,
        subject=subject,
        approver=operator,
        invocation=operation,
        purpose="operator_approval",
        registry=catalog,
    )
    completed = await invoke(
        execution_db,
        subject,
        partial.model_copy(update={"approval_receipt": operator_proof}),
        registry=catalog,
    )
    assert completed.status == "succeeded" and completed.output == {"stock": 7}
    proofs = (await execution_db.scalars(select(ShopActionAuthorization))).all()
    assert len(proofs) == 2 and all(
        item.consumed_invocation_id == operation.invocation_id for item in proofs
    )


@pytest.mark.asyncio
async def test_required_customer_context_is_enforced_for_a_staff_principal(action_app):
    """Descriptor context requirements are enforced independently of actor/scopes."""
    from dataclasses import replace
    from uuid import uuid4
    from services.shop_actions.context import staff_principal
    from services.shop_actions.contracts import Invocation
    from services.shop_actions.execution import invoke
    from services.shop_actions.registry import Registry
    from services.shop_store_context import resolve_context
    from tests.test_action_contracts import descriptor, spec
    from tests.test_campaign_admin_store_scope import AsyncDb
    from tests.test_shared_cart import AsyncDatabase

    db = AsyncDb(action_app.db)
    scope = await resolve_context(db, staff_id=7, session_id=action_app.session_id)
    principal = await staff_principal(
        db, scope=scope, actor=action_app.db.get(ShopStaff, 7), bot_id=BOT_A
    )
    registry = Registry()
    registry.register(
        replace(
            spec(), descriptor=descriptor(required_context=["store", "bot", "customer"])
        )
    )
    result = await invoke(
        AsyncDatabase(action_app.db),
        principal,
        Invocation(
            invocation_id=str(uuid4()),
            action_key="catalog.search_products",
            input={"query": "QA"},
        ),
        registry=registry,
    )
    assert result.status == "failed" and result.error.code == "action_context_required"
