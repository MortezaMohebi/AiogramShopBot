"""Store-scoped management of reusable catalog attributes and terms."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Exists

from models.shop_multibot import ShopStore
from models.shop_product_attribute import (
    ShopAttribute, ShopAttributeValue, ShopProductAttribute, ShopProductAttributeValue,
)
from services.shop_attribute_identity import definition_signature_v1, term_signature_v1
from services.shop_product_attributes import _Label, _label

CatalogKind = Literal["attributes", "values"]
PAGE_SIZE = 25
_PERSIAN_VARIANTS = str.maketrans("يك٠١٢٣٤٥٦٧٨٩0123456789", "یک۰۱۲۳۴۵۶۷۸۹۰۱۲۳۴۵۶۷۸۹")
_ARABIC_VARIANTS = str.maketrans("یک۰۱۲۳۴۵۶۷۸۹", "يك٠١٢٣٤٥٦٧٨٩")
_LATIN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


class CatalogSpecPayload(BaseModel):
    """Editable fields; connector identity is deliberately not editable here."""

    model_config = ConfigDict(extra="forbid", strict=True)
    label: _Label
    unit: Annotated[str, Field(min_length=1, max_length=24), AfterValidator(_label)] | None = None
    aliases: list[_Label] = Field(default_factory=list, max_length=6)
    definition_id: int | None = Field(default=None, gt=0, le=2147483647)


class CatalogSpecError(ValueError):
    """A stable, safe error for catalog administration."""

    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.status = status


def _used(kind: CatalogKind) -> Exists:
    if kind == "attributes":
        return select(ShopProductAttribute.id).where(
            ShopProductAttribute.definition_id == ShopAttribute.id,
        ).exists()
    return select(ShopProductAttributeValue.id).where(
        ShopProductAttributeValue.value_id == ShopAttributeValue.id,
    ).exists()


def _data(row: ShopAttribute | ShopAttributeValue, used: bool, parent: str | None = None) -> dict:
    data = {"id": row.id, "label": row.label, "used": used}
    if isinstance(row, ShopAttribute):
        return {**data, "unit": row.unit, "aliases": row.aliases}
    return {**data, "definition_id": row.definition_id, "attribute_label": parent}


async def list_catalog_specs(
    db: AsyncSession, store_id: str, kind: CatalogKind, query: str, page: int,
    definition_id: int | None,
) -> dict:
    """Search one Store; term searches can be limited to the selected definition."""
    if kind == "attributes":
        model = ShopAttribute
        stmt = select(model, _used(kind)).where(model.store_id == store_id)
    else:
        model = ShopAttributeValue
        stmt = select(model, _used(kind), ShopAttribute.label).join(
            ShopAttribute, ShopAttribute.id == model.definition_id,
        ).where(ShopAttribute.store_id == store_id)
        if definition_id is not None:
            stmt = stmt.where(model.definition_id == definition_id)
    if query.strip():
        query = query.strip()
        persian = query.translate(_PERSIAN_VARIANTS)
        variants = {query, persian, persian.translate(_LATIN_DIGITS), persian.translate(_ARABIC_VARIANTS)}
        patterns = [
            "%" + part.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
            for part in sorted(variants)
        ]
        fields = [model.label]
        if kind == "attributes":
            fields.append(ShopAttribute.unit)
        elif definition_id is None:
            fields.append(ShopAttribute.label)
        stmt = stmt.where(or_(*(field.ilike(pattern, escape="!") for field in fields for pattern in patterns)))
    results = (await db.execute(stmt.order_by(model.label, model.id).offset(
        (page - 1) * PAGE_SIZE,
    ).limit(PAGE_SIZE + 1))).all()
    return {"items": [_data(*row) for row in results[:PAGE_SIZE]], "has_more": len(results) > PAGE_SIZE}


async def change_catalog_spec(
    db: AsyncSession, store_id: str, kind: CatalogKind, item_id: int | None,
    payload: CatalogSpecPayload | None,
) -> dict:
    """Create, update, or remove a record under the catalog's product-write lock."""
    await db.scalar(select(ShopStore.id).where(ShopStore.id == store_id).with_for_update())
    if kind == "attributes":
        stmt = select(ShopAttribute, _used(kind)).where(
            ShopAttribute.store_id == store_id, ShopAttribute.id == item_id,
        )
    else:
        stmt = select(ShopAttributeValue, _used(kind), ShopAttribute.label).join(
            ShopAttribute, ShopAttribute.id == ShopAttributeValue.definition_id,
        ).where(ShopAttribute.store_id == store_id, ShopAttributeValue.id == item_id)
    result = (await db.execute(stmt)).one_or_none() if item_id is not None else None
    if item_id is not None and result is None:
        raise CatalogSpecError("not_found", 404)
    row = result[0] if result else None
    used = result[1] if result else False
    parent_label = result[2] if result and kind == "values" else None
    if payload is None:
        if used:
            raise CatalogSpecError("catalog_spec_in_use", 409)
        await db.delete(row)
    elif kind == "attributes":
        if payload.definition_id is not None:
            raise CatalogSpecError("invalid_catalog_spec", 422)
        if row is None:
            row = ShopAttribute(store_id=store_id, external_ids={})
            db.add(row)
        row.label, row.unit, row.aliases = payload.label, payload.unit, payload.aliases
        row.signature = definition_signature_v1(row.label, row.unit, row.aliases, row.external_ids)
    else:
        if payload.unit is not None or payload.aliases:
            raise CatalogSpecError("invalid_catalog_spec", 422)
        if row is not None and payload.definition_id not in (None, row.definition_id):
            raise CatalogSpecError("catalog_term_parent_fixed", 409)
        if row is None:
            parent = await db.scalar(select(ShopAttribute).where(
                ShopAttribute.store_id == store_id, ShopAttribute.id == payload.definition_id,
            ))
            if parent is None:
                raise CatalogSpecError("invalid_catalog_spec", 422)
            parent_label = parent.label
            row = ShopAttributeValue(definition_id=parent.id, external_ids={})
            db.add(row)
        row.label = payload.label
        row.signature = term_signature_v1(row.label, row.external_ids)
    try:
        await db.flush()
        data = _data(row, used, parent_label) if payload is not None else {"deleted": True}
        await db.commit()
        return data
    except IntegrityError:
        await db.rollback()
        code = "catalog_spec_in_use" if payload is None else "catalog_spec_conflict"
        raise CatalogSpecError(code, 409) from None
