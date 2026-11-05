"""Portable, strict Studio definitions; no renderer or execution state lives here."""

from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

Platform = Literal["telegram", "bale"]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
VariableName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
BotId = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
    ),
    AfterValidator(lambda value: str(UUID(value))),
]
VariableType = Literal[
    "string",
    "integer",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "enum",
    "product_ref",
    "category_ref",
    "order_ref",
    "customer_ref",
]


class StrictModel(BaseModel):
    """Reject unknown fields, implicit coercion and non-finite numeric data."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Reference(StrictModel):
    """An explicit structured reference, never an unrestricted customer object."""

    kind: Literal["product", "category", "order", "customer"]
    id: int = Field(ge=1, le=9_007_199_254_740_991)


Scalar = Union[str, int, bool, Reference, None]


class ConditionRule(StrictModel):
    """One allowlisted comparison against a declared or public context variable."""

    kind: Literal["rule"] = "rule"
    variable: str = Field(max_length=80)
    operator: Literal["eq", "neq", "gt", "lt", "contains", "exists", "is_empty"]
    value: Scalar = None


class ConditionGroup(StrictModel):
    """A bounded Boolean expression tree, without code or free-form operators."""

    kind: Literal["all", "any"]
    terms: list["Condition"] = Field(min_length=1, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def bound_depth(cls, value):
        """Reject hostile nesting before recursive Pydantic parsing occurs."""
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 6:
                raise ValueError("condition_depth_exceeded")
            if isinstance(item, dict):
                terms = item.get("terms", [])
                if isinstance(terms, list):
                    pending.extend((child, depth + 1) for child in terms)
        return value


Condition = Annotated[Union[ConditionRule, ConditionGroup], Field(discriminator="kind")]
ConditionGroup.model_rebuild()


class Variable(StrictModel):
    """A local workflow/input declaration with a bounded typed default."""

    name: VariableName
    type: VariableType
    scope: Literal["workflow", "input"] = "workflow"
    label: str = Field(default="", max_length=120)
    choices: list[str] = Field(default_factory=list, max_length=100)
    default: Scalar = None

    @model_validator(mode="after")
    def check_default(self):
        """Type-check defaults with the same rules used by simulation inputs."""
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("duplicate_enum_choice")
        if self.default is not None:
            from services.shop_workflow_conditions import cast_value

            cast_value(self, self.default)
        return self


class WorkflowButton(StrictModel):
    """Platform-independent navigation, without sensitive callback payloads."""

    key: Identifier
    label: str = Field(min_length=1, max_length=80)
    type: Literal[
        "callback",
        "url",
        "action",
        "request_contact",
        "back",
        "cancel",
        "main_menu",
    ] = "callback"
    row: int = Field(default=0, ge=0, le=15)
    target: str = Field(default="", max_length=64)
    action: str = Field(default="", max_length=64)
    url: str = Field(default="", max_length=2048)
    visible_when: Condition | None = None
    platforms: list[Platform] = Field(
        default_factory=lambda: ["telegram", "bale"], max_length=2
    )

    @model_validator(mode="after")
    def check_url(self):
        """Only an explicit HTTPS link may leave the simulated conversation."""
        if self.url:
            parsed = urlsplit(self.url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or "/bot" in parsed.path.lower()
                and parsed.hostname in {"api.telegram.org", "tapi.bale.ai"}
            ):
                raise ValueError("unsafe_button_url")
        if self.target and not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_-]{0,63}", self.target
        ):
            raise ValueError("invalid_button_target")
        return self


class WorkflowChoice(StrictModel):
    """One stable choice value, shared by switch and input configuration."""

    key: Identifier
    label: str = Field(min_length=1, max_length=120)
    value: Scalar = None


class WorkflowNode(StrictModel):
    """A typed domain step; position, selection and React fields are forbidden."""

    id: Identifier
    type: str = Field(max_length=64)
    label: str = Field(default="", max_length=120)
    config: dict[str, JsonValue] = Field(default_factory=dict)
    platform_overrides: dict[Platform, dict[str, JsonValue]] = Field(
        default_factory=dict
    )
    max_visits: int | None = Field(default=None, ge=1, le=25)

    @model_validator(mode="after")
    def type_configuration(self):
        """Validate base and partial overrides against one allowlisted node schema."""
        from services.shop_workflow_catalog import (
            NODE_SPECS,
            OVERRIDABLE_FIELDS,
        )

        spec = NODE_SPECS.get(self.type)
        if spec is None:
            raise ValueError("unknown_node_type")
        self.config = spec.config_model.model_validate(self.config).model_dump(
            mode="json"
        )
        for override in self.platform_overrides.values():
            if set(override) - OVERRIDABLE_FIELDS:
                raise ValueError("platform_override_changes_contract")
            # Validating the merged value preserves partial override intent while
            # still rejecting unknown fields and wrong primitive types.
            spec.config_model.model_validate(self.config | override)
        encoded = canonical_json(
            self.model_dump(exclude={"config", "platform_overrides"})
        )
        encoded += canonical_json(self.config) + canonical_json(self.platform_overrides)
        if re.search(r"[0-9]{5,}:[A-Za-z0-9_-]{20,}", encoded):
            raise ValueError("provider_secret_not_allowed")
        return self


class WorkflowEdge(StrictModel):
    """A stable named transition independent of a canvas handle implementation."""

    id: Identifier
    source: Identifier
    target: Identifier
    port: str = Field(default="next", min_length=1, max_length=64)


class EntryPoint(StrictModel):
    """A future routing declaration; registering it never changes live menus."""

    kind: Literal["start", "command", "menu", "internal"]
    key: Identifier
    node_id: Identifier
    command: str = Field(default="", max_length=32, pattern=r"^[a-z0-9_]*$")


class BotAssignment(StrictModel):
    """Store ownership is resolved separately from a client-side identifier list."""

    mode: Literal["selected", "all_eligible"] = "all_eligible"
    bot_ids: list[BotId] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_selection(self):
        """Avoid ambiguous repeated IDs or hidden selections in all-Bot mode."""
        if len(set(self.bot_ids)) != len(self.bot_ids):
            raise ValueError("duplicate_bot_assignment")
        if self.mode == "all_eligible" and self.bot_ids:
            raise ValueError("all_bots_has_explicit_ids")
        return self


class ErrorPolicy(StrictModel):
    """Resource budgets bound a preview; they are not a platform capacity quota."""

    max_steps: int = Field(default=200, ge=1, le=500)
    on_error: Literal["stop", "cancel"] = "stop"
    message: str = Field(
        default="اجرای فرایند متوقف شد؛ دوباره شروع کنید یا با پشتیبانی تماس بگیرید.",
        max_length=1000,
    )


class TimeoutPolicy(StrictModel):
    """Declarative future timeout policy; preview uses virtual time only."""

    seconds: int = Field(default=1800, ge=1, le=86400)
    outcome: Literal["cancel", "end"] = "cancel"


class Definition(StrictModel):
    """Canonical business graph, without workflow ownership or runtime sessions."""

    schema_version: Literal[1] = 1
    target_platforms: list[Platform] = Field(
        default_factory=lambda: ["telegram", "bale"],
        min_length=1,
        max_length=2,
    )
    assignment: BotAssignment = Field(default_factory=BotAssignment)
    entry_points: list[EntryPoint] = Field(default_factory=list, max_length=40)
    nodes: list[WorkflowNode] = Field(default_factory=list, max_length=200)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=800)
    variables: list[Variable] = Field(default_factory=list, max_length=100)
    error_policy: ErrorPolicy = Field(default_factory=ErrorPolicy)
    timeout_policy: TimeoutPolicy = Field(default_factory=TimeoutPolicy)

    @model_validator(mode="after")
    def exclude_provider_secrets(self):
        """Apply the credential guard to defaults and every nested definition field."""
        if re.search(r"[0-9]{5,}:[A-Za-z0-9_-]{20,}", canonical_json(self)):
            raise ValueError("provider_secret_not_allowed")
        return self


class Position(StrictModel):
    """Finite bounded coordinates avoid renderer overflow and arbitrary data."""

    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)


class Viewport(Position):
    """Only camera geometry belongs to the visual layout."""

    zoom: float = Field(default=1.0, ge=0.1, le=4.0)


class EditorLayout(StrictModel):
    """Renderer-independent node coordinates and optional camera geometry."""

    positions: dict[Identifier, Position] = Field(default_factory=dict)
    viewport: Viewport = Field(default_factory=lambda: Viewport(x=0.0, y=0.0))


class ValidationIssue(StrictModel):
    """A localized graph/field finding with stable machine identifiers."""

    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    node_id: str | None = None
    field: str | None = None
    platform: Platform | None = None
    blocks_activation: bool = True


class ValidationReport(StrictModel):
    """Simulation suitability is distinct from absent live Runtime readiness."""

    valid: bool
    can_simulate: bool
    activation_available: Literal[False] = False
    issues: list[ValidationIssue]


def canonical_json(value) -> str:
    """Encode stable UTF-8 JSON without executable objects or non-finite numbers."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
