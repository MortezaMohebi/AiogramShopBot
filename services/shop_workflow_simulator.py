"""Deterministic bounded conversation replay; no DB, provider or executor imports.

This is a design preview, not the production Workflow Runtime. Every commerce
or business-process action produces an explicit fixture/stub message only.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field, model_validator

from services.shop_platform_capabilities import CAPABILITIES
from services.shop_workflow_catalog import ACTION_SERVICES, UNAVAILABLE_ACTIONS
from services.shop_workflow_conditions import (
    cast_value,
    comparable,
    evaluate_condition,
)
from services.shop_workflow_schema import (
    BotId,
    Definition,
    Scalar,
    StrictModel,
)
from services.shop_workflow_validation import validate_definition


class SimulatedCustomer(StrictModel):
    """Only explicitly synthetic customer context can be sent from the browser."""

    customer_name: str = Field(default="مشتری آزمایشی", max_length=120)
    scenario: Literal["standard", "no_orders"] = "standard"


class SimulationContext(SimulatedCustomer):
    """Server-resolved names are presentation only and never grant access."""

    store_name: str = Field(default="فروشگاه آزمایشی", max_length=160)
    bot_name: str = Field(default="ربات آزمایشی", max_length=160)


class SimulatedFile(StrictModel):
    """Metadata-only preview input; bytes are never uploaded or persisted."""

    name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(max_length=100)
    size_bytes: int = Field(ge=1, le=50_000_000)


class SimulationEvent(StrictModel):
    """A bounded replay event; no arbitrary objects or expression strings execute."""

    kind: Literal["input", "button", "back", "cancel", "tick"]
    value: Scalar = None
    key: str = Field(default="", max_length=64)
    file: SimulatedFile | None = None
    seconds: int = Field(default=0, ge=0, le=86400)

    @model_validator(mode="after")
    def event_shape(self):
        """Reject unrelated payload fields rather than silently ignoring them."""
        if self.kind == "button" and not self.key:
            raise ValueError("button_key_required")
        if self.kind != "input" and (
            self.value is not None or self.file is not None
        ):
            raise ValueError("unexpected_input_value")
        if self.kind != "button" and self.key:
            raise ValueError("unexpected_button_key")
        if self.kind != "tick" and self.seconds:
            raise ValueError("unexpected_virtual_time")
        return self


class SimulationRequest(StrictModel):
    """Pin a saved immutable revision and one eligible same-Store preview Bot."""

    revision: int = Field(ge=1)
    bot_id: BotId
    platform: Literal["telegram", "bale"]
    context: SimulatedCustomer = Field(default_factory=SimulatedCustomer)
    events: list[SimulationEvent] = Field(default_factory=list, max_length=100)


@dataclass
class PreviewState:
    """Ephemeral replay state; it never appears in persisted workflow definitions."""

    node_id: str | None
    status: str = "running"
    code: str | None = None
    values: dict = field(default_factory=dict)
    messages: list[dict] = field(default_factory=list)
    buttons: list[dict] = field(default_factory=list)
    input: dict | None = None
    visited: list[str] = field(default_factory=list)
    visits: dict[str, int] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    stub_actions: list[str] = field(default_factory=list)
    elapsed_seconds: int = 0


class PreviewInterpreter:
    """Replay pure state transitions with explicit iteration and output budgets."""

    def __init__(self, definition, platform, context):
        """Bind one immutable graph and synthetic context, without external resources."""
        self.definition, self.platform, self.context = (
            definition,
            platform,
            context,
        )
        self.nodes = {node.id: node for node in definition.nodes}
        self.declarations = {
            variable.name: variable for variable in definition.variables
        }
        self.transitions = {
            (edge.source, edge.port): edge.target for edge in definition.edges
        }
        self.state = PreviewState(
            next(node.id for node in definition.nodes if node.type == "start")
        )
        self.state.values = {
            variable.name: cast_value(variable, variable.default)
            for variable in definition.variables
            if variable.default is not None
        }
        self.state.values.update(
            {
                "context.platform": platform,
                "context.customer_name": context.customer_name,
                "context.store_name": context.store_name,
                "context.bot_name": context.bot_name,
            }
        )
        self.past: list[PreviewState] = []
        self.total_steps = 0

    def config(self, node):
        """Use the selected platform's typed partial override over base settings."""
        return node.config | node.platform_overrides.get(self.platform, {})

    def render(self, text):
        """Substitute declared scalar values without evaluating attributes or code."""

        def value(match):
            item = self.state.values.get(match.group(1))
            if isinstance(item, dict):
                return f'{item["kind"]} #{item["id"]}'
            if item is None:
                return "—"
            return str(item)

        return re.sub(r"\{\{\s*([a-z][a-z0-9_.]*)\s*\}\}", value, text)

    def fail(self, code):
        """Stop or cancel a preview without triggering a fallback business action."""
        self.state.status = (
            "cancelled"
            if self.definition.error_policy.on_error == "cancel"
            else "error"
        )
        self.state.code = code
        self.state.messages.append(
            {
                "node_id": self.state.node_id,
                "kind": "error",
                "text": self.definition.error_policy.message,
                "simulation_only": True,
            }
        )

    def emit(self, kind, text, *, interpolate=True, **metadata):
        """Bound rendered messages instead of silently truncating a preview."""
        rendered = self.render(text) if interpolate else text
        if len(rendered) > CAPABILITIES[self.platform]["text_characters"]:
            self.fail("platform_text_limit_after_render")
            return False
        if (
            sum(len(item["text"]) for item in self.state.messages)
            + len(rendered)
            > 64_000
        ):
            self.fail("simulation_output_limit")
            return False
        self.state.messages.append(
            {
                "node_id": self.state.node_id,
                "kind": kind,
                "text": rendered,
                "simulation_only": True,
                **metadata,
            }
        )
        return True

    def next(self, port="next", target=None):
        """Resolve only graph-owned transitions; never deserialize a callback command."""
        if self.state.status in {"error", "cancelled"}:
            return
        destination = target or self.transitions.get(
            (self.state.node_id, port)
        )
        if destination not in self.nodes:
            self.fail("transition_not_available")
            return
        self.state.node_id, self.state.status = destination, "running"
        self.state.buttons, self.state.input = [], None

    def tick(self, seconds):
        """Advance virtual time; no sleeping, scheduling or external waits occur."""
        self.state.elapsed_seconds += seconds
        if self.state.elapsed_seconds > self.definition.timeout_policy.seconds:
            self.state.status = (
                "cancelled"
                if self.definition.timeout_policy.outcome == "cancel"
                else "completed"
            )
            self.state.code = "simulation_timeout"
            self.emit("system", "مهلت مجازی این شبیه‌سازی تمام شد.")

    def choices(self, config):
        """Expose deterministic, explicitly synthetic order/product options only."""
        source = config.get("choices_source", "static")
        if source == "simulation_orders":
            return (
                []
                if self.context.scenario == "no_orders"
                else [
                    {
                        "key": "order_1",
                        "label": "سفارش آزمایشی 90001",
                        "value": {"kind": "order", "id": 90001},
                    }
                ]
            )
        if source == "simulation_products":
            return [
                {
                    "key": "product_1",
                    "label": "محصول آزمایشی 90011",
                    "value": {"kind": "product", "id": 90011},
                }
            ]
        return config.get("choices", [])

    def stub(self, key, config):
        """Describe a future action; do not resolve/import its commerce service."""
        self.state.stub_actions.append(key)
        self.emit("stub", "فقط شبیه‌سازی — عملیات «" + key + "» اجرا نشد.")
        variable = self.declarations.get(config.get("output_variable", ""))
        if variable:
            value = {
                "string": "SIMULATED",
                "integer": 1,
                "decimal": "1.00",
                "boolean": True,
                "date": "2026-01-01",
                "datetime": "2026-01-01T00:00:00+00:00",
                "enum": variable.choices[0] if variable.choices else None,
                "product_ref": {"kind": "product", "id": 90011},
                "order_ref": {"kind": "order", "id": 90001},
                "customer_ref": {"kind": "customer", "id": 90021},
            }[variable.type]
            self.state.values[variable.name] = cast_value(variable, value)

    def pump(self):
        """Run automatic nodes until an interaction or a terminal/error state."""
        while self.state.status == "running":
            self.total_steps += 1
            if self.total_steps > self.definition.error_policy.max_steps:
                self.fail("simulation_step_limit")
                break
            node = self.nodes[self.state.node_id]
            visits = self.state.visits.get(node.id, 0)
            if visits >= (node.max_visits or 1):
                self.fail("node_visit_limit")
                break
            self.state.visits[node.id] = visits + 1
            self.state.visited.append(node.id)
            config = self.config(node)
            kind = node.type
            if kind in {"end", "cancel"}:
                if config["message"]:
                    self.emit("text", config["message"])
                if self.state.status == "running":
                    self.state.status = (
                        "completed" if kind == "end" else "cancelled"
                    )
            elif kind == "start":
                self.next()
            elif kind == "send_text":
                self.emit("text", config["text"])
                self.next()
            elif kind in {
                "send_photo",
                "send_video",
                "send_document",
                "send_media_group",
            }:
                self.emit(
                    "media",
                    config["caption"] or "رسانهٔ انتخاب‌شده در پیش‌نمایش",
                    media_kind=kind.removeprefix("send_"),
                    media_id=config.get("media_id"),
                    media_ids=config.get("media_ids", []),
                )
                self.next()
            elif kind == "delay":
                self.emit("system", f'تأخیر مجازی: {config["seconds"]} ثانیه')
                self.tick(config["seconds"])
                if self.state.status == "running":
                    self.next()
            elif kind == "go_to_step":
                self.next(target=config["target"])
            elif kind == "condition":
                result = evaluate_condition(
                    config["condition"], self.declarations, self.state.values
                )
                self.next("true" if result else "false")
            elif kind == "switch":
                port = "default"
                for case in config["cases"]:
                    if evaluate_condition(
                        {
                            "kind": "rule",
                            "variable": config["variable"],
                            "operator": "eq",
                            "value": case["value"],
                        },
                        self.declarations,
                        self.state.values,
                    ):
                        port = case["key"]
                        break
                self.next(port)
            elif kind == "action":
                from services.shop_action_bindings import resolve_inputs, write_outputs
                from services.shop_actions.simulation import simulate_action
                from services.shop_actions.contracts import ActionRejected
                from services.shop_actions.definitions import definition

                try:
                    output = simulate_action(
                        config["action_key"],
                        config["action_version"],
                        resolve_inputs(config, self.state.values),
                        platform=self.platform,
                    )
                    contract = definition(
                        config["action_key"], config["action_version"]
                    )
                    available = contract.descriptor.service_available
                    if available:
                        write_outputs(
                            config, output, self.state.values, self.declarations
                        )
                    key = config["action_key"] + "@" + config["action_version"]
                    self.state.stub_actions.append(key)
                    self.emit(
                        "stub",
                        (
                            "Action فقط با دادهٔ آزمایشی شبیه‌سازی شد: "
                            if available
                            else "سرویس Action آماده نیست؛ مسیر unavailable شبیه‌سازی شد: "
                        )
                        + key,
                        action_key=config["action_key"],
                        action_version=config["action_version"],
                        status="succeeded" if available else "unavailable",
                        output=output if available else None,
                    )
                    self.next("success" if available else "unavailable")
                except ActionRejected as error:
                    self.emit(
                        "stub",
                        "ورودی Action آزمایشی قابل پردازش نیست.",
                        error_code=error.code,
                    )
                    self.next("error")
            elif kind in ACTION_SERVICES or kind in UNAVAILABLE_ACTIONS:
                self.stub(kind, config)
                self.next()
            elif kind == "confirm":
                if not self.emit("text", config["prompt"]):
                    break
                self.state.buttons = [
                    {
                        "key": "confirm",
                        "label": config["confirm_label"],
                        "row": 0,
                        "type": "callback",
                    },
                    {
                        "key": "cancel",
                        "label": config["cancel_label"],
                        "row": 0,
                        "type": "callback",
                    },
                ]
                self.state.status = "waiting"
            elif kind == "show_buttons":
                if not self.emit("text", config["text"]):
                    break
                self.state.buttons = [
                    button
                    for button in config["buttons"]
                    if self.platform in button["platforms"]
                    and (
                        not button["visible_when"]
                        or evaluate_condition(
                            button["visible_when"],
                            self.declarations,
                            self.state.values,
                        )
                    )
                ]
                if self.state.buttons:
                    self.state.status = "waiting"
                else:
                    self.fail("no_visible_buttons")
            elif kind.startswith("ask_") or kind == "wait_for_input":
                if not self.emit("text", config["prompt"]):
                    break
                self.state.input = {
                    "kind": kind.removeprefix("ask_"),
                    **config,
                }
                self.state.buttons = []
                if kind == "ask_choice":
                    self.state.buttons = [
                        {
                            "key": choice["key"],
                            "label": choice["label"],
                            "row": i // 2,
                            "type": "choice",
                        }
                        for i, choice in enumerate(self.choices(config))
                    ]
                    if not self.state.buttons:
                        self.emit(
                            "system",
                            "گزینهٔ آزمایشی واجد شرایطی وجود ندارد؛ می‌توانید برگردید یا لغو کنید.",
                        )
                if not config["required"]:
                    self.state.buttons.append(
                        {
                            "key": "skip",
                            "label": "ردکردن این مرحله",
                            "row": 99,
                            "type": "skip",
                        }
                    )
                self.state.status = "waiting"
            else:
                self.fail("unsupported_simulation_node")

    def input_value(self, node, config, event):
        """Normalize only this node's declared type and permitted fixture choices."""
        variable = self.declarations[config["variable"]]
        if (
            event.kind == "button"
            and event.key == "skip"
            and not config["required"]
        ):
            return None
        if node.type == "ask_choice":
            options = self.choices(config)
            if event.kind == "button":
                option = next(
                    (item for item in options if item["key"] == event.key),
                    None,
                )
                if option is None:
                    raise ValueError("invalid_choice")
                value = option["value"]
            else:
                value = event.value
                if value not in [item["value"] for item in options]:
                    raise ValueError("invalid_choice")
            return cast_value(variable, value)
        if node.type in {"ask_photo", "ask_document"}:
            upload = event.file
            limit = min(
                config["max_bytes"],
                CAPABILITIES[self.platform]["download_bytes"],
            )
            if upload is None or upload.size_bytes > limit:
                raise ValueError("invalid_simulated_file")
            if node.type == "ask_photo" and upload.mime_type not in {
                "image/jpeg",
                "image/png",
                "image/webp",
            }:
                raise ValueError("invalid_simulated_photo")
            return cast_value(variable, upload.name)
        value = event.value
        if isinstance(value, str):
            value = value.strip().translate(
                str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
            )
        if config["required"] and value in (None, ""):
            raise ValueError("input_required")
        if node.type == "ask_email" and (
            not isinstance(value, str)
            or len(value) > 254
            or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,63}", value)
        ):
            raise ValueError("invalid_email")
        if node.type == "ask_phone" and (
            not isinstance(value, str)
            or not re.fullmatch(r"\+?[0-9]{9,15}", value)
        ):
            raise ValueError("invalid_phone")
        converted = cast_value(variable, value, from_input=True)
        if (
            node.type == "ask_text"
            and converted is not None
            and not config["min_length"]
            <= len(converted)
            <= config["max_length"]
        ):
            raise ValueError("text_length_limit")
        if node.type == "ask_number" and converted is not None:
            number = comparable(variable, converted)
            for bound, operator in (
                (config["minimum"], "min"),
                (config["maximum"], "max"),
            ):
                if bound is not None:
                    limit = comparable(
                        variable, cast_value(variable, bound, from_input=True)
                    )
                    if (operator == "min" and number < limit) or (
                        operator == "max" and number > limit
                    ):
                        raise ValueError("number_range_limit")
        return converted

    def event(self, event):
        """Consume a replay event without touching a persisted draft/session."""
        if event.kind == "back":
            if self.past:
                self.state = self.past.pop()
            return
        if event.kind == "cancel":
            self.state.status, self.state.code = (
                "cancelled",
                "cancelled_by_user",
            )
            self.state.buttons, self.state.input = [], None
            self.emit("system", "شبیه‌سازی لغو شد.")
            return
        if event.kind == "tick":
            self.tick(event.seconds)
            return
        if self.state.status != "waiting":
            return
        node, before = self.nodes[self.state.node_id], deepcopy(self.state)
        config = self.config(node)
        if self.state.input is not None:
            try:
                value = self.input_value(node, config, event)
            except (ValueError, TypeError):
                attempts = self.state.attempts.get(node.id, 0) + 1
                self.state.attempts[node.id] = attempts
                self.emit("error", config["error_message"])
                if attempts >= config["max_attempts"]:
                    self.fail("input_attempts_exhausted")
                return
            self.past.append(before)
            self.state.values[config["variable"]] = value
            self.emit(
                "input",
                str(value) if value is not None else "این مرحله رد شد.",
                interpolate=False,
            )
            self.next()
        elif event.kind == "button":
            button = next(
                (
                    item
                    for item in self.state.buttons
                    if item["key"] == event.key
                ),
                None,
            )
            if button is None:
                return
            if button["type"] == "back":
                if self.past:
                    self.state = self.past.pop()
                return
            if button["type"] in {"cancel", "main_menu"}:
                self.event(SimulationEvent(kind="cancel"))
                return
            if button["type"] in {"url", "request_contact"}:
                self.emit(
                    "stub",
                    "این دکمه در Runtime پاسخ می‌گیرد؛ در شبیه‌سازی اثر خارجی ندارد.",
                )
                return
            self.past.append(before)
            self.emit("input", button["label"])
            if button["type"] == "action":
                self.stub(button["action"], {})
            self.next(event.key, button.get("target"))
        self.pump()

    def result(self):
        """Return bounded public preview output with no hidden execution state."""
        return {
            "status": self.state.status,
            "code": self.state.code,
            "active_node_id": self.state.node_id,
            "messages": self.state.messages,
            "buttons": self.state.buttons,
            "input": self.state.input,
            "values": self.state.values,
            "visited": self.state.visited,
            "stub_actions": self.state.stub_actions,
            "elapsed_seconds": self.state.elapsed_seconds,
            "can_go_back": bool(self.past),
            "simulation_only": True,
        }


