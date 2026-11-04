"""Verify Store ownership before legacy catalog policy mutations start."""

from __future__ import annotations

import pytest

from models.shop_checkout import ShopCoupon, ShopShippingMethod
from models.shop_content import ShopCategory
from models.shop_staff import ShopStaff
from tests.test_campaign_admin_store_scope import (
    STORE_A, STORE_B, campaign_app,
)


@pytest.fixture
def catalog_policy_app(campaign_app):
    """Reuse the real signed middleware and disposable database transaction."""
    return campaign_app


def policy_record(app, kind: str, *, store_id: str):
    """Persist an editable policy with its actual role and request payload."""
    if kind == "categories":
        record = ShopCategory(store_id=store_id, name="Original category")
        role, field = "content", "name"
        payload = {"name": "Updated category"}
    elif kind == "shipping":
        record = ShopShippingMethod(
            store_id=store_id, name="Original shipping", price_irr=100,
        )
        role, field = "sales", "name"
        payload = {"name": "Updated shipping", "price_irr": 200}
    else:
        record = ShopCoupon(
            store_id=store_id, code="ORIGINAL", discount_type="fixed", value=100,
        )
        role, field = "marketing", "code"
        payload = {"code": "UPDATED", "discount_type": "fixed", "value": 200}
    app.db.get(ShopStaff, 7).role = role
    app.db.add(record)
    app.db.commit()
    return record, field, payload


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["categories", "shipping", "coupons"])
async def test_selected_read_store_policy_requires_switch(catalog_policy_app, kind):
    """Another selected Store returns 409 before changing or flushing its row."""
    app = catalog_policy_app
    record, field, payload = policy_record(app, kind, store_id=STORE_B)
    original = getattr(record, field)
    response = await app.request(
        "PATCH", f"/{kind}/{record.id}", payload=payload,
        raise_app_exceptions=False,
    )
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "store_switch_required"}
    app.db.rollback()
    app.db.refresh(record)
    assert getattr(record, field) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["categories", "shipping", "coupons"])
async def test_unselected_policy_is_hidden_even_if_cached(catalog_policy_app, kind):
    """A cached policy cannot bypass the active Store filter or leak ownership."""
    app = catalog_policy_app
    record, field, payload = policy_record(app, kind, store_id=STORE_B)
    original = getattr(record, field)
    app.select_store(STORE_A)
    response = await app.request(
        "PATCH", f"/{kind}/{record.id}", payload=payload,
        raise_app_exceptions=False,
    )
    assert response.status_code == 404, response.text
    app.db.rollback()
    app.db.refresh(record)
    assert getattr(record, field) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["categories", "shipping", "coupons"])
async def test_current_store_policy_remains_editable(catalog_policy_app, kind):
    """The same signed route still persists authorized current-Store edits."""
    app = catalog_policy_app
    record, field, payload = policy_record(app, kind, store_id=STORE_A)
    response = await app.request("PATCH", f"/{kind}/{record.id}", payload=payload)
    assert response.status_code == 200, response.text
    app.db.refresh(record)
    assert getattr(record, field) == payload[field]
