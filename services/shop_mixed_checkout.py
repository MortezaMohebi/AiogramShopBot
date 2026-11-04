"""Deterministic split and customer quote proof for Telegram mixed carts.

Telegram digital goods use Stars XTR while physical goods may use a fiat
provider. A mixed basket becomes two legally separate, independently paid
orders, never a single invoice with two currencies. This pure module has no
provider side effects, ORM session or floating-point currency conversion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable


class MixedCheckoutError(ValueError):
    """A mixed Telegram checkout cannot be priced without ambiguity."""


@dataclass(frozen=True, slots=True)
class PartLine:
    """An immutable product/quantity snapshot for checkout planning."""

    product_id: int
    product_type: str
    quantity: int
    unit_price_irr: int
    unit_price_stars: int | None
    requires_shipping: bool

    @property
    def line_total_irr(self) -> int:
        """Multiply exact integer rials without rounding."""
        return self.quantity * self.unit_price_irr


@dataclass(frozen=True, slots=True)
class CheckoutPart:
    """One independently invoiced physical/IRR or digital/XTR order."""

    kind: str
    currency: str
    lines: tuple[PartLine, ...]
    subtotal_irr: int
    discount_irr: int
    shipping_irr: int
    total_irr: int
    total_stars: int | None


@dataclass(frozen=True, slots=True)
class MixedCheckoutPlan:
    """Two committed parts plus a human-readable physical shipping label."""

    physical: CheckoutPart
    digital: CheckoutPart
    shipping_label: str | None
    coupon_code: str | None


def _normalized_line(item: object) -> PartLine:
    """Accept a customer CartQuote or explicit test snapshot, never floats."""
    product = getattr(item, "product", item)
    qty = getattr(item, "quantity", None)
    amount = getattr(product, "unit_price_irr", None)
    if amount is None:
        price = getattr(product, "price", None)
        line_total = getattr(item, "line_total", None)
        if type(line_total) is int and type(qty) is int and qty > 0:
            if line_total % qty != 0:
                raise MixedCheckoutError("Non-integral Rial line snapshot.")
            amount = line_total // qty
        else:
            amount = price
    data = PartLine(
        product_id=getattr(product, "product_id", getattr(product, "id", None)),
        product_type=getattr(product, "product_type", None),
        quantity=qty,
        unit_price_irr=amount,
        unit_price_stars=getattr(
            product, "unit_price_stars", getattr(product, "price_stars", None)
        ),
        requires_shipping=getattr(product, "requires_shipping", None),
    )
    if (
        type(data.product_id) is not int or data.product_id <= 0
        or data.product_type not in {"physical", "digital"}
        or type(data.quantity) is not int or not 1 <= data.quantity <= 99
        or type(data.unit_price_irr) is not int or data.unit_price_irr < 0
        or type(data.requires_shipping) is not bool
        or (data.product_type == "digital" and data.requires_shipping)
    ):
        raise MixedCheckoutError("Invalid product or quantity in split checkout.")
    return data


def normalize_lines(lines: Iterable[object]) -> tuple[PartLine, ...]:
    """Normalize a maximum of 20 unique source products into stable order."""
    items = tuple(_normalized_line(item) for item in lines)
    if not 1 <= len(items) <= 20:
        raise MixedCheckoutError("Expected 1–20 products per checkout.")
    identifiers = [item.product_id for item in items]
    if len(identifiers) != len(set(identifiers)):
        raise MixedCheckoutError("Duplicate product in checkout.")
    return tuple(sorted(items, key=lambda item: item.product_id))


def build_split_plan(
    lines: Iterable[object], *, shipping_irr: int,
    physical_discount_irr: int, coupon_code: str | None = None,
    shipping_label: str | None = None,
) -> MixedCheckoutPlan:
    """Price each Telegram cart half in its *own* payment currency.

    Discount and shipping belong solely to the physical IRR invoice. They
    never enter XTR Star totals. Caller validates coupon rules against only
    the physical subtotal *before* selecting the discount argument.
    """
    items = normalize_lines(lines)
    physical = tuple(item for item in items if item.product_type == "physical")
    digital = tuple(item for item in items if item.product_type == "digital")
    if not physical or not digital:
        raise MixedCheckoutError("A split requires physical and digital items.")
    if (
        type(shipping_irr) is not int or shipping_irr < 0
        or type(physical_discount_irr) is not int or physical_discount_irr < 0
        or (coupon_code is not None and (not coupon_code or len(coupon_code) > 32))
    ):
        raise MixedCheckoutError("Invalid shipping/discount values.")
    physical_subtotal = sum(item.line_total_irr for item in physical)
    digital_subtotal = sum(item.line_total_irr for item in digital)
    if not 0 <= physical_discount_irr < physical_subtotal:
        raise MixedCheckoutError("Physical coupon would zero or overdraw invoice.")
    fiat = physical_subtotal + shipping_irr - physical_discount_irr
    if fiat <= 0 or fiat > 999_999_999_999_999:
        raise MixedCheckoutError("Invalid physical IRR invoice amount.")
    stars = 0
    for item in digital:
        if type(item.unit_price_stars) is not int or item.unit_price_stars <= 0:
            raise MixedCheckoutError("Missing positive Telegram Star price.")
        stars += item.unit_price_stars * item.quantity
    if not 1 <= stars <= 999_999_999_999:
        raise MixedCheckoutError("Invalid Telegram Stars invoice total.")
    return MixedCheckoutPlan(
        physical=CheckoutPart(
            "physical", "IRR", physical, physical_subtotal,
            physical_discount_irr, shipping_irr, fiat, None,
        ),
        digital=CheckoutPart(
            "digital", "XTR", digital, digital_subtotal,
            0, 0, digital_subtotal, stars,
        ),
        shipping_label=shipping_label,
        coupon_code=coupon_code,
    )


def checkout_quote_fingerprint(
    lines: Iterable[object], *, shipping_irr: int,
    physical_discount_irr: int, policy_token: str,
    coupon_code: str | None = None, shipping_label: str | None = None,
    shipping_address: str | None = None,
) -> str:
    """Bind a 12-hex callback proof to exact prices, cart and sales terms.

    A stale callback must not silently accept changed Star prices or a
    changed shipping address/coupon. The proof is *not* customer auth;
    owner and cart revision are always checked separately under DB locks.
    """
    if not isinstance(policy_token, str) or not policy_token:
        raise MixedCheckoutError("Missing sales-policy proof.")
    items = normalize_lines(lines)
    payload = {
        "terms": policy_token,
        "shipping_irr": shipping_irr,
        "discount_irr": physical_discount_irr,
        "coupon": coupon_code,
        "shipping_label": shipping_label,
        "shipping_address": shipping_address,
        "items": [
            (
                line.product_id, line.product_type, line.quantity,
                line.unit_price_irr, line.unit_price_stars,
                line.requires_shipping,
            ) for line in items
        ],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("ascii")).hexdigest()[:12]
