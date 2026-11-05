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
            "config": {"message": "شبیه‌سازی تمام شد؛ درخواست مرجوعی واقعی ایجاد نشد."},
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


def wholesale_application_template() -> tuple[Definition, EditorLayout]:
    """Collect a real confirmation-bound wholesale form without publishing or enabling it."""
    nodes = [{"id": "start", "type": "start"}]
    declarations = []
    fields = [
        ("name", "text", "نام و نام خانوادگی؟", "string", {"max_length": 160}),
        (
            "phone",
            "phone",
            "شمارهٔ تماس خود را با دکمهٔ اشتراک شماره بفرستید.",
            "string",
            {},
        ),
        ("company", "text", "نام کسب‌وکار یا شرکت؟", "string", {"max_length": 200}),
        ("city", "text", "شهر محل فعالیت؟", "string", {"max_length": 120}),
        (
            "estimated_monthly_amount",
            "number",
            "برآورد خرید ماهانه، به ریال؟",
            "integer",
            {"minimum": "0", "maximum": "999999999999999"},
        ),
        (
            "document",
            "document",
            "در صورت تمایل، مدرک PDF یا تصویر مجوز را به صورت فایل بفرستید؛ این مرحله اختیاری است.",
            "string",
            {"required": False, "max_bytes": 2_000_000},
        ),
    ]
    for key, kind, prompt, variable_type, extra in fields:
        nodes.append(
            {
                "id": key,
                "type": "ask_" + kind,
                "config": {"variable": key, "prompt": prompt, **extra},
            }
        )
        declarations.append({"name": key, "type": variable_type})
    nodes.extend(
        [
            {
                "id": "review",
                "type": "confirm",
                "config": {
                    "prompt": "اطلاعات درخواست همکاری را بررسی کنید:\nنام: {{name}}\nتماس: {{phone}}\nکسب‌وکار: {{company}}\nشهر: {{city}}\nبرآورد ماهانه: {{estimated_monthly_amount}} ریال\nآیا درخواست ثبت شود؟"
                },
            },
            {
                "id": "apply",
                "type": "action",
                "config": {
                    "action_key": "wholesale.create_application",
                    "action_version": "1.0.0",
                    "input_mapping": {
                        key: {"kind": "variable", "name": source}
                        for key, source in [
                            ("name", "name"),
                            ("phone", "phone"),
                            ("company", "company"),
                            ("city", "city"),
                            ("estimated_monthly_amount", "estimated_monthly_amount"),
                            ("document_handle", "document"),
                        ]
                    },
                    "output_mapping": {"request_id": "application_id"},
                },
            },
            {
                "id": "done",
                "type": "end",
                "config": {
                    "message": "درخواست شما با شمارهٔ {{application_id}} ثبت شد."
                },
            },
            {
                "id": "cancelled",
                "type": "cancel",
                "config": {"message": "درخواست ثبت نشد؛ می‌توانید دوباره شروع کنید."},
            },
        ]
    )
    declarations.append({"name": "application_id", "type": "integer"})
    sequence = ["start", *(x[0] for x in fields), "review"]
    transitions = [(left, "next", right) for left, right in zip(sequence, sequence[1:])]
    transitions += [
        ("review", "confirm", "apply"),
        ("review", "cancel", "cancelled"),
        ("apply", "success", "done"),
    ]
    transitions += [
        ("apply", port, "cancelled")
        for port in ("error", "retry", "pending_approval", "unavailable")
    ]
    definition = Definition.model_validate(
        {
            "target_platforms": ["telegram", "bale"],
            "entry_points": [
                {
                    "kind": "command",
                    "key": "wholesale",
                    "command": "wholesale",
                    "node_id": "start",
                },
                {"kind": "start", "key": "wholesale", "node_id": "start"},
            ],
            "nodes": nodes,
            "variables": declarations,
            "edges": [
                {
                    "id": "e" + str(index),
                    "source": source,
                    "port": port,
                    "target": target,
                }
                for index, (source, port, target) in enumerate(transitions)
            ],
        }
    )
    layout = EditorLayout.model_validate(
        {
            "positions": {
                node["id"]: {"x": (i % 3) * 320.0, "y": (i // 3) * 220.0}
                for i, node in enumerate(nodes)
            }
        }
    )
    return definition, layout
