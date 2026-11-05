"""Bounded, platform-neutral Runtime contracts and publication capabilities."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from services.shop_workflow_schema import StrictModel

SUPPORTED_NODES = frozenset(
    {
        "start",
        "end",
        "cancel",
        "condition",
        "switch",
        "wait_for_input",
        "delay",
        "go_to_step",
        "set_variable",
        "send_text",
        "send_photo",
        "send_video",
        "send_document",
        "send_media_group",
        "show_buttons",
        "confirm",
        "ask_text",
        "ask_number",
        "ask_phone",
        "ask_email",
        "ask_photo",
        "ask_document",
        "ask_choice",
        "action",
    }
)
TERMINAL = frozenset({"completed", "cancelled", "failed", "expired"})
WAITING = frozenset(
    {"waiting_input", "waiting_action", "waiting_approval", "waiting_timeout"}
)
RESERVED_COMMANDS = frozenset(
    {"cart", "checkout", "catalog", "orders", "support", "payment"}
)
MAX_EVENTS = 1000
MAX_OUTBOX = 1000
INPUTS_PER_MINUTE = 60
MAX_PENDING_INPUTS = 20


class RuntimeRejected(ValueError):
    """Carry only a stable redacted failure code across runtime boundaries."""

    def __init__(self, code: str, status: int = 409):
        """Keep private customer values outside logs and HTTP error responses."""
        self.code, self.status = code, status
        super().__init__(code)


class BindingSpec(StrictModel):
    """One exact Bot entry point, with no executable eligibility expression."""

    bot_id: str
    kind: Literal["command", "menu", "start", "internal", "legacy_bridge", "admin_test"]
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    node_id: str = Field(min_length=1, max_length=64)
    priority: int = Field(default=0, ge=0, le=100)
    enabled: bool = True
    eligibility: Literal["all", "existing_customer"] = "all"
    fallback: Literal["legacy", "ignore"] = "legacy"
    version_policy: Literal["active_publication"] = "active_publication"

    @model_validator(mode="after")
    def valid_identity(self):
        """Reject malformed Bot IDs and entries reserved for financial commerce."""
        UUID(self.bot_id)
        if self.kind == "command" and self.key in RESERVED_COMMANDS:
            raise ValueError("runtime_legacy_command_reserved")
        return self


class FileInput(StrictModel):
    """An authenticated Bot's opaque provider handle, never a path or URL."""

    file_id: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    kind: Literal["photo", "document"]
    size: int = Field(ge=1, le=20_000_000)
    mime_type: Literal["image/jpeg", "image/png", "application/pdf"]


class RuntimeInput(StrictModel):
    """Receiver-authoritative user/update identity plus bounded neutral content."""

    platform: Literal["telegram", "bale"]
    update_id: str = Field(min_length=1, max_length=100)
    user_id: int = Field(ge=1, le=9_223_372_036_854_775_807)
    chat_id: int = Field(ge=1, le=9_223_372_036_854_775_807)
    kind: Literal[
        "command",
        "callback",
        "text",
        "contact",
        "photo",
        "document",
        "timeout",
        "internal",
    ]
    text: str = Field(default="", max_length=4096)
    callback: str = Field(default="", max_length=64)
    contact_owner: int | None = None
    file: FileInput | None = None

    @model_validator(mode="after")
    def private_chat(self):
        """Customer workflows accept private direct messages only."""
        if self.chat_id != self.user_id:
            raise ValueError("runtime_private_chat_required")
        return self


def publication_findings(definition) -> list[dict]:
    """Report runtime-specific gaps separately from editable draft validation."""
    findings = []
    declarations = {v.name: v for v in definition.variables}
    for node in definition.nodes:
        code = None
        if node.type not in SUPPORTED_NODES:
            code = "runtime_node_unsupported"
        if node.type == "ask_choice" and node.config["choices_source"] != "static":
            code = "runtime_choice_source_unsupported"
        if node.type == "show_buttons":
            if any(b["type"] == "action" for b in node.config["buttons"]):
                code = "runtime_use_typed_action_node"
        if node.type == "set_variable":
            from services.shop_workflow_conditions import cast_value

            variable = declarations.get(node.config["variable"])
            try:
                if variable is None:
                    raise ValueError("unknown_variable")
                cast_value(variable, node.config["value"])
            except ValueError:
                code = "runtime_variable_invalid"
        if code:
            findings.append({"code": code, "node_id": node.id, "severity": "error"})
    return findings


class DeliveryRejected(RuntimeError):
    """A definite provider rejection that guarantees this attempt delivered nothing."""

    def __init__(self, code: str, *, retryable: bool = False):
        """Only an allowlisted failure code and explicit retry policy cross transport."""
        self.code, self.retryable = code, retryable
        super().__init__(code)