def simulate(
    definition: Definition, *, platform: str, context=None, events=None
) -> dict:
    """Replay a bounded immutable definition with synthetic, side-effect-free inputs."""
    definition = Definition.model_validate(definition)
    preview_context = SimulationContext.model_validate(context or {})
    empty = {
        "active_node_id": None,
        "messages": [],
        "buttons": [],
        "input": None,
        "values": {},
        "visited": [],
        "stub_actions": [],
        "elapsed_seconds": 0,
        "can_go_back": False,
        "simulation_only": True,
    }
    if platform not in definition.target_platforms:
        return empty | {
            "status": "invalid",
            "code": "workflow_platform_not_targeted",
            "simulation_only": True,
        }
    report = validate_definition(definition, [platform])
    if not report.can_simulate:
        return empty | {
            "status": "invalid",
            "code": "workflow_graph_invalid",
            "validation": report.model_dump(mode="json"),
            "messages": [],
            "visited": [],
            "simulation_only": True,
        }
    if events is not None and len(events) > 100:
        raise ValueError("simulation_event_limit")
    replay = [SimulationEvent.model_validate(event) for event in events or []]
    engine = PreviewInterpreter(definition, platform, preview_context)
    engine.pump()
    for event in replay:
        engine.event(event)
    return engine.result() | {"validation": report.model_dump(mode="json")}
