"""Render customer copy with explicit optional-field visibility.

Required product identity, price and out-of-stock warnings remain visible.
Hiding an optional eye removes its entire label and associated value.
"""
from __future__ import annotations


def product_message(
    product: object,
    *,
    price_label: str,
    show_description: bool = True,
    show_stock: bool = True,
) -> str:
    """Build a product message without leaking a hidden optional field."""
    name = str(getattr(product, "name"))
    stock = int(getattr(product, "stock_quantity"))
    description = str(getattr(product, "description") or "")
    lines = [name]
    if show_description and description:
        excerpt = description[:2800]
        if len(description) > 2800:
            excerpt += "…"
        lines.extend(("", excerpt))
    lines.extend(("", f"قیمت: {price_label}"))
    if stock <= 0:
        lines.append("ناموجود")
    elif show_stock:
        lines.append(f"موجودی: {stock}")
    return "\n".join(lines)
