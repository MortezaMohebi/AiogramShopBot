"""Prove content child rows inherit their Product's trusted Store ownership.

Requests use real signed session middleware and disposable database/files.
Denied mutations must preserve both the row and its private original.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from models.shop_content import Product, ProductMedia, ShopCategory
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


@pytest.mark.asyncio
async def test_product_editor_pager_matches_the_catalog_across_pages(media_app):
    products = [
        Product(store_id=STORE_A, sku=f"item-{index}", name="Pager sample", description="",
                price=100, uom_id=default_unit_id(STORE_A))
        for index in range(82)
    ]
    # Keep the oldest result in the search via SKU only.
    products[0].sku, products[0].name = "pager-sku", "Other name"
    excluded = Product(store_id=STORE_A, sku="other", name="Other", description="",
                       price=100, uom_id=default_unit_id(STORE_A))
    foreign = Product(store_id=STORE_B, sku="pager-foreign", name="Pager foreign", description="",
                      price=100, uom_id=default_unit_id(STORE_B))
    media_app.db.add_all([*products, excluded, foreign])
    media_app.db.commit()
    media_app.select_store(STORE_A)
    request = media_app.request

    first = await request("GET", "/products?search=pager")
    second = await request("GET", "/products?page=2&search=pager")
    assert first.json()["page_size"] == 80 and len(first.json()["items"]) == 80
    assert len(second.json()["items"]) == 2
    ids = [row["id"] for response in (first, second) for row in response.json()["items"]]
    assert ids == [row.id for row in reversed(products)]
    for index in (0, 79, 80, 81):
        current = await request("GET", f"/products/{ids[index]}?list_search=pager")
        assert current.status_code == 200, current.text
        assert current.json().get("navigation") == {
            "position": index + 1, "total": 82,
            "previous_id": ids[index - 1] if index > 0 else None,
            "next_id": ids[index + 1] if index < 81 else None,
            "page": index // 80 + 1,
        }
    assert (await request("GET", f"/products/{excluded.id}?list_search=pager")).json()["navigation"] is None
    direct = (await request("GET", f"/products/{excluded.id}?list_search=")).json()["navigation"]
    assert direct["position"] == 1 and direct["total"] == 83 and direct["next_id"] == ids[0]
    assert (await request("GET", f"/products/{foreign.id}?list_search=pager")).status_code == 404


@pytest.mark.asyncio
async def test_product_media_order_rejects_stale_or_foreign_rows(media_app, tmp_path):
    product, first, _ = asset(media_app, tmp_path, "product", store_id=STORE_A)
    _, foreign, _ = asset(media_app, tmp_path, "product")
    second = ProductMedia(
        product_id=product.id, storage_key=uuid4().hex + ".png",
        original_filename="second.png", mime_type="image/png", size_bytes=len(PNG),
        kind="photo", position=3, is_published=True,
    )
    media_app.db.add(second)
    media_app.db.commit()
    url = f"/products/{product.id}/media"
    original = [first.id, second.id]
    new = list(reversed(original))
    saved = await media_app.request("POST", url + "/order", payload={"expected": original, "ids": new})
    assert saved.status_code == 200, saved.text
    for expected, ids in ((original, new), (new, [second.id, foreign.id])):
        rejected = await media_app.request("POST", url + "/order", payload={"expected": expected, "ids": ids})
        assert rejected.status_code in (409, 422), rejected.text
    rows = (await media_app.request("GET", url)).json()["items"]
    assert [row["id"] for row in rows] == new
    assert [row["is_published"] for row in rows] == [True, False]


@pytest.mark.asyncio
async def test_category_order_changes_current_store_only(media_app):
    first, second, foreign = [
        ShopCategory(name=name, store_id=store_id, position=position)
        for name, store_id, position in (("one", STORE_A, 1), ("two", STORE_A, 2), ("three", STORE_B, 80))
    ]
    media_app.db.add_all([first, second, foreign])
    media_app.db.commit()
    expected = [first.id, second.id]
    denied = await media_app.request("POST", "/categories/order", payload={
        "expected": expected, "ids": [second.id, foreign.id],
    })
    assert denied.status_code == 422, denied.text
    saved = await media_app.request("POST", "/categories/order", payload={
        "expected": expected, "ids": expected[::-1],
    })
    assert saved.status_code == 200, saved.text
    assert [row["id"] for row in (await media_app.request("GET", "/categories")).json()
            if row["store_id"] == STORE_A] == expected[::-1]
    media_app.db.refresh(foreign)
    assert foreign.position == 80


@pytest.mark.asyncio
async def test_category_hierarchy_rejects_cycles_and_foreign_parents(media_app):
    root = ShopCategory(name="Root", store_id=STORE_A)
    foreign = ShopCategory(name="Other Store", store_id=STORE_B)
    media_app.db.add_all([root, foreign])
    media_app.db.commit()
    root_id, foreign_id = root.id, foreign.id

    created = await media_app.request("POST", "/categories", payload={
        "name": "Child", "parent_id": root_id,
    })
    assert created.status_code == 201, created.text
    child_id = created.json()["id"]
    for category_id, invalid_parent in (
        (root_id, child_id), (child_id, child_id), (child_id, foreign_id),
    ):
        denied = await media_app.request("PATCH", f"/categories/{category_id}", payload={
            "parent_id": invalid_parent,
        })
        assert denied.status_code == 422, denied.text

    categories = (await media_app.request("GET", "/categories")).json()
    parents = {row["id"]: row["parent_id"] for row in categories}
    assert parents[root_id] is None
    assert parents[child_id] == root_id
    moved = await media_app.request("PATCH", f"/categories/{child_id}", payload={"parent_id": None})
    assert moved.status_code == 200, moved.text
    categories = (await media_app.request("GET", "/categories")).json()
    assert next(row["parent_id"] for row in categories if row["id"] == child_id) is None


@pytest.mark.asyncio
async def test_product_attributes_round_trip_and_survive_partial_updates(media_app, tmp_path):
    product, _, _ = asset(media_app, tmp_path, "product", store_id=STORE_A)
    url = f"/products/{product.id}"
    attributes = [{
        "key": "capacity", "label": "گنجایش", "unit": "ml", "visible": True, "variation": False,
        "aliases": ["حجم"],
        "external_ids": {"odoo:main": "12", "woo:main": "7"},
        "values": [{"label": "۲۵۰", "external_ids": {"odoo:main": "29"}}],
    }]
    assert (await media_app.request("GET", url)).json()["attributes"] == []
    saved = await media_app.request("PATCH", url, payload={"attributes": attributes})
    assert saved.status_code == 200, saved.text
    stored = (await media_app.request("GET", url)).json()["attributes"]
    selection_id = stored[0]["values"][0]["id"]
    assert isinstance(selection_id, int)
    assert stored[0]["aliases"] == ["حجم"]
    assert stored[0]["values"][0]["external_ids"] == {"odoo:main": "29"}
    assert (await media_app.request("PATCH", url, payload={"name": "نام جدید"})).status_code == 200
    rejected = await media_app.request("PATCH", url, payload={"attributes": attributes * 2})
    assert rejected.status_code == 422
    assert (await media_app.request("GET", url)).json()["attributes"] == stored
    stored[0]["values"][0]["label"] = "۳۰۰"
    still_linked = await media_app.request("PATCH", url, payload={"attributes": stored})
    assert still_linked.status_code == 200, still_linked.text
    assert still_linked.json()["attributes"][0]["values"][0]["label"] == "۲۵۰"
    old_term_id = stored[0]["values"][0].pop("value_id")
    updated = await media_app.request("PATCH", url, payload={"attributes": stored})
    assert updated.status_code == 200, updated.text
    value = updated.json()["attributes"][0]["values"][0]
    assert value["label"] == "۳۰۰" and value["id"] == selection_id
    assert value["value_id"] != old_term_id
    assert (await media_app.request("PATCH", url, payload={"attributes": []})).status_code == 200
    assert (await media_app.request("GET", url)).json()["attributes"] == []


@pytest.mark.asyncio
async def test_products_reuse_catalog_attributes_and_values_without_sharing_assignments(media_app, tmp_path):
    first, _, _ = asset(media_app, tmp_path, "product", store_id=STORE_A)
    second, _, _ = asset(media_app, tmp_path, "product", store_id=STORE_A)
    draft = {"key": "size", "label": "حجم", "unit": "ml", "values": [{"label": "۲۵۰"}]}

    async def save(product, attribute):
        response = await media_app.request("PATCH", f"/products/{product.id}", payload={"attributes": [attribute]})
        assert response.status_code == 200, response.text
        return response.json()["attributes"][0]

    one = await save(first, draft)
    two = await save(second, {**draft, "key": "capacity", "visible": False, "values": [{"label": "250"}]})
    assert one["definition_id"] == two["definition_id"]
    assert one["values"][0]["value_id"] == two["values"][0]["value_id"]
    assert one["values"][0]["id"] != two["values"][0]["id"]
    assert one["visible"] and not two["visible"]

    response = await media_app.request("GET", f"/stores/{STORE_A}/product-attribute-options")
    assert response.status_code == 200, response.text
    options = response.json()
    assert options[0]["definition_id"] == one["definition_id"]
    assert options[0]["values"][0]["value_id"] == one["values"][0]["value_id"]

    updated = await save(second, {**draft, "key": "capacity", "values": [{"label": "۵۰۰"}]})
    assert updated["definition_id"] == one["definition_id"]
    assert updated["values"][0]["value_id"] != one["values"][0]["value_id"]
    assert (await media_app.request("GET", f"/products/{first.id}")).json()["attributes"] == [one]


@pytest.mark.asyncio
async def test_catalog_specs_can_be_managed_and_shared_without_detaching_other_products(media_app, tmp_path):
    base = f"/catalog-specs/{STORE_A}"
    attributes, values = base + "/attributes", base + "/values"
    request = media_app.request
    first, _, _ = asset(media_app, tmp_path, "product", store_id=STORE_A)
    second, _, _ = asset(media_app, tmp_path, "product", store_id=STORE_A)

    response = await request("POST", attributes, payload={"label": "گنجایش", "unit": "ml"})
    assert response.status_code == 200, response.text
    definition = response.json()["id"]
    other = (await request("POST", attributes, payload={"label": "رنگ"})).json()["id"]
    response = await request("POST", values, payload={"definition_id": definition, "label": "۲۵۰"})
    assert response.status_code == 200, response.text
    term = response.json()["id"]
    wrong_term = (await request("POST", values, payload={"definition_id": other, "label": "آبی"})).json()["id"]
    duplicate = await request("POST", values, payload={"definition_id": definition, "label": "250"})
    assert duplicate.status_code == 409 and duplicate.json()["detail"] == "catalog_spec_conflict"
    found = await request("GET", f"{attributes}?q=ml")
    assert [row["id"] for row in found.json()["items"]] == [definition]
    found = await request("GET", f"{values}?definition_id={definition}&q=250")
    assert [row["id"] for row in found.json()["items"]] == [term]

    row = {"key": "shared", "definition_id": definition, "label": "متن قدیمی",
           "values": [{"value_id": term, "label": "متن قدیمی"}]}
    for product in (first, second):
        response = await request("PATCH", f"/products/{product.id}", payload={"attributes": [row]})
        assert response.status_code == 200, response.text
        assert response.json()["attributes"][0]["label"] == "گنجایش"
    for bad_values in ([], row["values"] * 2, [{"value_id": wrong_term, "label": "آبی"}]):
        response = await request("PATCH", f"/products/{first.id}",
                                 payload={"attributes": [{**row, "values": bad_values}]})
        assert response.status_code == 422, response.text
    changed = await request("PATCH", f"{values}/{term}", payload={"label": "۳۰۰", "definition_id": definition})
    assert changed.status_code == 200 and changed.json()["used"] is True
    changed = await request("PATCH", f"{attributes}/{definition}", payload={"label": "حجم", "unit": "ml"})
    assert changed.status_code == 200 and changed.json()["used"] is True
    for product in (first, second):
        selected = (await request("GET", f"/products/{product.id}")).json()["attributes"][0]
        assert selected["label"] == "حجم" and selected["definition_id"] == definition
        assert selected["values"][0]["label"] == "۳۰۰" and selected["values"][0]["value_id"] == term
    moved = await request("PATCH", f"{values}/{term}", payload={"label": "۳۰۰", "definition_id": other})
    assert moved.status_code == 409 and moved.json()["detail"] == "catalog_term_parent_fixed"
    for path in (f"{attributes}/{definition}", f"{values}/{term}"):
        denied = await request("DELETE", path)
        assert denied.status_code == 409 and denied.json()["detail"] == "catalog_spec_in_use"
    detached = await request("PATCH", f"/products/{first.id}", payload={"attributes": []})
    assert detached.status_code == 200 and detached.json()["attributes"] == []
    assert (await request("DELETE", f"{values}/{term}")).status_code == 409
    assert (await request("DELETE", f"{values}/{wrong_term}")).json() == {"deleted": True}
    assert (await request("DELETE", f"{attributes}/{other}")).json() == {"deleted": True}


@pytest.mark.asyncio
async def test_catalog_specs_reject_cross_store_ids_and_mutations(media_app, tmp_path):
    request = media_app.request
    store_a = f"/catalog-specs/{STORE_A}"
    store_b = f"/catalog-specs/{STORE_B}"
    assert (await request("POST", store_b + "/attributes", payload={"label": "غیرمجاز"})).status_code in (403, 409)
    media_app.select_store(STORE_B)
    response = await request("POST", store_b + "/attributes", payload={"label": "فروشگاه دوم"})
    assert response.status_code == 200, response.text
    other = response.json()["id"]
    media_app.select_store(STORE_A)
    assert (await request("GET", store_b + "/attributes")).status_code in (403, 404)
    assert (await request("PATCH", f"{store_a}/attributes/{other}", payload={"label": "تغییر"})).status_code == 404
    assert (await request("POST", store_a + "/values", payload={"label": "تغییر", "definition_id": other})).status_code == 422
    product, _, _ = asset(media_app, tmp_path, "product", store_id=STORE_A)
    forged = {"key": "foreign", "definition_id": other, "label": "ویژگی", "values": [{"label": "مقدار"}]}
    assert (await request("PATCH", f"/products/{product.id}", payload={"attributes": [forged]})).status_code == 422
    assert (await request("GET", f"/products/{product.id}")).json()["attributes"] == []
