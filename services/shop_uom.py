"""Unit registry and conversion policy for registered Stores.

Every Store receives its own deterministic base units. No conversion may
cross categories or Stores. The current checkout accepts integral quantities
only; product sale units therefore represent one indivisible sellable unit.
"""

from __future__ import annotations

import re
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from models.shop_content import Product
from models.shop_multibot import ShopStore
from models.shop_uom import ShopUom, ShopUomCategory, default_unit_id
from services import shop_admin_security as security
from services.shop_store_context import current_context

_CODE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_SEED = (
    ("count", "تعداد", "piece", "عدد", "عدد", 1, 1, True),
    ("count", "تعداد", "dozen", "دوجین", "دوجین", 12, 1, False),
    ("mass", "جرم", "kg", "کیلوگرم", "kg", 1, 1, True),
    ("mass", "جرم", "g", "گرم", "g", 1, 1000, False),
    ("volume", "حجم", "l", "لیتر", "L", 1, 1, True),
    ("volume", "حجم", "ml", "میلی‌لیتر", "mL", 1, 1000, False),
    ("length", "طول", "m", "متر", "m", 1, 1, True),
    ("length", "طول", "cm", "سانتی‌متر", "cm", 1, 100, False),
)


def _id(store_id: str, value: str) -> str:
    """Compute stable identifiers to avoid duplicate units on retry."""
    return str(uuid5(NAMESPACE_URL, f"aiogramshopbot:uom:{store_id}:{value}"))


def seed_store_units(db: Session, store_id: str) -> None:
    """Create base catalog units for a new Store without network activity."""
    categories_seen: set[str] = set()
    for category_code, label, code, name, symbol, num, den, reference in _SEED:
        category_id = _id(store_id, f"category:{category_code}")
        if category_id not in categories_seen and db.get(
            ShopUomCategory, category_id,
        ) is None:
            db.add(ShopUomCategory(
                id=category_id, store_id=store_id,
                code=category_code, name=label,
            ))
        categories_seen.add(category_id)
        unit_id = default_unit_id(store_id) if code == "piece" else _id(
            store_id, f"unit:{code}",
        )
        if db.get(ShopUom, unit_id) is None:
            db.add(ShopUom(
                id=unit_id, store_id=store_id, category_id=category_id,
                code=code, name=name, symbol=symbol,
                ratio_num=num, ratio_den=den, is_reference=reference,
                rounding=Decimal("1"),
            ))


async def list_units(
    db: AsyncSession, *, store_id: str,
) -> dict:
    """Return only the requested Store's non-secret UoM metadata."""
    scope = current_context()
    if scope:
        scope.require(store_id)
    rows = (await db.scalars(select(ShopUom).where(
        ShopUom.store_id == store_id,
    ).order_by(ShopUom.category_id, ShopUom.code).limit(1000))).all()
    categories = (await db.scalars(select(ShopUomCategory).where(
        ShopUomCategory.store_id == store_id,
    ).order_by(ShopUomCategory.code))).all()
    return {
        "store_id": store_id,
        "categories": [{
            "id": row.id, "code": row.code, "name": row.name,
        } for row in categories],
        "items": [{
            "id": row.id, "code": row.code, "name": row.name,
            "symbol": row.symbol, "category_id": row.category_id,
            "ratio_num": row.ratio_num, "ratio_den": row.ratio_den,
            "rounding": str(row.rounding),
            "reference": row.is_reference, "active": row.active,
        } for row in rows],
    }


