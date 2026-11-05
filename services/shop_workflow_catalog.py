"""One allowlisted typed node catalog drives validation and inspector forms."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import Field, create_model

from services.shop_platform_capabilities import platform_capabilities
from services.shop_action_binding_schema import ActionInputSource
from services.shop_actions.definitions import definitions as action_definitions
from services.shop_workflow_schema import (
    Condition,
    StrictModel,
    WorkflowButton,
    WorkflowChoice,
)

PositiveId = Annotated[int, Field(ge=1, le=9_007_199_254_740_991)]
ShortText = Annotated[str, Field(max_length=4096)]
ShortName = Annotated[str, Field(max_length=80)]
Attempts = Annotated[int, Field(ge=1, le=10)]


@dataclass(frozen=True)
class ConfigField:
    """A schema-backed form field shared by all workflows of a node type."""

    key: str
    label: str
    kind: str
    annotation: object
    default: object = ""
    required: bool = False
    options: tuple[str, ...] = ()
    help: str = ""
    show_if: dict = field(default_factory=dict)


@dataclass(frozen=True)
class NodeSpec:
    """Stable domain type, form metadata and future action integration contract."""

    type: str
    label: str
    group: str
    fields: tuple[ConfigField, ...]
    ports: tuple[str, ...] = ("next",)
    service: str | None = None
    contract_available: bool = True

    @property
    def config_model(self):
        """Return the cached strict model for exactly these configuration fields."""
        return CONFIG_MODELS[self.type]


def f(
    key,
    label,
    kind="text",
    annotation=ShortText,
    default="",
    *,
    required=False,
    options=(),
    help="",
    show_if=None,
):
    """Construct compact catalog data without duplicating form/schema fields."""
    return ConfigField(
        key,
        label,
        kind,
        annotation,
        default,
        required,
        tuple(options),
        help,
        show_if or {},
    )


TEXT = f("text", "متن پیام", "textarea", required=True)
VARIABLE = f("variable", "متغیر پاسخ", "variable", ShortName, required=True)
PROMPT = f("prompt", "پرسش", "textarea", required=True)
INPUT_FIELDS = (
    PROMPT,
    VARIABLE,
    f("required", "پاسخ الزامی است", "boolean", bool, True),
    f("max_attempts", "حداکثر تلاش نامعتبر", "number", Attempts, 3),
    f(
        "error_message",
        "پیام پاسخ نامعتبر",
        default="پاسخ معتبر نیست؛ دوباره تلاش کنید.",
    ),
)
OVERRIDABLE_FIELDS = {
    "text",
    "prompt",
    "caption",
    "message",
    "error_message",
    "confirm_label",
    "cancel_label",
    "media_id",
    "media_ids",
}

ACTION_SERVICES = {
    "show_categories": "services.shop_channel_catalog.CatalogFlow.reply",
    "show_products": "services.shop_channel_catalog.CatalogFlow.reply",
    "show_product_details": "services.shop_channel_catalog.CatalogFlow.reply",
    "select_product": "services.shop_channel_catalog.CatalogFlow.reply",
    "select_quantity": "services.shop_cart.ShopCartFlow.reply",
    "add_to_cart": "services.shop_cart.ShopCartFlow.reply",
    "view_cart": "services.shop_cart.ShopCartFlow.reply",
    "start_checkout": "services.shop_cart.ShopCartFlow.reply",
    "show_order_status": "services.shop_orders.ShopOrdersFlow.reply",
    "create_support_request": "services.shop_customer_support.CustomerSupportFlow.reply",
}
UNAVAILABLE_ACTIONS = {
    "create_return_request",
    "request_admin_approval",
    "notify_admin",
    "request_wholesale_access",
}


def _specs() -> list[NodeSpec]:
    """Build all initial node families; business logic stays outside this catalog."""
    control = "شروع و کنترل"
    result = [
        NodeSpec("start", "شروع", control, ()),
        NodeSpec("end", "پایان", control, (f("message", "پیام پایان"),), ()),
        NodeSpec("cancel", "لغو", control, (f("message", "پیام لغو"),), ()),
        NodeSpec(
            "condition",
            "شرط",
            control,
            (
                f(
                    "condition",
                    "شرط",
                    "condition",
                    Condition | None,
                    None,
                    required=True,
                ),
            ),
            ("true", "false"),
        ),
        NodeSpec(
            "switch",
            "چندشاخه",
            control,
            (
                VARIABLE,
                f(
                    "cases",
                    "شاخه‌ها",
                    "choices",
                    list[WorkflowChoice],
                    [],
                    required=True,
                ),
            ),
            ("default",),
        ),
        NodeSpec("wait_for_input", "انتظار پاسخ", control, INPUT_FIELDS),
        NodeSpec(
            "delay",
            "تأخیر",
            control,
            (
                f(
                    "seconds",
                    "ثانیهٔ مجازی",
                    "number",
                    Annotated[int, Field(ge=0, le=86400)],
                    1,
                ),
            ),
        ),
        NodeSpec(
            "go_to_step",
            "رفتن به گره",
            control,
            (f("target", "گرهٔ مقصد", "node", ShortName, required=True),),
        ),
        NodeSpec("send_text", "پیام متنی", "پیام", (TEXT,)),
    ]
    for kind, label in (
        ("photo", "تصویر"),
        ("video", "ویدیو"),
        ("document", "سند"),
    ):
        result.append(
            NodeSpec(
                "send_" + kind,
                "ارسال " + label,
                "پیام",
                (
                    f(
                        "media_id",
                        "رسانهٔ فروشگاه",
                        "media",
                        PositiveId | None,
                        None,
                        required=True,
                    ),
                    f("caption", "زیرنویس", "textarea"),
                ),
            )
        )
    result.append(
        NodeSpec(
            "send_media_group",
            "آلبوم رسانه",
            "پیام",
            (
                f(
                    "media_ids",
                    "رسانه‌های آلبوم",
                    "media_list",
                    Annotated[list[PositiveId], Field(max_length=10)],
                    [],
                    required=True,
                ),
                f("caption", "زیرنویس", "textarea"),
            ),
        )
    )
    result.extend(
        [
            NodeSpec(
                "show_buttons",
                "پیام و دکمه‌ها",
                "تعامل",
                (
                    TEXT,
                    f(
                        "keyboard",
                        "نوع صفحه‌کلید",
                        "select",
                        Literal["inline", "reply"],
                        "inline",
                        options=("inline", "reply"),
                    ),
                    f(
                        "buttons",
                        "دکمه‌ها",
                        "buttons",
                        Annotated[list[WorkflowButton], Field(max_length=60)],
                        [],
                        required=True,
                    ),
                ),
                (),
            ),
            NodeSpec(
                "confirm",
                "تأیید یا لغو",
                "تعامل",
                (
                    PROMPT,
                    f("confirm_label", "دکمهٔ تأیید", default="تأیید"),
                    f("cancel_label", "دکمهٔ لغو", default="لغو"),
                ),
                ("confirm", "cancel"),
            ),
        ]
    )
    for kind, label in (
        ("text", "متن"),
        ("number", "عدد"),
        ("phone", "تلفن"),
        ("email", "ایمیل"),
        ("photo", "تصویر"),
        ("document", "سند"),
        ("choice", "گزینه"),
    ):
        fields = list(INPUT_FIELDS)
        if kind == "text":
            fields.extend(
                [
                    f(
                        "min_length",
                        "حداقل نویسه",
                        "number",
                        Annotated[int, Field(ge=0, le=4096)],
                        0,
                    ),
                    f(
                        "max_length",
                        "حداکثر نویسه",
                        "number",
                        Annotated[int, Field(ge=1, le=4096)],
                        4096,
                    ),
                ]
            )
        if kind == "number":
            fields.extend(
                [
                    f(
                        "number_type",
                        "نوع عدد",
                        "select",
                        Literal["integer", "decimal"],
                        "integer",
                        options=("integer", "decimal"),
                    ),
                    f("minimum", "کمینه", "text", ShortName | None, None),
                    f("maximum", "بیشینه", "text", ShortName | None, None),
                ]
            )
        if kind == "phone":
            fields.append(
                f(
                    "contact_only",
                    "در Runtime، Contact خود مشتری لازم است",
                    "boolean",
                    bool,
                    True,
                )
            )
        if kind in {"photo", "document"}:
            fields.append(
                f(
                    "max_bytes",
                    "حداکثر حجم فایل",
                    "number",
                    Annotated[int, Field(ge=1, le=50_000_000)],
                    10_000_000 if kind == "photo" else 20_000_000,
                )
            )
        if kind == "choice":
            fields.extend(
                [
                    f(
                        "choices_source",
                        "منبع گزینه‌ها",
                        "select",
                        Literal[
                            "static",
                            "simulation_orders",
                            "simulation_products",
                        ],
                        "static",
                        options=(
                            "static",
                            "simulation_orders",
                            "simulation_products",
                        ),
                    ),
                    f(
                        "choices",
                        "گزینه‌ها",
                        "choices",
                        Annotated[list[WorkflowChoice], Field(max_length=100)],
                        [],
                        show_if={"choices_source": "static"},
                    ),
                ]
            )
        result.append(
            NodeSpec("ask_" + kind, "دریافت " + label, "تعامل", tuple(fields))
        )
    labels = {
        "show_categories": "نمایش دسته‌بندی‌ها",
        "show_products": "نمایش محصولات",
        "show_product_details": "جزئیات محصول",
        "select_product": "انتخاب محصول",
        "select_quantity": "انتخاب تعداد",
        "add_to_cart": "افزودن به سبد",
        "view_cart": "نمایش سبد",
        "start_checkout": "شروع Checkout",
        "show_order_status": "وضعیت سفارش",
        "create_support_request": "درخواست پشتیبانی",
        "create_return_request": "درخواست مرجوعی",
        "request_admin_approval": "درخواست تأیید مدیر",
        "notify_admin": "اعلان به مدیر",
        "request_wholesale_access": "درخواست دسترسی عمده",
    }
    for kind, label in labels.items():
        fields = (
            f("product_variable", "متغیر محصول", "variable", ShortName),
            f("order_variable", "متغیر سفارش", "variable", ShortName),
            f("quantity_variable", "متغیر تعداد", "variable", ShortName),
            f(
                "output_variable",
                "متغیر خروجی شبیه‌سازی",
                "variable",
                ShortName,
            ),
            f("message", "توضیح این مرحله", "textarea"),
        )
        result.append(
            NodeSpec(
                kind,
                label,
                (
                    "تجارت"
                    if kind in ACTION_SERVICES
                    and kind != "create_support_request"
                    else "فرایند کسب‌وکار"
                ),
                fields,
                service=ACTION_SERVICES.get(kind),
                contract_available=kind not in UNAVAILABLE_ACTIONS,
            )
        )
    result.append(
        NodeSpec(
            "action",
            "Action تایپ‌شده",
            "عملیات Backend",
            (
                f(
                    "action_key",
                    "Action",
                    "action_key",
                    Annotated[str, Field(max_length=81)],
                    required=True,
                ),
                f(
                    "action_version",
                    "نسخهٔ Action",
                    "action_version",
                    ShortName,
                    "1.0.0",
                    required=True,
                ),
                f(
                    "input_mapping",
                    "ورودی‌های Action",
                    "action_inputs",
                    Annotated[dict[str, ActionInputSource], Field(max_length=40)],
                    {},
                ),
                f(
                    "output_mapping",
                    "خروجی‌های Action",
                    "action_outputs",
                    Annotated[dict[str, str], Field(max_length=40)],
                    {},
                ),
            ),
            ("success", "error", "retry", "pending_approval", "unavailable"),
        )
    )
    return result


NODE_SPECS = {spec.type: spec for spec in _specs()}
CONFIG_MODELS = {
    key: create_model(
        "WorkflowConfig_" + key,
        __base__=StrictModel,
        **{item.key: (item.annotation, item.default) for item in spec.fields},
    )
    for key, spec in NODE_SPECS.items()
}


def node_catalog() -> dict:
    """Describe typed forms, action readiness and platform limits without executors."""
    nodes = []
    for key, spec in NODE_SPECS.items():
        schema = spec.config_model.model_json_schema()
        nodes.append(
            {
                "type": key,
                "label": spec.label,
                "group": spec.group,
                "ports": list(spec.ports),
                "defaults": spec.config_model().model_dump(mode="json"),
                "fields": [
                    {
                        "key": item.key,
                        "label": item.label,
                        "kind": item.kind,
                        "required": item.required,
                        "overridable": item.key in OVERRIDABLE_FIELDS,
                        "options": list(item.options),
                        "help": item.help,
                        "show_if": item.show_if,
                        "schema": schema["properties"][item.key],
                    }
                    for item in spec.fields
                ],
                "config_schema": schema,
                "action_contract": {
                    "key": key,
                    "service": spec.service,
                    "available": spec.contract_available,
                    "execution_available": False,
                    "simulation_only": bool(
                        spec.service or key in UNAVAILABLE_ACTIONS or key == "action"
                    ),
                },
            }
        )
    return {
        "schema_version": 1,
        "nodes": nodes,
        "actions": [
            item.descriptor.model_dump(mode="json") for item in action_definitions()
        ],
        "platforms": platform_capabilities(),
        "runtime_available": False,
        "callback_contract": {
            "live_generation_available": False,
            "max_bytes": 64,
            "strategy": "opaque_server_resolved_scoped_capability",
            "contains_business_state": False,
        },
    }
