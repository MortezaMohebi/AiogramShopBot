"""Prove content child rows inherit their Product's trusted Store ownership.

Requests use real signed session middleware and disposable database/files.
Denied mutations must preserve both the row and its private original.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from models.shop_content import Product, ProductMedia
from models.shop_content import Testimonial as ProductTestimonial
from models.shop_multibot import DEFAULT_STORE_ID
from models.shop_product_visibility import ShopProductVisibility
from models.shop_staff import ShopStaff
from models.shop_uom import default_unit_id
from services.shop_uom import seed_store_units
from tests.test_campaign_admin_store_scope import (
    PNG, STORE_A, STORE_B, campaign_app,
)


@pytest.fixture
def media_app(campaign_app):
    """Use a content editor with explicit Store memberships, without MFA."""
    campaign_app.db.get(ShopStaff, 7).role = "content"
    for store_id in (STORE_A, STORE_B, DEFAULT_STORE_ID):
        seed_store_units(campaign_app.db, store_id)
    campaign_app.db.commit()
    return campaign_app


def asset(app, directory, kind, *, store_id=STORE_B):
    """Create an actual Product-owned child and its isolated private file."""
    suffix = uuid4().hex
    product = Product(
        store_id=store_id, sku=suffix, name="محصول آزمایشی",
        description="شرح", price=100, uom_id=default_unit_id(store_id),
    )
    app.db.add(product)
    app.db.flush()
    key = suffix + ".png"
    if kind == "product":
        row = ProductMedia(
            product_id=product.id, storage_key=key, original_filename="fixture.png",
            mime_type="image/png", size_bytes=len(PNG), kind="photo",
            caption="متن اصلی", is_published=False,
        )
    else:
        row = ProductTestimonial(
            product_id=product.id, text="متن اصلی", media_storage_key=key,
            media_kind="photo", media_mime_type="image/png", is_approved=False,
        )
    app.db.add(row)
    app.db.commit()
    path = directory / key
    path.write_bytes(PNG)
    return product, row, path


def resource(kind, row_id):
    """Resolve only the two actual content mutation contracts."""
    return f"/media/{row_id}" if kind == "product" else f"/testimonials/{row_id}"


def patch(kind):
    """Return a deliberate metadata edit for the selected content model."""
    field = "caption" if kind == "product" else "text"
    return {field: "تغییر غیرمجاز"}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["product", "testimonial"])
async def test_private_preview_denies_unselected_product_store(
    media_app, tmp_path, kind,
):
    """A child cached before the request cannot bypass its Product's Store."""
    _, row, path = asset(media_app, tmp_path, kind)
    media_app.select_store(STORE_A)
    response = await media_app.request("GET", f"/media/preview/{kind}/{row.id}")
    assert response.status_code == 404, response.text
    assert path.read_bytes() == PNG


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["product", "testimonial"])
async def test_private_preview_allows_another_active_read_store(
    media_app, tmp_path, kind,
):
    """The active Store set permits reads without granting write ownership."""
    _, row, _ = asset(media_app, tmp_path, kind)
    response = await media_app.request("GET", f"/media/preview/{kind}/{row.id}")
    assert response.status_code == 200, response.text
    assert response.content == PNG


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["product", "testimonial"])
@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
async def test_default_store_cannot_mutate_foreign_content(
    media_app, tmp_path, kind, method,
):
    """The legacy default Store cannot update or delete another Store's child."""
    _, row, path = asset(media_app, tmp_path, kind)
    media_app.select_store(DEFAULT_STORE_ID)
    response = await media_app.request(method, resource(kind, row.id),
                                       payload=patch(kind))
    assert response.status_code == 404, response.text
    persisted = media_app.db.get(type(row), row.id)
    assert persisted is not None
    assert (persisted.caption if kind == "product" else persisted.text) == "متن اصلی"
    assert path.read_bytes() == PNG


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["product", "testimonial"])
@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
async def test_read_selected_store_cannot_become_content_write_owner(
    media_app, tmp_path, kind, method,
):
    """A second selected Store requires an explicit switch before any write."""
    _, row, path = asset(media_app, tmp_path, kind)
    response = await media_app.request(method, resource(kind, row.id),
                                       payload=patch(kind))
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "store_switch_required"
    assert media_app.db.get(type(row), row.id) is not None
    assert path.read_bytes() == PNG


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["product", "testimonial"])
@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
async def test_current_store_can_mutate_its_content(media_app, tmp_path, kind, method):
    """Ownership enforcement preserves normal per-Store editor operations."""
    _, row, path = asset(media_app, tmp_path, kind, store_id=STORE_A)
    response = await media_app.request(method, resource(kind, row.id),
                                       payload=patch(kind))
    assert response.status_code == 200, response.text
    persisted = media_app.db.get(type(row), row.id)
    if method == "DELETE":
        assert persisted is None
        assert not path.exists()
    else:
        value = persisted.caption if kind == "product" else persisted.text
        assert value == "تغییر غیرمجاز"
        assert path.read_bytes() == PNG


@pytest.mark.asyncio
async def test_product_media_editor_does_not_trust_cached_parent(media_app, tmp_path):
    """A cached Product cannot authorize the private child editor read."""
    product, _, _ = asset(media_app, tmp_path, "product")
    media_app.select_store(STORE_A)
    response = await media_app.request("GET", f"/products/{product.id}/media")
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["product", "testimonial"])
async def test_upload_uses_current_product_store(media_app, tmp_path, kind):
    """A child derives ownership from its authorized Product, never a form ID."""
    product, _, _ = asset(media_app, tmp_path, kind, store_id=STORE_A)
    response = await media_app.request(
        "POST", f"/upload/{kind}", file=True,
        fields={"product_id": str(product.id), "caption": "رسانه جدید"},
    )
    assert response.status_code == 201, response.text
    model = ProductMedia if kind == "product" else ProductTestimonial
    created = media_app.db.get(model, response.json()["id"])
    assert created.product_id == product.id
    assert (created.is_published if kind == "product" else created.is_approved) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["product", "testimonial"])
async def test_upload_cannot_target_another_selected_store(media_app, tmp_path, kind):
    """A forged parent in another active read Store never receives a file."""
    product, _, path = asset(media_app, tmp_path, kind)
    before = set(tmp_path.iterdir())
    response = await media_app.request(
        "POST", f"/upload/{kind}", file=True,
        fields={"product_id": str(product.id), "caption": "رسانه غیرمجاز"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "store_switch_required"
    assert set(tmp_path.iterdir()) == before
    assert path.read_bytes() == PNG


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", [True, False])
async def test_visibility_only_edit_requires_current_product_store(
    media_app, tmp_path, selected,
):
    """A visibility child edit cannot bypass the unchanged Product's owner."""
    product, _, _ = asset(media_app, tmp_path, "product")
    if not selected:
        media_app.select_store(STORE_A)
    response = await media_app.request(
        "PATCH", f"/products/{product.id}", payload={"show_stock": False},
    )
    assert response.status_code == (409 if selected else 404), response.text
    assert media_app.db.get(ShopProductVisibility, product.id) is None


@pytest.mark.asyncio
async def test_current_store_can_edit_product_visibility(media_app, tmp_path):
    """An authorized child-only edit preserves the ordinary product record."""
    product, _, _ = asset(media_app, tmp_path, "product", store_id=STORE_A)
    response = await media_app.request(
        "PATCH", f"/products/{product.id}", payload={"show_stock": False},
    )
    assert response.status_code == 200, response.text
    assert media_app.db.get(ShopProductVisibility, product.id).show_stock is False
