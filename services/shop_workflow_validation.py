"""Bounded domain-graph validation independent of React Flow and persistence."""

from __future__ import annotations

import re
from collections import defaultdict

from services.shop_platform_capabilities import CAPABILITIES
from services.shop_workflow_catalog import (
    ACTION_SERVICES,
    NODE_SPECS,
    UNAVAILABLE_ACTIONS,
)
from services.shop_workflow_conditions import (
    PUBLIC_VARIABLES,
    condition_errors,
)
from services.shop_workflow_schema import (
    Definition,
    ValidationIssue,
    ValidationReport,
)


def node_ports(node, config: dict | None = None) -> set[str]:
    """Resolve domain transition names, including configured buttons and cases."""
    config = config if config is not None else node.config
    ports = set(NODE_SPECS[node.type].ports)
    if node.type == "show_buttons":
        ports.update(
            button["key"]
            for button in config["buttons"]
            if button["type"] in {"callback", "action"}
        )
    if node.type == "switch":
        ports.update(case["key"] for case in config["cases"])
    return ports


def _walk(start: str, adjacency: dict[str, set[str]]) -> set[str]:
    """Traverse at most the bounded node set, including explicit loop edges."""
    seen, pending = set(), [start]
    while pending:
        item = pending.pop()
        if item in seen:
            continue
        seen.add(item)
        pending.extend(adjacency.get(item, set()) - seen)
    return seen


def _cyclic_components(
    nodes: set[str], adjacency: dict[str, set[str]]
) -> list[set[str]]:
    """Find bounded SCCs with iterative reachability, without external graph state."""
    remaining, components = set(nodes), []
    reverse = defaultdict(set)
    for source, targets in adjacency.items():
        for target in targets:
            reverse[target].add(source)
    while remaining:
        root = min(remaining)
        component = _walk(root, adjacency) & _walk(root, reverse) & nodes
        remaining -= component
        if len(component) > 1 or root in adjacency.get(root, set()):
            components.append(component)
    return components


