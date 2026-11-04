"""Typed local comparisons and input normalization, with no expression execution."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from services.shop_workflow_schema import Reference, Variable

PUBLIC_VARIABLES = {
    "context.platform": Variable(name="platform", type="enum", choices=["telegram", "bale"]),
    "context.customer_name": Variable(name="customer_name", type="string"),
    "context.store_name": Variable(name="store_name", type="string"),
    "context.bot_name": Variable(name="bot_name", type="string"),
}
DECIMAL = re.compile(r"^-?[0-9]{1,18}(?:\.[0-9]{1,8})?$")


def cast_value(variable: Variable, value, *, from_input: bool = False):
    """Return a validated local scalar/ref; no implicit bool/integer coercion."""
    if value is None:
        return None
    kind = variable.type
    if kind.endswith("_ref"):
        ref = value if isinstance(value, Reference) else Reference.model_validate(value)
        if ref.kind != kind.removesuffix("_ref"):
            raise ValueError("reference_type_mismatch")
        return ref.model_dump()
    if kind == "boolean":
        if from_input and isinstance(value, str) and value in {"true", "false"}:
            value = value == "true"
        if type(value) is not bool:
            raise ValueError("boolean_required")
        return value
    if kind == "integer":
        if from_input and isinstance(value, str) and re.fullmatch(r"-?[0-9]{1,15}", value):
            value = int(value)
        if type(value) is not int or abs(value) > 9_007_199_254_740_991:
            raise ValueError("integer_required")
        return value
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("string_required")
    if kind == "decimal" and not DECIMAL.fullmatch(value):
        raise ValueError("decimal_required")
    if kind == "enum" and value not in variable.choices:
        raise ValueError("enum_value_required")
    if kind == "date":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("date_required")
        date.fromisoformat(value)
    if kind == "datetime":
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("timezone_required")
    return value


def comparable(variable: Variable, value):
    """Convert a validated value into its exact comparison representation."""
    value = cast_value(variable, value)
    if value is None:
        return None
    if variable.type == "decimal":
        return Decimal(value)
    if variable.type == "date":
        return date.fromisoformat(value)
    if variable.type == "datetime":
        return datetime.fromisoformat(value)
    return value


def condition_errors(condition, declarations: dict[str, Variable]) -> list[str]:
    """Return stable unknown-reference/operator-type findings for a typed tree."""
    if hasattr(condition, "model_dump"):
        condition = condition.model_dump(mode="json")
    if not condition:
        return ["missing_configuration"]
    if condition["kind"] in {"all", "any"}:
        return [code for term in condition["terms"]
                for code in condition_errors(term, declarations)]
    variable = declarations.get(condition["variable"]) or PUBLIC_VARIABLES.get(condition["variable"])
    if variable is None:
        return ["unknown_variable"]
    operator = condition["operator"]
    if operator in {"gt", "lt"} and variable.type not in {"integer", "decimal", "date", "datetime"}:
        return ["condition_type_mismatch"]
    if operator == "contains" and variable.type not in {"string", "enum"}:
        return ["condition_type_mismatch"]
    if operator in {"gt", "lt", "contains"} and condition.get("value") is None:
        return ["condition_type_mismatch"]
    if operator not in {"exists", "is_empty"}:
        try:
            cast_value(variable, condition.get("value"))
        except (ValueError, TypeError):
            return ["condition_type_mismatch"]
    return []


def evaluate_condition(condition, declarations: dict[str, Variable], values: dict) -> bool:
    """Evaluate only structurally validated, bounded typed comparisons."""
    if hasattr(condition, "model_dump"):
        condition = condition.model_dump(mode="json")
    if not condition or condition_errors(condition, declarations):
        return False
    if condition["kind"] in {"all", "any"}:
        results = (evaluate_condition(term, declarations, values) for term in condition["terms"])
        return all(results) if condition["kind"] == "all" else any(results)
    name, operator = condition["variable"], condition["operator"]
    raw = values.get(name)
    if operator == "exists":
        return name in values and raw is not None
    if operator == "is_empty":
        return raw is None or raw == ""
    variable = declarations.get(name) or PUBLIC_VARIABLES[name]
    try:
        left = comparable(variable, raw)
        right = comparable(variable, condition.get("value"))
    except (ValueError, TypeError):
        return False
    if operator == "eq":
        return left == right
    if operator == "neq":
        return left != right
    if left is None or right is None:
        return False
    if operator == "gt":
        return left > right
    if operator == "lt":
        return left < right
    return right in left if operator == "contains" else False