async def create_category(
    db: AsyncSession, *, store_id: str, code: str, name: str,
    base_code: str, base_name: str, base_symbol: str,
) -> dict:
    """Define a new conversion dimension together with its reference unit."""
    scope = current_context()
    if scope:
        scope.require(store_id, manage=True)
    if (
        not _CODE.fullmatch(code) or not _CODE.fullmatch(base_code)
        or not 1 <= len(name.strip()) <= 120
        or not 1 <= len(base_name.strip()) <= 120
        or not 1 <= len(base_symbol.strip()) <= 24
    ):
        raise security.SecurityRejected("invalid_uom", 422)
    category_id = _id(store_id, f"category:{code}")
    unit_id = _id(store_id, f"unit:{base_code}")
    if await db.scalar(select(ShopUomCategory.id).where(
        ShopUomCategory.store_id == store_id,
        ShopUomCategory.code == code,
    )) or await db.scalar(select(ShopUom.id).where(
        ShopUom.store_id == store_id, ShopUom.code == base_code,
    )):
        raise security.SecurityRejected("uom_already_exists", 409)
    if await db.get(ShopStore, store_id) is None:
        raise security.SecurityRejected("store_not_found", 404)
    db.add(ShopUomCategory(
        id=category_id, store_id=store_id, code=code, name=name.strip(),
    ))
    db.add(ShopUom(
        id=unit_id, store_id=store_id, category_id=category_id,
        code=base_code, name=base_name.strip(),
        symbol=base_symbol.strip(), is_reference=True,
        ratio_num=1, ratio_den=1, rounding=Decimal("1"),
    ))
    await db.commit()
    return {"category_id": category_id, "reference_unit_id": unit_id}


async def create_unit(
    db: AsyncSession, *, store_id: str, category_id: str, code: str,
    name: str, symbol: str, ratio_num: int, ratio_den: int,
    rounding: Decimal,
) -> dict:
    """Register one non-reference unit only inside its own Store/dimension."""
    scope = current_context()
    if scope:
        scope.require(store_id, manage=True)
    if (
        not _CODE.fullmatch(code)
        or not 1 <= len(name.strip()) <= 120
        or not 1 <= len(symbol.strip()) <= 24
        or type(ratio_num) is not int or type(ratio_den) is not int
        or not 1 <= ratio_num <= 1_000_000_000
        or not 1 <= ratio_den <= 1_000_000_000
        or not Decimal("0") < rounding <= Decimal("1000000")
    ):
        raise security.SecurityRejected("invalid_uom", 422)
    category = await db.get(ShopUomCategory, category_id)
    if category is None or category.store_id != store_id:
        raise security.SecurityRejected("uom_category_not_found", 404)
    if await db.scalar(select(ShopUom.id).where(
        ShopUom.store_id == store_id,
        ShopUom.code == code,
    )) is not None:
        raise security.SecurityRejected("uom_already_exists", 409)
    unit = ShopUom(
        id=_id(store_id, f"unit:{code}"), store_id=store_id,
        category_id=category_id, code=code, name=name.strip(),
        symbol=symbol.strip(), ratio_num=ratio_num,
        ratio_den=ratio_den, rounding=rounding,
    )
    db.add(unit)
    await db.commit()
    return {"id": unit.id, "store_id": store_id, "code": code}


async def validate_product_units(
    db: AsyncSession, *, store_id: str,
    uom_id: str | None, purchase_uom_id: str | None,
) -> tuple[str, str | None]:
    """Ensure both sale and purchase units belong to this Store/category."""
    selected = uom_id or default_unit_id(store_id)
    sale = await db.get(ShopUom, selected)
    if sale is None or sale.store_id != store_id or not sale.active:
        raise security.SecurityRejected("uom_not_available", 422)
    if purchase_uom_id is not None:
        purchase = await db.get(ShopUom, purchase_uom_id)
        if (
            purchase is None or not purchase.active
            or purchase.store_id != store_id
            or purchase.category_id != sale.category_id
        ):
            raise security.SecurityRejected("uom_category_mismatch", 422)
    return sale.id, purchase_uom_id


async def ensure_unit_not_in_use(
    db: AsyncSession, *, store_id: str, unit_id: str,
) -> None:
    """Refuse destructive UoM deactivation while a Product references it."""
    scope = current_context()
    if scope:
        scope.require(store_id, manage=True)
    in_use = await db.scalar(select(Product.id).where(
        Product.store_id == store_id,
        (Product.uom_id == unit_id) | (Product.purchase_uom_id == unit_id),
    ).limit(1))
    if in_use is not None:
        raise security.SecurityRejected("uom_in_use", 409)