def validate_definition(
    definition: Definition, platforms: list[str] | None = None
) -> ValidationReport:
    """Locate semantic graph/type/platform findings while preserving editable drafts."""
    issues: list[ValidationIssue] = []

    def add(
        code,
        message,
        node_id=None,
        field=None,
        platform=None,
        severity="error",
    ):
        issues.append(
            ValidationIssue(
                code=code,
                message=message,
                node_id=node_id,
                field=field,
                platform=platform,
                severity=severity,
            )
        )

    nodes = {node.id: node for node in definition.nodes}
    starts = [node for node in definition.nodes if node.type == "start"]
    if len(nodes) != len(definition.nodes):
        add("duplicate_node", "شناسهٔ گره تکراری است.")
    if not starts:
        add("missing_start", "یک گرهٔ شروع اضافه کنید.")
    elif len(starts) > 1:
        add("duplicate_start", "فرایند باید دقیقاً یک گرهٔ شروع داشته باشد.")
    if len({edge.id for edge in definition.edges}) != len(definition.edges):
        add("duplicate_edge", "شناسهٔ اتصال تکراری است.")
    if len(set(definition.target_platforms)) != len(
        definition.target_platforms
    ):
        add("duplicate_platform", "پیام‌رسان هدف تکراری است.")
    declarations = {
        variable.name: variable for variable in definition.variables
    }
    if len(declarations) != len(definition.variables):
        add("duplicate_variable", "نام متغیر تکراری است.")
    if (
        definition.assignment.mode == "selected"
        and not definition.assignment.bot_ids
    ):
        add("bot_assignment_required", "حداقل یک ربات انتخاب کنید.")
    adjacency, reverse = defaultdict(set), defaultdict(set)
    used_ports = set()
    for edge in definition.edges:
        if edge.source not in nodes or edge.target not in nodes:
            add("dangling_edge", "مبدأ یا مقصد اتصال وجود ندارد.", edge.source)
            continue
        source = nodes[edge.source]
        if edge.port not in node_ports(source):
            add(
                "invalid_port",
                "خروجی اتصال برای این گره معتبر نیست.",
                source.id,
            )
        if (source.id, edge.port) in used_ports:
            add(
                "ambiguous_transition", "هر خروجی فقط یک مقصد دارد.", source.id
            )
        used_ports.add((source.id, edge.port))
        adjacency[edge.source].add(edge.target)
        reverse[edge.target].add(edge.source)
    for node in definition.nodes:
        for button in node.config.get("buttons", []):
            if (
                button["type"] in {"callback", "action"}
                and button["target"] in nodes
            ):
                targets = {
                    edge.target
                    for edge in definition.edges
                    if edge.source == node.id and edge.port == button["key"]
                }
                if targets and targets != {button["target"]}:
                    add(
                        "ambiguous_transition",
                        "مقصد دکمه و اتصال یکسان نیستند.",
                        node.id,
                        "buttons",
                    )
                adjacency[node.id].add(button["target"])
                reverse[button["target"]].add(node.id)
        if node.type == "go_to_step" and node.config["target"]:
            target = node.config["target"]
            if target not in nodes:
                add(
                    "invalid_transition_target",
                    "گرهٔ مقصد وجود ندارد.",
                    node.id,
                    "target",
                )
            else:
                adjacency[node.id].add(target)
                reverse[target].add(node.id)
    terminals = {
        node.id for node in definition.nodes if node.type in {"end", "cancel"}
    }
    reaches_terminal = (
        set().union(*(_walk(node_id, reverse) for node_id in terminals))
        if terminals
        else set()
    )
    if starts:
        reached = _walk(starts[0].id, adjacency)
        for node_id in nodes.keys() - reached:
            add(
                "unreachable_node",
                "این گره از شروع قابل دسترسی نیست.",
                node_id,
            )
        for node_id in reached & nodes.keys() - reaches_terminal:
            add(
                "missing_terminal_path",
                "مسیر قابل پایان یا لغو وجود ندارد.",
                node_id,
            )
    for component in _cyclic_components(set(nodes), adjacency):
        has_exit = any(adjacency[key] - component for key in component)
        if not has_exit or any(
            nodes[key].max_visits is None for key in component
        ):
            for key in sorted(component):
                add(
                    "unsafe_cycle",
                    "چرخه به خروج و سقف بازدید صریح نیاز دارد.",
                    key,
                )
    for entry in definition.entry_points:
        if entry.node_id not in nodes:
            add(
                "invalid_entry_target", "مقصد ورودی وجود ندارد.", entry.node_id
            )
    if len(
        {(entry.kind, entry.key) for entry in definition.entry_points}
    ) != len(definition.entry_points):
        add("duplicate_entry", "کلید ورودی تکراری است.")
    for node in definition.nodes:
        spec = NODE_SPECS[node.type]
        if not spec.contract_available:
            add(
                "action_contract_unavailable",
                "سرویس این عملیات موجود نیست؛ فقط Stub شبیه‌سازی دارد.",
                node.id,
                severity="warning",
            )
        for platform in platforms or definition.target_platforms:
            if platform not in CAPABILITIES:
                continue
            config = node.config | node.platform_overrides.get(platform, {})
            for item in spec.fields:
                if item.required and config.get(item.key) in (None, "", []):
                    add(
                        "missing_configuration",
                        "تنظیم الزامی این گره را تکمیل کنید.",
                        node.id,
                        item.key,
                        platform,
                    )
            for key, value in config.items():
                if (
                    key
                    in {
                        "variable",
                        "product_variable",
                        "order_variable",
                        "quantity_variable",
                        "output_variable",
                    }
                    and value
                ):
                    if value not in declarations:
                        add(
                            "unknown_variable",
                            "متغیر تعریف نشده است.",
                            node.id,
                            key,
                            platform,
                        )
                    else:
                        expected_type = {
                            "product_variable": "product_ref",
                            "order_variable": "order_ref",
                            "quantity_variable": "integer",
                        }.get(key)
                        if (
                            expected_type
                            and declarations[value].type != expected_type
                        ):
                            add(
                                "action_variable_type_mismatch",
                                "نوع مرجع عملیات معتبر نیست.",
                                node.id,
                                key,
                                platform,
                            )
                if isinstance(value, str):
                    for name in re.findall(
                        r"\{\{\s*([a-z][a-z0-9_.]*)\s*\}\}", value
                    ):
                        if (
                            name not in declarations
                            and name not in PUBLIC_VARIABLES
                        ):
                            add(
                                "unknown_variable",
                                "متغیر متن تعریف نشده است.",
                                node.id,
                                key,
                                platform,
                            )
            if config.get("condition"):
                for code in condition_errors(
                    config["condition"], declarations
                ):
                    add(
                        code,
                        "نوع یا متغیر شرط معتبر نیست.",
                        node.id,
                        "condition",
                        platform,
                    )
            buttons = config.get("buttons", [])
            if len({button["key"] for button in buttons}) != len(buttons):
                add(
                    "duplicate_button_key",
                    "کلید دکمه تکراری است.",
                    node.id,
                    "buttons",
                    platform,
                )
            if (
                node.type == "show_buttons"
                and buttons
                and not any(
                    platform in button["platforms"] for button in buttons
                )
            ):
                add(
                    "platform_buttons_empty",
                    "برای این پیام‌رسان دکمه‌ای وجود ندارد.",
                    node.id,
                    "buttons",
                    platform,
                )
            for button in buttons:
                if (
                    button["type"] == "action"
                    and button["action"]
                    not in ACTION_SERVICES.keys() | UNAVAILABLE_ACTIONS
                ):
                    add(
                        "unknown_action_contract",
                        "قرارداد این عملیات وجود ندارد.",
                        node.id,
                        "buttons",
                        platform,
                    )
                if button["target"] and button["target"] not in nodes:
                    add(
                        "invalid_transition_target",
                        "مقصد دکمه وجود ندارد.",
                        node.id,
                        "buttons",
                        platform,
                    )
                if (
                    button["type"] == "callback"
                    and not any(
                        edge.source == node.id and edge.port == button["key"]
                        for edge in definition.edges
                    )
                    and not button["target"]
                ):
                    add(
                        "missing_button_target",
                        "مقصد دکمه را مشخص کنید.",
                        node.id,
                        "buttons",
                        platform,
                    )
                if button["type"] == "url" and not button["url"]:
                    add(
                        "missing_configuration",
                        "آدرس HTTPS دکمه را وارد کنید.",
                        node.id,
                        "buttons",
                        platform,
                    )
                if button["visible_when"]:
                    for code in condition_errors(
                        button["visible_when"], declarations
                    ):
                        add(
                            code,
                            "شرط نمایش دکمه معتبر نیست.",
                            node.id,
                            "buttons",
                            platform,
                        )
                if (
                    button["type"] == "request_contact"
                    and config.get("keyboard") != "reply"
                ):
                    add(
                        "unsupported_button_type",
                        "درخواست Contact به Reply Keyboard نیاز دارد.",
                        node.id,
                        "buttons",
                        platform,
                    )
            capabilities = CAPABILITIES[platform]
            if node.type in {"ask_photo", "ask_document"} and config[
                "max_bytes"
            ] > min(
                capabilities["download_bytes"],
                (
                    capabilities["photo_bytes"]
                    if node.type == "ask_photo"
                    else capabilities["file_bytes"]
                ),
            ):
                add(
                    "platform_input_file_limit",
                    "حجم دریافت فایل از محدودیت این پیام‌رسان بیشتر است.",
                    node.id,
                    "max_bytes",
                    platform,
                )
            if (
                len(config.get("text", config.get("prompt", "")))
                > capabilities["text_characters"]
            ):
                add(
                    "platform_text_limit",
                    "متن از سقف پیام‌رسان بیشتر است.",
                    node.id,
                    "text",
                    platform,
                )
            caption = config.get("caption", "")
            if len(caption) > capabilities["caption_characters"]:
                add(
                    "platform_caption_limit",
                    "زیرنویس از سقف پیام‌رسان بیشتر است.",
                    node.id,
                    "caption",
                    platform,
                )
            if len(caption) > capabilities["adapter_caption_characters"]:
                add(
                    "adapter_caption_limit",
                    "Adapter فعلی این زیرنویس را کامل ارسال نمی‌کند.",
                    node.id,
                    "caption",
                    platform,
                )
            if node.type == "send_media_group":
                if len(config["media_ids"]) < 2:
                    add(
                        "invalid_media_group",
                        "آلبوم به حداقل دو رسانه نیاز دارد.",
                        node.id,
                        "media_ids",
                        platform,
                    )
                if not capabilities["adapter_media_group"]:
                    add(
                        "adapter_action_unavailable",
                        "API آلبوم را دارد؛ Adapter فعلی Executor آن را ندارد.",
                        node.id,
                        platform=platform,
                        severity="warning",
                    )
            variable = declarations.get(config.get("variable", ""))
            if variable:
                expected = {
                    "ask_number": config.get("number_type"),
                    "ask_phone": "string",
                    "ask_email": "string",
                    "ask_text": "string",
                    "ask_photo": "string",
                    "ask_document": "string",
                }.get(node.type)
                if expected and variable.type != expected:
                    add(
                        "input_type_mismatch",
                        "نوع متغیر با ورودی این گره سازگار نیست.",
                        node.id,
                        "variable",
                        platform,
                    )
            if node.type == "condition" and not {"true", "false"} <= {
                edge.port
                for edge in definition.edges
                if edge.source == node.id
            }:
                add(
                    "missing_branch",
                    "هر دو شاخهٔ شرط باید مقصد داشته باشند.",
                    node.id,
                )
            if node.type in {"switch", "confirm"} and not node_ports(
                node, config
            ) <= {
                edge.port
                for edge in definition.edges
                if edge.source == node.id
            }:
                add(
                    "missing_branch",
                    "همهٔ شاخه‌ها باید مقصد داشته باشند.",
                    node.id,
                    platform=platform,
                )
    valid = not any(issue.severity == "error" for issue in issues)
    return ValidationReport(valid=valid, can_simulate=valid, issues=issues)
