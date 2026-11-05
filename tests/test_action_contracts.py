"""Verify public Action contracts reject unsafe resolution and untyped data."""

from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import Field, ValidationError

from services.shop_actions.contracts import (
    ActionDescriptor,
    ActionRejected,
    ActionResult,
    Invocation,
    StrictModel,
    bounded_json,
    redact,
)
from services.shop_actions.registry import ActionSpec, Registry


class Query(StrictModel):
    """A test Action's actual typed input contract."""

    query: str = Field(min_length=2, max_length=100)


class Answer(StrictModel):
    """A test Action's public typed output."""

    count: int = Field(ge=0)


async def answer(_db, _context, _input):
    """Produce an explicit adapter result without framework dispatch."""
    return {"count": 3}


def descriptor(**changes):
    """Build a complete safe read-only descriptor for contract tests."""
    return ActionDescriptor(
        key="catalog.search_products",
        version="1.0.0",
        name="Search",
        description="Search visible catalog",
        category="catalog",
        input_schema=Query.model_json_schema(),
        output_schema=Answer.model_json_schema(),
        **changes,
    )


def spec(**changes):
    """Bind schemas to explicit Python adapters in trusted source only."""
    return ActionSpec(descriptor(**changes), Query, Answer, answer)


def test_duplicate_registration_rejected_without_overwriting_adapter():
    """A duplicate must not silently replace a previously reviewed handler."""
    registry = Registry()
    registry.register(spec())
    with pytest.raises(ActionRejected, match="action_duplicate"):
        registry.register(spec())
    assert registry.resolve("catalog.search_products", "1.0.0").adapter is answer


def test_registry_keeps_versions_explicit():
    """Old pinned workflows must resolve their original version."""
    registry = Registry()
    registry.register(spec())
    old = replace(
        spec(),
        descriptor=descriptor().model_copy(
            update={
                "version": "0.9.0",
                "deprecated": True,
                "replacement": "catalog.search_products@1.0.0",
            }
        ),
    )
    registry.register(old)
    assert registry.resolve("catalog.search_products", "0.9.0").descriptor.deprecated
    with pytest.raises(ActionRejected, match="action_version_unavailable"):
        registry.resolve("catalog.search_products", "^1")


@pytest.mark.parametrize(
    "key",
    [
        "run_sql",
        "execute_python",
        "call_url",
        "invoke_service",
        "call_method",
        "os.system",
        "__import__.module",
        "catalog..read",
        "catalog/read",
    ],
)
def test_unsafe_keys_are_never_registered(key):
    """A catalog entry cannot turn into a generic method/RCE escape hatch."""
    registry = Registry()
    with pytest.raises((ActionRejected, ValidationError)):
        value = descriptor().model_dump() | {"key": key}
        registry.register(replace(spec(), descriptor=ActionDescriptor(**value)))


def test_unknown_action_is_a_safe_stable_error():
    """Unknown keys cannot fall back to reflection or import resolution."""
    with pytest.raises(ActionRejected) as error:
        Registry().resolve("catalog.missing", "1.0.0")
    assert error.value.code == "action_unknown"
    assert error.value.retryable is False


@pytest.mark.parametrize(
    "changes",
    [
        {"side_effect": "write"},
        {"timeout_seconds": 0},
        {"timeout_seconds": 999},
        {"max_retries": 100},
        {"version": "latest"},
        {"platforms": ["telegram", "matrix"]},
        {"side_effect": "business_mutation", "idempotency": "not_applicable"},
        {"side_effect": "irreversible", "max_retries": 2},
    ],
)
def test_invalid_policy_combinations_rejected(changes):
    """Mutation and retry metadata must enforce executable safety rules."""
    with pytest.raises(ValidationError):
        ActionDescriptor(**(descriptor().model_dump() | changes))


def test_registry_detects_schema_descriptor_drift():
    """Advertised input schema must match the model actually validating it."""
    registry = Registry()
    broken = descriptor().model_copy(update={"input_schema": {"type": "object"}})
    with pytest.raises(ActionRejected, match="action_schema_mismatch"):
        registry.register(replace(spec(), descriptor=broken))


def test_input_validation_does_not_coerce_or_accept_unknown_fields():
    """Dashboard input cannot smuggle privileged context through an Action."""
    value = spec()
    for data in ({"query": 42}, {"query": "valid", "store_id": "foreign"}):
        with pytest.raises(ActionRejected, match="action_invalid_input"):
            value.input(data)
    assert value.input({"query": "کالای نمونه"}).query == "کالای نمونه"


def test_output_validation_filters_by_declared_contract():
    """Undeclared secret output causes a failure rather than leaking a payload."""
    value = spec()
    with pytest.raises(ActionRejected, match="action_invalid_output"):
        value.output({"count": 3, "token": "private"})
    assert value.output({"count": 3}) == {"count": 3}


@pytest.mark.parametrize(
    "value",
    [
        {"__proto__": {"admin": True}},
        {"a": {"constructor": "x"}},
        {"query": "x" * 66000},
        {"a": float("inf")},
    ],
)
def test_bounded_json_rejects_pollution_and_resource_abuse(value):
    """Deep/large/non-JSON or prototype keys never enter hashing or validation."""
    with pytest.raises(ActionRejected):
        bounded_json(value)


def test_bounded_json_rejects_recursive_depth():
    """Depth is bounded before invoking recursive schema validation."""
    value = {}
    for _ in range(10):
        value = {"x": value}
    with pytest.raises(ActionRejected, match="action_payload_too_deep"):
        bounded_json(value)


def test_sensitive_redaction_handles_lists_nested_paths_and_token_values():
    """Receipts and logs remove declared PII plus recognizable credentials."""
    value = {
        "count": 3,
        "customer": {"phone": "09123456789"},
        "items": [{"secret": "hidden"}],
        "echo": "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAA",
    }
    safe = redact(value, ("customer.phone", "items.*.secret"))
    assert safe == {
        "count": 3,
        "customer": {"phone": "[redacted]"},
        "items": [{"secret": "[redacted]"}],
        "echo": "[redacted]",
    }
    assert value["customer"]["phone"] == "09123456789"


def test_invocation_cannot_supply_authoritative_identity_or_approval_boolean():
    """Actor/Store/approved fields belong to independent Backend verification."""
    data = {
        "invocation_id": str(uuid4()),
        "action_key": "catalog.search_products",
        "action_version": "1.0.0",
        "input": {"query": "part"},
    }
    for privileged in ("store_id", "bot_id", "customer_id", "scopes", "approved"):
        with pytest.raises(ValidationError):
            Invocation(**(data | {privileged: True}))
    assert Invocation(**data).mode == "live"


def test_safe_result_can_distinguish_pending_and_unavailable():
    """A missing executor is never a successful synthetic live Action."""
    pending = ActionResult(status="pending_approval", correlation_id="request-1")
    unavailable = ActionResult(status="unavailable", correlation_id="request-1")
    assert pending.output is None and unavailable.output is None
    assert pending.retryable is False
