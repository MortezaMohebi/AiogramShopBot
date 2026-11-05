"""One central explicit registry; production adapters are never imported by preview."""

from functools import lru_cache

from services.shop_actions import adapters as a
from services.shop_actions.definitions import definitions
from services.shop_actions.registry import ActionSpec, Registry
from services.shop_actions.simulation import simulate_action


@lru_cache(maxsize=1)
def actions() -> Registry:
    """Bind only reviewed keys to exact functions, never input-selected service names."""
    bindings = {
        "catalog.list_categories": (a.list_categories, a.list_categories),
        "catalog.search_products": (a.search_products, a.search_products),
        "catalog.get_product": (a.get_product, a.get_product),
        "catalog.validate_product_visibility": (
            a.product_visibility,
            a.product_visibility,
        ),
        "catalog.get_price_uom": (a.price_uom, a.price_uom),
        "cart.get": (a.cart_get, a.cart_get),
        "cart.add_item": (a.cart_add, a.cart_add_preview),
        "cart.update_quantity": (a.cart_update, a.cart_update_preview),
        "cart.remove_item": (a.cart_remove, a.cart_remove_preview),
        "cart.clear": (a.cart_clear, a.cart_clear_preview),
        "order.list_customer_orders": (a.customer_orders, a.customer_orders),
        "order.get_status": (a.order_status, a.order_status),
        "checkout.validate": (a.checkout_prepare, a.checkout_prepare),
        "checkout.prepare": (a.checkout_prepare, a.checkout_prepare),
        "support.create_request": (a.support_create, a.support_preview),
    }
    registry = Registry()
    for definition in definitions():
        descriptor = definition.descriptor
        adapter, preview = bindings.get(descriptor.key, (None, None))
        key, version = descriptor.key, descriptor.version
        registry.register(
            ActionSpec(
                descriptor,
                definition.input_model,
                definition.output_model,
                adapter,
                preview,
                lambda payload, platform, key=key, version=version: simulate_action(
                    key, version, payload, platform=platform
                ),
            )
        )
    return registry
