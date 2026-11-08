"""Pure versioned Action definitions; safe for validation and Simulator imports."""

from dataclasses import dataclass
from functools import lru_cache

from services.shop_actions import schemas as s
from services.shop_actions.contracts import ActionDescriptor


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """A portable descriptor and authoritative models without live adapters."""

    descriptor: ActionDescriptor
    input_model: type
    output_model: type


def _definition(
    key,
    name,
    input_model,
    output_model,
    *,
    scope="catalog.read",
    mutation=False,
    confirmation="none",
    available=True,
    reason=None,
    sensitive=(),
    external=False,
    version="1.0.0",
):
    """Build one explicit reviewed descriptor with conservative execution policy."""
    category = key.split(".")[0]
    return ActionDefinition(
        ActionDescriptor(
            key=key,
            version=version,
            name=name,
            description=name,
            category=category,
            input_schema=input_model.model_json_schema(),
            output_schema=output_model.model_json_schema(),
            required_scopes=[scope],
            allowed_actors=(
                ["customer", "staff"] if category == "catalog" else ["customer"]
            ),
            required_context=["store", "bot"]
            + ([] if category == "catalog" else ["customer"]),
            side_effect=(
                "external_mutation"
                if external
                else "business_mutation" if mutation else "read_only"
            ),
            idempotency="required" if mutation or external else "not_applicable",
            transaction=(
                "outbox" if external else "atomic_local" if mutation else "read_only"
            ),
            confirmation=confirmation,
            service_available=available,
            unavailable_reason=reason,
            sensitive_inputs=list(sensitive),
        ),
        input_model,
        output_model,
    )


@lru_cache(maxsize=1)
def definitions() -> tuple[ActionDefinition, ...]:
    """Expose exactly the approved business surface; no generic code/HTTP/SQL."""
    return (
        _definition(
            "catalog.list_categories",
            "فهرست دسته‌بندی‌های مجاز",
            s.Page,
            s.CategoryPage,
        ),
        _definition(
            "catalog.search_products", "جستجوی محصولات مجاز", s.Search, s.ProductPage
        ),
        _definition(
            "catalog.search_products", "جستجوی محصولات با متن نمایش",
            s.Search, s.ProductSearchDisplay, version="2.0.0",
        ),
        _definition(
            "catalog.get_product", "جزئیات محصول", s.ProductInput, s.ProductPublic
        ),
        _definition(
            "catalog.validate_product_visibility",
            "بررسی دسترسی محصول",
            s.ProductInput,
            s.Visibility,
        ),
        _definition(
            "catalog.get_price_uom",
            "قیمت و واحد فروش محصول",
            s.ProductInput,
            s.PriceUom,
        ),
        _definition("cart.get", "مشاهده سبد", s.Empty, s.CartView, scope="cart.read"),
        _definition(
            "cart.add_item",
            "افزودن کالا به سبد",
            s.AddItem,
            s.CartView,
            scope="cart.write",
            mutation=True,
        ),
        _definition(
            "cart.update_quantity",
            "تغییر تعداد کالا",
            s.UpdateItem,
            s.CartView,
            scope="cart.write",
            mutation=True,
        ),
        _definition(
            "cart.remove_item",
            "حذف کالا از سبد",
            s.RemoveItem,
            s.CartView,
            scope="cart.write",
            mutation=True,
        ),
        _definition(
            "cart.clear",
            "خالی‌کردن سبد",
            s.CartRevision,
            s.CartView,
            scope="cart.write",
            mutation=True,
            confirmation="customer_confirmation",
        ),
        _definition(
            "order.list_customer_orders",
            "سفارش‌های مشتری",
            s.Page,
            s.OrderPage,
            scope="orders.read",
        ),
        _definition(
            "order.get_status",
            "وضعیت سفارش مشتری",
            s.OrderInput,
            s.OrderStatus,
            scope="orders.read",
        ),
        _definition(
            "order.list_return_eligible_orders",
            "سفارش‌های قابل مرجوعی",
            s.Page,
            s.OrderPage,
            scope="orders.read",
            available=False,
            reason="action_return_policy_unavailable",
        ),
        _definition(
            "checkout.validate",
            "بررسی پیش‌نیازهای خرید",
            s.Empty,
            s.CheckoutView,
            scope="checkout.read",
        ),
        _definition(
            "checkout.prepare",
            "آماده‌سازی پیش‌نمایش خرید",
            s.Empty,
            s.CheckoutView,
            scope="checkout.read",
        ),
        _definition(
            "support.create_request",
            "ثبت درخواست پشتیبانی",
            s.SupportInput,
            s.TicketResult,
            scope="support.write",
            mutation=True,
            sensitive=("body",),
        ),
        _definition(
            "returns.create_request",
            "ثبت درخواست مرجوعی",
            s.ReturnInput,
            s.RequestResult,
            scope="support.write",
            mutation=True,
            confirmation="customer_confirmation",
            available=False,
            reason="action_service_unavailable",
            sensitive=("description",),
        ),
        _definition(
            "wholesale.create_application",
            "ثبت درخواست همکاری عمده",
            s.WholesaleInput,
            s.WholesaleResult,
            scope="support.write",
            mutation=True,
            confirmation="customer_confirmation",
            sensitive=(
                "name", "phone", "company", "city", "estimated_monthly_amount",
                "document_handle",
            ),
        ),
        _definition(
            "notification.notify_admin",
            "اعلان به مدیر",
            s.NotifyInput,
            s.RequestResult,
            scope="support.write",
            external=True,
            available=False,
            reason="action_service_unavailable",
            sensitive=("message",),
        ),
    )


def definition(key: str, version: str) -> ActionDefinition | None:
    """Resolve a pure exact-version contract without constructing live adapters."""
    return next(
        (
            item
            for item in definitions()
            if (item.descriptor.key == key and item.descriptor.version == version)
        ),
        None,
    )
