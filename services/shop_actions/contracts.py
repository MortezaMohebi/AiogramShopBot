"""Bounded public Action contracts with no trusted identity fields in requests."""

from __future__ import annotations

import json
import re
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from services.shop_workflow_schema import StrictModel

SideEffect = Literal[
    "none",
    "read_only",
    "reversible",
    "business_mutation",
    "external_mutation",
    "irreversible",
]
Status = Literal[
    "succeeded",
    "failed",
    "retryable",
    "pending_approval",
    "pending_external",
    "skipped",
    "unavailable",
]
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}\.[a-z][a-z0-9_]{0,47}$")
_SECRET = re.compile(r"[0-9]{5,}:[A-Za-z0-9_-]{20,}")
_FORBIDDEN = {"__proto__", "prototype", "constructor"}
_SECRET_KEYS = {
    "token",
    "secret",
    "password",
    "credential",
    "approval_receipt",
    "confirmation_receipt",
    "authorization",
    "api_key",
}


class ActionRejected(ValueError):
    """Expose a stable code, never a raw exception or private business input."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        """Keep machine-readable failure policy independent of error wording."""
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def bounded_json(value: Any, *, max_bytes: int = 65536) -> str:
    """Bound work before model parsing and return deterministic finite JSON."""
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 8:
            raise ActionRejected("action_payload_too_deep")
        if count > 5000:
            raise ActionRejected("action_payload_too_large")
        if isinstance(item, dict):
            if any(not isinstance(key, str) or key in _FORBIDDEN for key in item):
                raise ActionRejected("action_invalid_key")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif item is not None and type(item) not in {str, int, float, bool}:
            raise ActionRejected("action_invalid_payload")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (ValueError, TypeError, RecursionError):
        raise ActionRejected("action_invalid_payload") from None
    if len(encoded.encode()) > max_bytes:
        raise ActionRejected("action_payload_too_large")
    return encoded


def redact(value: Any, paths: tuple[str, ...] | list[str] = ()) -> Any:
    """Copy safe output, redacting declared paths, nested lists and credentials."""
    patterns = [path.split(".") for path in paths]

    def visit(item, location):
        if any(
            len(pattern) == len(location)
            and all(
                wanted == "*" or wanted == actual
                for wanted, actual in zip(pattern, location)
            )
            for pattern in patterns
        ):
            return "[redacted]"
        if isinstance(item, dict):
            return {
                key: (
                    "[redacted]"
                    if key.lower() in _SECRET_KEYS
                    else visit(child, location + [key])
                )
                for key, child in item.items()
            }
        if isinstance(item, list):
            return [
                visit(child, location + [str(index)])
                for index, child in enumerate(item)
            ]
        if isinstance(item, str) and _SECRET.search(item):
            return "[redacted]"
        return item

    return visit(value, [])


class ActionDescriptor(StrictModel):
    """Versioned discoverable policy, coupled to explicit typed adapters."""

    key: str = Field(min_length=3, max_length=81)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    category: str = Field(pattern=r"^[a-z][a-z_]{0,31}$")
    input_schema: dict
    output_schema: dict
    error_schema: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "retryable": {"type": "boolean"},
            },
            "additionalProperties": False,
        }
    )
    required_context: list[
        Literal["store", "bot", "customer", "administrator", "workflow", "node"]
    ] = Field(default_factory=lambda: ["store", "bot"])
    allowed_actors: list[Literal["customer", "staff"]] = Field(
        default_factory=lambda: ["customer", "staff"], min_length=1, max_length=2
    )
    required_scopes: list[str] = Field(default_factory=lambda: ["catalog.read"])
    side_effect: SideEffect = "read_only"
    idempotency: Literal["not_applicable", "recommended", "required"] = "not_applicable"
    transaction: Literal["read_only", "atomic_local", "outbox"] = "read_only"
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    max_retries: int = Field(default=0, ge=0, le=5)
    backoff_seconds: int = Field(default=1, ge=1, le=60)
    retry_requires_idempotency: bool = True
    retryable_codes: list[str] = Field(
        default_factory=lambda: ["action_timeout", "action_busy"]
    )
    confirmation: Literal[
        "none", "customer_confirmation", "operator_approval", "both"
    ] = "none"
    platforms: list[Literal["telegram", "bale"]] = Field(
        default_factory=lambda: ["telegram", "bale"], min_length=1, max_length=2
    )
    store_policy: str = "active_store"
    bot_policy: str = "active_owned_bot"
    service_available: bool = True
    unavailable_reason: str | None = None
    simulator: Literal["deterministic", "unavailable"] = "deterministic"
    dry_run: bool = True
    sensitive_inputs: list[str] = Field(default_factory=list)
    sensitive_outputs: list[str] = Field(default_factory=list)
    audit: Literal["metadata_only"] = "metadata_only"
    deprecated: bool = False
    replacement: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def safe_policy(self):
        """Make unsafe mutation/retry combinations invalid at registration."""
        if not _KEY.fullmatch(self.key) or self.key.split(".")[0] in {
            "os",
            "sys",
            "subprocess",
            "builtins",
            "importlib",
        }:
            raise ValueError("action_unsafe_key")
        if self.key.split(".")[1] in {
            "execute_python",
            "execute_javascript",
            "execute_js",
            "execute_command",
            "run_sql",
            "call_url",
            "invoke_service",
            "call_method",
            "call_backend_method",
        }:
            raise ValueError("action_unsafe_key")
        mutation = self.side_effect not in {"none", "read_only"}
        if mutation and self.idempotency != "required":
            raise ValueError("action_mutation_requires_idempotency")
        if mutation and self.transaction == "read_only":
            raise ValueError("action_mutation_requires_transaction")
        if self.side_effect == "irreversible" and self.max_retries:
            raise ValueError("action_unsafe_retry")
        if self.max_retries and (
            not self.retry_requires_idempotency or self.idempotency == "not_applicable"
        ):
            raise ValueError("action_retry_requires_idempotency")
        if len(set(self.platforms)) != len(self.platforms):
            raise ValueError("action_duplicate_platform")
        bounded_json(self.input_schema)
        bounded_json(self.output_schema)
        return self


class Invocation(StrictModel):
    """Untrusted operation data; identity is supplied through a separate principal."""

    invocation_id: str = Field(min_length=36, max_length=36)
    action_key: str = Field(max_length=81)
    action_version: str = Field(default="1.0.0", max_length=32)
    input: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    mode: Literal["live", "dry_run", "simulation"] = "live"
    workflow_id: str | None = Field(default=None, max_length=36)
    workflow_revision: int | None = Field(default=None, ge=1)
    workflow_run_id: str | None = Field(default=None, max_length=36)
    node_id: str | None = Field(default=None, max_length=64)
    correlation_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_-]*$")
    request_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_-]*$")
    locale: str = Field(default="fa-IR", max_length=20)
    timezone: str = Field(default="Asia/Tehran", max_length=64)
    attempt: int = Field(default=0, ge=0, le=5)
    approval_receipt: str | None = Field(default=None, max_length=200)
    confirmation_receipt: str | None = Field(default=None, max_length=200)
    timestamp: str | None = Field(default=None, max_length=40)

    @model_validator(mode="before")
    @classmethod
    def check_resource_bounds(cls, value):
        """Reject dangerous JSON before descending into input values."""
        bounded_json(value)
        return value

    @model_validator(mode="after")
    def valid_identity(self):
        """Operation and optional trace IDs must be canonical UUIDs."""
        for field in ("invocation_id", "workflow_id", "workflow_run_id"):
            value = getattr(self, field)
            if value is not None and str(UUID(value)) != value:
                raise ValueError("action_invalid_identifier")
        if bool(self.workflow_id) != bool(self.workflow_revision):
            raise ValueError("action_workflow_revision_required")
        return self


class ActionError(StrictModel):
    """Safe stable failure suitable for both UI and future MCP adapters."""

    code: str
    message: str = "عملیات انجام نشد؛ ورودی و دسترسی را بررسی کنید."


class ActionResult(StrictModel):
    """One transport-independent outcome, including safe no-effect previews."""

    status: Status
    output: dict | None = None
    error: ActionError | None = None
    retryable: bool = False
    retry_after_seconds: int | None = None
    execution_receipt: str | None = None
    side_effect_receipt: str | None = None
    correlation_id: str
    duration_ms: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    simulated: bool = False
    dry_run: bool = False
    exact_preview: bool = False
    audit: dict = Field(default_factory=dict)
