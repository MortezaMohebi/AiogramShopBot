"""Explicit nonpublished sample definitions; no real orders or return requests."""

from services.shop_workflow_schema import Definition, EditorLayout


def return_request_template() -> tuple[Definition, EditorLayout]:
    """Demonstrate typed choices/branching/optional photo and an unavailable return stub."""
    nodes = [
        {"id": "start", "type": "start", "config": {}},
        {
            "id": "intro",
            "type": "send_text",
            "config": {
                "text": "درخواست مرجوعی — فقط داده‌های آزمایشی نمایش داده می‌شوند."
            },
        },
        {
            "id": "order",
            "type": "ask_choice",
            "config": {
                "prompt": "سفارش آزمایشی را انتخاب کنید.",
                "variable": "order",
                "choices_source": "simulation_orders",
            },
        },
        {
            "id": "product",
            "type": "ask_choice",
            "config": {
                "prompt": "محصول آزمایشی را انتخاب کنید.",
                "variable": "product",
                "choices_source": "simulation_products",
            },
        },
        {
            "id": "reason",
            "type": "ask_choice",
            "config": {
                "prompt": "دلیل مرجوعی چیست؟",
                "variable": "reason",
                "choices": [
                    {
                        "key": "damaged",
                        "label": "کالا آسیب دیده",
                        "value": "damaged",
                    },
                    {
                        "key": "wrong_item",
                        "label": "کالای دیگری دریافت کردم",
                        "value": "wrong_item",
                    },
                ],
            },
        },
        {
            "id": "description",
            "type": "ask_text",
            "config": {
                "prompt": "توضیح کوتاهی اضافه کنید؛ این مرحله اختیاری است.",
                "variable": "description",
                "required": False,
            },
        },
        {
            "id": "photo_branch",
            "type": "condition",
            "config": {
                "condition": {
                    "kind": "rule",
                    "variable": "reason",
                    "operator": "eq",
                    "value": "damaged",
                }
            },
        },
        {
            "id": "photo",
            "type": "ask_photo",
            "config": {
                "prompt": "در صورت تمایل، مشخصات یک تصویر آزمایشی را اضافه کنید.",
                "variable": "photo",
                "required": False,
            },
        },
        {
            "id": "summary",
            "type": "send_text",
            "config": {
                "text": "خلاصهٔ آزمایشی\nسفارش: {{order}}\nمحصول: {{product}}\nدلیل: {{reason}}\nتوضیح: {{description}}\nتصویر: {{photo}}"
            },
        },
        {
            "id": "confirm",
            "type": "confirm",
            "config": {"prompt": "این درخواست آزمایشی تأیید می‌شود؟"},
        },
        {
            "id": "return_stub",
            "type": "create_return_request",
            "config": {
                "order_variable": "order",
                "product_variable": "product",
            },
        },
        {
            "id": "end",
            "type": "end",
            "config": {
                "message": "شبیه‌سازی تمام شد؛ درخواست مرجوعی واقعی ایجاد نشد."
            },
        },
        {
            "id": "cancel",
            "type": "cancel",
            "config": {"message": "درخواست آزمایشی لغو شد."},
        },
    ]
    links = [
        ("start", "intro", "next"),
        ("intro", "order", "next"),
        ("order", "product", "next"),
        ("product", "reason", "next"),
        ("reason", "description", "next"),
        ("description", "photo_branch", "next"),
        ("photo_branch", "photo", "true"),
        ("photo_branch", "summary", "false"),
        ("photo", "summary", "next"),
        ("summary", "confirm", "next"),
        ("confirm", "return_stub", "confirm"),
        ("confirm", "cancel", "cancel"),
        ("return_stub", "end", "next"),
    ]
    definition = Definition.model_validate(
        {
            "entry_points": [
                {"kind": "menu", "key": "request_return", "node_id": "start"}
            ],
            "nodes": nodes,
            "edges": [
                {
                    "id": f"e_{i}",
                    "source": source,
                    "target": target,
                    "port": port,
                }
                for i, (source, target, port) in enumerate(links)
            ],
            "variables": [
                {"name": "order", "type": "order_ref"},
                {"name": "product", "type": "product_ref"},
                {
                    "name": "reason",
                    "type": "enum",
                    "choices": ["damaged", "wrong_item"],
                },
                {"name": "description", "type": "string"},
                {"name": "photo", "type": "string"},
            ],
        }
    )
    layout = EditorLayout.model_validate(
        {
            "positions": {
                node["id"]: {
                    "x": float((i % 3) * 280),
                    "y": float((i // 3) * 180),
                }
                for i, node in enumerate(nodes)
            }
        }
    )
    return definition, layout
