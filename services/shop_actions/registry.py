"""Resolve only explicitly registered key/version/model/adapter combinations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from pydantic import BaseModel, ValidationError

from services.shop_actions.contracts import (
    ActionDescriptor,
    ActionRejected,
    bounded_json,
    redact,
)

Adapter = Callable[[object, object, BaseModel], Awaitable[dict]]


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """Trusted code binding; public metadata never contains Python service names."""

    descriptor: ActionDescriptor
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    adapter: Adapter | None
    preflight: Adapter | None = None
    simulate: Callable[[dict], dict] | None = None

    def input(self, value: dict) -> BaseModel:
        """Validate bounded input without echoing private values in errors."""
        bounded_json(value)
        try:
            return self.input_model.model_validate(value)
        except (ValidationError, ValueError, TypeError, RecursionError):
            raise ActionRejected("action_invalid_input") from None

    def output(self, value: dict) -> dict:
        """Fail closed when an adapter produces undeclared or invalid data."""
        bounded_json(value)
        try:
            return self.output_model.model_validate(value).model_dump(mode="json")
        except (ValidationError, ValueError, TypeError, RecursionError):
            raise ActionRejected("action_invalid_output") from None

    def safe_output(self, value: dict) -> dict:
        """Persist/replay only the declared output after sensitive redaction."""
        return redact(self.output(value), self.descriptor.sensitive_outputs)


class Registry:
    """A versioned allowlist; unknown keys cannot trigger reflection or imports."""

    def __init__(self) -> None:
        """Start an explicit registry without package scanning or plugin loading."""
        self._specs: dict[tuple[str, str], ActionSpec] = {}

    def register(self, value: ActionSpec) -> None:
        """Reject duplicates and drift between advertised and executable schemas."""
        descriptor = ActionDescriptor.model_validate(value.descriptor.model_dump())
        key = descriptor.key, descriptor.version
        if key in self._specs:
            raise ActionRejected("action_duplicate")
        if (
            descriptor.input_schema != value.input_model.model_json_schema()
            or descriptor.output_schema != value.output_model.model_json_schema()
        ):
            raise ActionRejected("action_schema_mismatch")
        if descriptor.service_available and value.adapter is None:
            raise ActionRejected("action_adapter_required")
        self._specs[key] = value

    def resolve(self, key: str, version: str) -> ActionSpec:
        """Resolve exact reviewed versions; ranges are never silently upgraded."""
        value = self._specs.get((key, version))
        if value is None:
            code = (
                "action_version_unavailable"
                if any(item[0] == key for item in self._specs)
                else "action_unknown"
            )
            raise ActionRejected(code)
        return value

    def catalog(self) -> list[dict]:
        """Return safe deterministic public metadata sorted by key and version."""
        return [
            self._specs[key].descriptor.model_dump(mode="json")
            for key in sorted(self._specs)
        ]
