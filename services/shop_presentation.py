"""Render customer copy with explicit optional-field visibility.

Required product identity, price and out-of-stock warnings remain visible.
Hiding an optional eye removes its entire label and associated value.
"""
from __future__ import annotations

from services.shop_product_attributes import ATTRIBUTE_DETAIL_LIMIT, public_attributes


def product_message(
    product: object,
    *,
    price_label: str,
    unit_symbol: str = "عدد",
    show_description: bool = True,
    show_stock: bool = True,
    full_attributes: bool = False,
    attributes: list[dict] | None = None,
) -> str:
    """Build a product message without leaking a hidden optional field."""
    name = str(getattr(product, "name"))
    stock = int(getattr(product, "stock_quantity"))
    description = str(getattr(product, "description") or "")
    lines = [name]
    lines.extend(("", f"قیمت هر {unit_symbol}: {price_label}"))
    if stock <= 0:
        lines.append("ناموجود")
    elif show_stock:
        lines.append(f"موجودی: {stock} {unit_symbol}")
    specs = public_attributes(attributes)
    if specs:
        limit = ATTRIBUTE_DETAIL_LIMIT if full_attributes else 320
        excerpt = specs if len(specs) <= limit else specs[:limit - 1].rstrip() + "…"
        lines.extend(("", excerpt))
    if show_description and description:
        available = 4000 - len("\n".join(lines)) - 2
        limit = available if full_attributes else min(2800, available)
        excerpt = description if len(description) <= limit else description[:limit - 1] + "…"
        lines.extend(("", excerpt))
    return "\n".join(lines)
