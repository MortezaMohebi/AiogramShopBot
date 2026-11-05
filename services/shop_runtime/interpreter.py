"""Deterministic bounded Workflow state machine with no I/O or business effects."""

from __future__ import annotations

import re
from copy import deepcopy
from decimal import Decimal

from services.shop_runtime.contracts import SUPPORTED_NODES
from services.shop_workflow_conditions import cast_value, evaluate_condition
from services.shop_workflow_schema import canonical_json

DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class Machine:
    """Advance a pinned definition only until the next persistent boundary."""

    def __init__(
        self,
        definition,
        *,
        platform,
        node_id,
        values=None,
        state=None,
        context=None,
        now=None,
    ):
        """Copy portable state; no provider SDK or mutable global reaches execution."""
        self.definition, self.platform, self.node_id = definition, platform, node_id
        self.nodes = {n.id: n for n in definition.nodes}
        self.declarations = {v.name: v for v in definition.variables}
        self.values = (
            deepcopy(values)
            if values is not None
            else {
                v.name: cast_value(v, v.default)
                for v in definition.variables
                if v.default is not None
            }
        )
        self.context = dict(context or {}) | {"context.platform": platform}
        self.state = deepcopy(state or {})
        self.now = now
        self.status, self.error = "active", None
        self.outbound, self.action, self.wait = [], None, None

    def config(self, node):
        """Apply only schema-validated per-platform presentation overrides."""
        return node.config | node.platform_overrides.get(self.platform, {})

    def render(self, text):
        """Interpolate declared scalar values only, without executing expressions."""

        def substitute(match):
            value = (self.values | self.context).get(match[1])
            if isinstance(value, dict):
                return f"{value['kind']} #{value['id']}"
            return "—" if value is None else str(value)

        result = re.sub(r"\{\{\s*([a-z][a-z0-9_.]*)\s*\}\}", substitute, text)
        if len(result) > 4096:
            raise ValueError("runtime_text_limit")
        return result

    def emit(self, text="", **payload):
        """Produce one bounded render intent; persistence supplies callback capabilities."""
        self.outbound.append(
            {
                "node_id": self.node_id,
                "epoch": self.state.get("epoch", 0),
                "text": self.render(text),
                **payload,
            }
        )
        if len(self.outbound) > 200:
            raise ValueError("runtime_outbound_budget")

    def move(self, port="next", *, direct=None):
        """Follow one validated edge without accepting a client-supplied destination."""
        target = direct or next(
            (
                e.target
                for e in self.definition.edges
                if e.source == self.node_id and e.port == port
            ),
            None,
        )
        if target is None or target not in self.nodes:
            raise ValueError("runtime_transition_missing")
        self.node_id = target
        self.state["node_transitions"] = self.state.get("node_transitions", 0) + 1

    def resume_at(self, port="next", *, direct=None):
        """Resume a durable boundary, failing closed on a missing pinned transition."""
        try:
            self.move(port, direct=direct)
        except ValueError:
            self.fail("runtime_transition_missing")
            return
        self.status = "active"
        self.advance()

    def fail(self, code):
        """Expose stable diagnostics, keeping raw input and private values out of errors."""
        self.status = (
            "cancelled"
            if self.definition.error_policy.on_error == "cancel"
            else "failed"
        )
        self.error = code
        self.action, self.wait = None, None
        self.outbound.append(
            {
                "node_id": self.node_id,
                "epoch": self.state.get("epoch", 0),
                "kind": "text",
                "text": self.definition.error_policy.message,
                "buttons": [],
                "notice": True,
            }
        )

    def boundary(self, node, config):
        """Persist a new interaction generation and a bounded safe Back checkpoint."""
        self.state["epoch"] = self.state.get("epoch", 0) + 1
        self.state["attempts"] = 0
        past = self.state.setdefault("past", [])
        if not self.state.pop("restoring", False):
            past.append({"node_id": node.id, "values": deepcopy(self.values)})
            del past[:-5]
        self.status = "waiting_input"
        self.wait = {
            "kind": node.type,
            "seconds": self.definition.timeout_policy.seconds,
        }
        buttons = []
        if node.type == "confirm":
            buttons = [
                {"label": config["confirm_label"], "value": "confirm"},
                {"label": config["cancel_label"], "value": "cancel"},
            ]
        elif node.type == "ask_choice":
            buttons = [
                {"label": x["label"], "value": x["key"]} for x in config["choices"]
            ]
        elif node.type == "show_buttons":
            for b in config["buttons"]:
                if self.platform not in b["platforms"] or (
                    b.get("visible_when")
                    and not evaluate_condition(
                        b["visible_when"], self.declarations, self.values | self.context
                    )
                ):
                    continue
                buttons.append(
                    {
                        "label": b["label"],
                        "value": b["key"] if b["type"] == "callback" else b["type"],
                        "url": b["url"] if b["type"] == "url" else None,
                        "row": b["row"],
                    }
                )
        else:
            if len(past) > 1:
                buttons.append({"label": "بازگشت", "value": "back", "command": "/back"})
            if not config.get("required", True):
                buttons.append(
                    {"label": "رد کردن این مرحله", "value": "skip", "command": "/skip"}
                )
            buttons.append({"label": "لغو", "value": "cancel", "command": "/cancel"})
        # Reply keyboards return plain text without a callback token. Pin the
        # exact offered labels to this generation, including visibility filters.
        self.state.pop("reply_choices", None)
        if node.type == "show_buttons" and config.get("keyboard") == "reply":
            self.state["reply_choices"] = {
                b["label"]: b["value"] for b in buttons if not b.get("url")
            }
        self.emit(
            config.get("prompt", config.get("text", "پاسخ خود را وارد کنید.")),
            kind="text",
            buttons=buttons,
            keyboard=config.get("keyboard", "inline"),
            request_contact=node.type == "ask_phone"
            and config.get("contact_only", True),
        )

    def advance(self):
        """Iterate bounded control nodes until input, timeout, Action or terminal state."""
        try:
            for _ in range(self.definition.error_policy.max_steps):
                node = self.nodes[self.node_id]
                if node.type not in SUPPORTED_NODES:
                    raise ValueError("runtime_node_unsupported")
                visits = self.state.setdefault("visits", {})
                visits[node.id] = visits.get(node.id, 0) + 1
                self.state["steps"] = self.state.get("steps", 0) + 1
                if visits[node.id] > (node.max_visits or 25):
                    raise ValueError("runtime_visit_budget")
                if self.state["steps"] > self.definition.error_policy.max_steps:
                    raise ValueError("runtime_step_budget")
                config = self.config(node)
                kind = node.type
                if kind in {"end", "cancel"}:
                    self.status = "completed" if kind == "end" else "cancelled"
                    if config.get("message"):
                        self.emit(
                            config["message"],
                            kind="text",
                            buttons=[],
                            notice=kind == "cancel",
                        )
                    self.wait = None
                    return
                if kind in {
                    "confirm",
                    "show_buttons",
                    "wait_for_input",
                } or kind.startswith("ask_"):
                    self.boundary(node, config)
                    return
                if kind == "action":
                    self.status, self.action = (
                        "waiting_action",
                        {"node_id": node.id, "config": config},
                    )
                    self.state["epoch"] = self.state.get("epoch", 0) + 1
                    return
                if kind == "delay":
                    self.state["epoch"] = self.state.get("epoch", 0) + 1
                    self.status = "waiting_timeout"
                    self.wait = {"kind": "delay", "seconds": max(1, config["seconds"])}
                    return
                if kind == "condition":
                    self.move(
                        "true"
                        if evaluate_condition(
                            config["condition"],
                            self.declarations,
                            self.values | self.context,
                        )
                        else "false"
                    )
                elif kind == "switch":
                    port = next(
                        (
                            case["key"]
                            for case in config["cases"]
                            if evaluate_condition(
                                {
                                    "kind": "rule",
                                    "variable": config["variable"],
                                    "operator": "eq",
                                    "value": case["value"],
                                },
                                self.declarations,
                                self.values | self.context,
                            )
                        ),
                        "default",
                    )
                    self.move(port)
                elif kind == "go_to_step":
                    self.move(direct=config["target"])
                elif kind == "set_variable":
                    self.values[config["variable"]] = cast_value(
                        self.declarations[config["variable"]], config["value"]
                    )
                    self.state.pop("confirmed_values", None)
                    self.move()
                elif kind == "start":
                    self.move()
                elif kind == "send_text":
                    self.emit(config["text"], kind="text", buttons=[])
                    self.move()
                elif kind.startswith("send_"):
                    self.emit(
                        config.get("caption", ""),
                        kind=kind.removeprefix("send_"),
                        media_ids=config.get("media_ids", [config.get("media_id")]),
                        buttons=[],
                    )
                    self.move()
                else:
                    raise ValueError("runtime_node_unsupported")
            raise ValueError("runtime_step_budget")
        except (ValueError, KeyError, TypeError) as error:
            code = (
                str(error)
                if str(error).startswith("runtime_")
                else "runtime_definition_invalid"
            )
            self.fail(code)
        finally:
            if (
                len(canonical_json(self.values).encode()) > 65536
                or len(canonical_json(self.state).encode()) > 262144
            ):
                self.fail("runtime_state_budget")

    def accept(self, value, *, kind="text", contact_owner=None, user_id=None):
        """Validate one typed answer; invalid input leaves the current wait in place."""
        node = self.nodes[self.node_id]
        config = self.config(node)
        try:
            if (
                node.type == "show_buttons"
                and config.get("keyboard") == "reply"
                and kind == "text"
            ):
                offered = self.state.get("reply_choices", {})
                if value in offered:
                    self.choose(offered[value])
                    return
            if (
                node.type in {"ask_text", "ask_number", "ask_email", "wait_for_input"}
                and kind != "text"
            ):
                raise ValueError("runtime_input_kind_mismatch")
            if node.type not in {"wait_for_input"} and not node.type.startswith("ask_"):
                raise ValueError("runtime_choice_required")
            if (
                node.type == "ask_phone"
                and config["contact_only"]
                and (kind != "contact" or contact_owner != user_id)
            ):
                raise ValueError("runtime_own_contact_required")
            if node.type in {
                "ask_photo",
                "ask_document",
            } and kind != node.type.removeprefix("ask_"):
                raise ValueError("runtime_file_required")
            if isinstance(value, str):
                value = value.strip().translate(DIGITS)
            if value in (None, "") and config.get("required", True):
                raise ValueError("runtime_input_required")
            if node.type == "ask_choice":
                choice = next((x for x in config["choices"] if x["key"] == value), None)
                if choice is None:
                    raise ValueError("runtime_choice_invalid")
                value = choice["value"]
            if node.type == "ask_phone" and not re.fullmatch(
                r"\+?[0-9]{9,15}", str(value)
            ):
                raise ValueError("runtime_phone_invalid")
            if node.type == "ask_email" and (
                len(str(value)) > 254
                or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,63}", str(value))
            ):
                raise ValueError("runtime_email_invalid")
            variable = self.declarations[config["variable"]]
            converted = cast_value(variable, value, from_input=True)
            if (
                node.type == "ask_text"
                and converted is not None
                and not config["min_length"] <= len(converted) <= config["max_length"]
            ):
                raise ValueError("runtime_text_length")
            if node.type == "ask_number" and converted is not None:
                number = Decimal(str(converted))
                if config["minimum"] is not None and number < Decimal(
                    config["minimum"]
                ):
                    raise ValueError("runtime_number_range")
                if config["maximum"] is not None and number > Decimal(
                    config["maximum"]
                ):
                    raise ValueError("runtime_number_range")
            self.values[variable.name] = converted
            self.state.pop("confirmed_values", None)
            self.resume_at()
        except (ValueError, KeyError, TypeError):
            self.state["validation_errors"] = self.state.get("validation_errors", 0) + 1
            self.state["attempts"] = self.state.get("attempts", 0) + 1
            if self.state["attempts"] >= config.get("max_attempts", 3):
                self.fail("runtime_input_attempts_exhausted")
            else:
                self.status = "waiting_input"
                self.emit(
                    config.get("error_message", "پاسخ معتبر نیست؛ دوباره تلاش کنید."),
                    kind="text",
                    buttons=[],
                )

    def cancel(self, *, menu=False):
        """Terminate globally without traversing a confirmation's decline edge."""
        self.status, self.wait, self.action = "cancelled", None, None
        self.emit(
            "منوی فروشگاه" if menu else "فرایند لغو شد.",
            kind="legacy_menu" if menu else "text",
            buttons=[],
            notice=True,
        )

    def timeout(self, target=None):
        """Resolve an unanswered input wait; the hard Run TTL is independent."""
        if target:
            self.resume_at(direct=target)
            return
        self.status = (
            "cancelled"
            if self.definition.timeout_policy.outcome == "cancel"
            else "completed"
        )
        self.error, self.wait = "runtime_input_timeout", None
        self.emit(
            "مهلت پاسخ تمام شده است؛ می‌توانید دوباره شروع کنید.",
            kind="text",
            buttons=[],
            notice=True,
        )

    def choose(self, value):
        """Consume a server-resolved choice; arbitrary transition IDs are never accepted."""
        node = self.nodes[self.node_id]
        config = self.config(node)
        if node.type == "confirm" and value == "cancel":
            self.resume_at("cancel")
            return
        if value in {"cancel", "main_menu"}:
            self.cancel(menu=value == "main_menu")
            return
        if value == "back":
            past = self.state.get("past", [])
            if len(past) < 2:
                self.emit("بازگشت از این مرحله ممکن نیست.", kind="text", buttons=[])
                return
            past.pop()
            previous = past[-1]
            self.values = deepcopy(previous["values"])
            self.node_id = previous["node_id"]
            self.state["restoring"] = True
            # A deliberate Back is bounded by the total step budget, not a false loop failure.
            visits = self.state.setdefault("visits", {})
            visits[self.node_id] = max(0, visits.get(self.node_id, 0) - 1)
            self.state.pop("confirmed_values", None)
            self.advance()
            return
        if value == "skip" and not config.get("required", True):
            self.values[config["variable"]] = None
            self.resume_at()
            return
        if node.type == "ask_choice":
            self.accept(value)
            return
        if node.type == "confirm" and value == "confirm":
            from services.shop_runtime.publication import digest

            self.state["confirmed_values"] = digest(self.values)
            # Only the coordinator supplies this server timestamp. A pure
            # interpreter used without a trusted clock cannot mint authority.
            self.state["confirmed_at"] = self.now.isoformat() if self.now else None
            self.resume_at("confirm")
            return
        if node.type == "show_buttons":
            button = next(
                (
                    b
                    for b in config["buttons"]
                    if b["key"] == value and b["type"] == "callback"
                ),
                None,
            )
            if button:
                self.resume_at(value, direct=button.get("target") or None)
                return
        self.emit("این انتخاب دیگر معتبر نیست.", kind="text", buttons=[])
