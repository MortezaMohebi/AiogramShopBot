"""Deterministic synthetic Action outputs; imports no database or live adapters."""

from services.shop_actions.contracts import ActionRejected
from services.shop_actions.definitions import definition

_SAMPLE_UOM = {
    "id": "sample-piece",
    "name": "عدد آزمایشی",
    "symbol": "عدد",
    "ratio_num": 1,
    "ratio_den": 1,
    "rounding": "1",
}


def simulate_action(
    key: str, version: str, payload: dict, *, platform: str = "telegram"
) -> dict:
    """Replay a reviewed typed Action with unmistakably synthetic safe data."""
    contract = definition(key, version)
    if contract is None:
        raise ActionRejected("action_unknown")
    if platform not in contract.descriptor.platforms:
        raise ActionRejected("action_platform_unavailable")
    try:
        data = contract.input_model.model_validate(payload).model_dump(mode="json")
    except ValueError:
        raise ActionRejected("action_invalid_input") from None
    product_id = data.get("product_id", 90011)
    product = {
        "id": product_id,
        "name": "محصول آزمایشی",
        "sku": "SAMPLE",
        "description": "داده شبیه‌سازی؛ محصول واقعی نیست.",
        "product_type": "physical",
        "price_irr": 1000,
        "price_stars": None,
        "in_stock": True,
        "uom": dict(_SAMPLE_UOM),
    }
    order = {
        "order_id": data.get("order_id", 90001),
        "status": "paid",
        "currency": "IRR",
        "amount": 1000,
        "bot_id": "sample-bot",
        "platform": platform,
    }
    if key == "catalog.list_categories":
        output = {
            "items": [{"id": 90001, "name": "دسته آزمایشی"}],
            "total": 1,
            "page": 1,
            "has_more": False,
        }
    elif key == "catalog.search_products":
        output = {"items": [product], "total": 1, "page": 1, "has_more": False}
    elif key == "catalog.get_product":
        output = product
    elif key == "catalog.get_price_uom":
        output = {
            "product_id": product_id,
            "price_irr": 1000,
            "price_stars": None,
            "uom": dict(_SAMPLE_UOM),
        }
    elif key == "catalog.validate_product_visibility":
        output = {"visible": True}
    elif key.startswith("cart."):
        count = data.get("quantity", 1)
        empty = key in {"cart.clear", "cart.remove_item"}
        output = {
            "cart_id": 90001,
            "revision": data.get("expected_cart_revision", 1) + 1,
            "items": (
                []
                if empty
                else [
                    {
                        "product_id": product_id,
                        "name": product["name"],
                        "quantity": count,
                        "unit_price_irr": 1000,
                        "line_total_irr": 1000 * count,
                        "uom": dict(_SAMPLE_UOM),
                    }
                ]
            ),
            "subtotal_irr": 0 if empty else 1000 * count,
            "discount_irr": 0,
            "shipping_irr": 0,
            "total_irr": 0 if empty else 1000 * count,
            "shipping_required": not empty,
            "shipping_ready": False,
        }
    elif key == "order.get_status":
        output = order
    elif key.startswith("order."):
        output = {"items": [order], "total": 1, "page": 1, "has_more": False}
    elif key.startswith("checkout."):
        output = {
            "ready": True,
            "missing": [],
            "cart_revision": 1,
            "mode": "manual",
            "terms_version": "sample",
            "total_irr": 1000,
            "total_stars": None,
        }
    elif key == "support.create_request":
        output = {"ticket_id": 90001, "status": "simulated"}
    elif key == "wholesale.create_application":
        output = {"request_id": 90001, "status": "simulated"}
    else:
        output = {"request_id": None, "status": "simulated_unavailable"}
    return contract.output_model.model_validate(output).model_dump(mode="json")
