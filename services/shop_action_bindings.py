"""Validate and replay portable Action mappings without importing live adapters."""

from __future__ import annotations

from typing import Annotated, Literal, get_args, get_origin
from datetime import date, datetime

from pydantic import TypeAdapter

from services.shop_actions.contracts import ActionRejected
from services.shop_actions.definitions import definition as action_definition
from services.shop_workflow_conditions import cast_value

PUBLIC_CONTEXT = frozenset(
    {
        "context.platform",
        "context.customer_name",
        "context.store_name",
        "context.bot_name",
    }
)
ACTION_PORTS = ("success", "error", "retry", "pending_approval", "unavailable")


def _contract(config):
    """Resolve a pure exact version; no Python method names are interpreted."""
    contract = action_definition(config["action_key"], config["action_version"])
    if contract is None:
        from services.shop_actions.definitions import definitions

        known = any(
            item.descriptor.key == config["action_key"] for item in definitions()
        )
        raise ActionRejected(
            "action_version_unavailable" if known else "action_unknown"
        )
    return contract


def _types(annotation):
    """Reduce only typing unions/literals to allowed primitive types."""
    origin = get_origin(annotation)
    if origin is Literal:
        return {type(item) for item in get_args(annotation)}
    if origin is not None:
        args = get_args(annotation)
        if origin in {list, dict}:
            return {origin}
        return set().union(*(_types(item) for item in args))
    return {annotation}


def _compatible(field, variable, name, *, output=False, action_key=""):
    """Only compatible scalar/reference assignments enter declared variables."""
    primitive = _types(field.annotation)
    if variable.type.endswith("_ref"):
        kind = variable.type.removesuffix("_ref")
        allowed = name == kind + "_id" or (
            output
            and name == "id"
            and action_key == "catalog.get_product"
            and kind == "product"
        )
        return int in primitive and allowed
    if variable.type == "integer":
        return int in primitive
    if variable.type == "boolean":
        return bool in primitive
    if variable.type in {"string", "enum", "date", "datetime"}:
        if output and variable.type in {"date", "datetime"}:
            return (date if variable.type == "date" else datetime) in primitive
        if str not in primitive:
            return False
        if output and variable.type == "enum":
            return get_origin(field.annotation) is Literal and set(
                get_args(field.annotation)
            ) <= set(variable.choices)
        if get_origin(field.annotation) is Literal and not output:
            return variable.type == "enum" and set(variable.choices) <= set(
                get_args(field.annotation)
            )
        return True
    return False


def _unwrap(name, value):
    """Convert an explicit product/order reference to its declared ID field only."""
    if isinstance(value, dict):
        if set(value) == {"kind", "id"} and name == value["kind"] + "_id":
            return value["id"]
        raise ActionRejected("action_input_type_mismatch")
    return value


def _validate_constant(field, name, value):
    """Respect the Action's real bounds/literals, including strict integer IDs."""
    annotation = (
        Annotated[field.annotation, *field.metadata]
        if field.metadata
        else field.annotation
    )
    return TypeAdapter(annotation).validate_python(_unwrap(name, value), strict=True)


def binding_findings(node, declarations, platforms, edges):
    """Return semantic findings so incomplete drafts remain editable."""
    findings = []
    config = node.config
    try:
        contract = _contract(config)
    except ActionRejected as error:
        return [(error.code, "Action یا نسخهٔ انتخاب‌شده در دسترس نیست.", "error")]
    fields = contract.input_model.model_fields
    mappings = config["input_mapping"]
    for name, field in fields.items():
        if field.is_required() and name not in mappings:
            findings.append(
                ("action_input_required", "ورودی الزامی Action را متصل کنید.", "error")
            )
    for name, source in mappings.items():
        if name not in fields:
            findings.append(
                (
                    "action_input_unknown",
                    "این ورودی در قرارداد Action وجود ندارد.",
                    "error",
                )
            )
            continue
        if source["kind"] == "constant":
            try:
                _validate_constant(fields[name], name, source["value"])
            except (ValueError, TypeError):
                findings.append(
                    (
                        "action_constant_invalid",
                        "مقدار ثابت با نوع و محدودیت ورودی سازگار نیست.",
                        "error",
                    )
                )
        elif source["kind"] == "context":
            if source["name"] not in PUBLIC_CONTEXT:
                findings.append(
                    (
                        "action_context_forbidden",
                        "این کلید Context قابل استفاده نیست.",
                        "error",
                    )
                )
            elif str not in _types(fields[name].annotation):
                findings.append(
                    (
                        "action_input_type_mismatch",
                        "نوع Context با ورودی Action سازگار نیست.",
                        "error",
                    )
                )
        else:
            variable = declarations.get(source["name"])
            if variable is None:
                findings.append(
                    ("action_unknown_variable", "متغیر اتصال تعریف نشده است.", "error")
                )
            elif not _compatible(fields[name], variable, name):
                findings.append(
                    (
                        "action_input_type_mismatch",
                        "نوع متغیر با ورودی Action سازگار نیست.",
                        "error",
                    )
                )
    outputs = contract.output_model.model_fields
    for name, target in config["output_mapping"].items():
        if name not in outputs or any(
            path == name or path.startswith(name + ".")
            for path in contract.descriptor.sensitive_outputs
        ):
            findings.append(
                (
                    "action_output_unknown",
                    "این خروجی برای اتصال به متغیر مجاز نیست.",
                    "error",
                )
            )
        elif target not in declarations:
            findings.append(
                ("action_unknown_variable", "متغیر خروجی تعریف نشده است.", "error")
            )
        elif not _compatible(
            outputs[name],
            declarations[target],
            name,
            output=True,
            action_key=contract.descriptor.key,
        ):
            findings.append(
                (
                    "action_output_type_mismatch",
                    "نوع خروجی با متغیر سازگار نیست.",
                    "error",
                )
            )
    actual_ports = {edge.port for edge in edges if edge.source == node.id}
    if not set(ACTION_PORTS) <= actual_ports:
        findings.append(
            (
                "action_transition_required",
                "مقصد همهٔ نتیجه‌های Action را مشخص کنید.",
                "error",
            )
        )
    if not set(platforms) <= set(contract.descriptor.platforms):
        findings.append(
            (
                "action_platform_unavailable",
                "Action از همهٔ پیام‌رسان‌های هدف پشتیبانی نمی‌کند.",
                "error",
            )
        )
    if not contract.descriptor.service_available:
        findings.append(
            (
                contract.descriptor.unavailable_reason or "action_service_unavailable",
                "Adapter واقعی این Action آماده نیست؛ پیش‌نمایش فقط دادهٔ آزمایشی دارد.",
                "warning",
            )
        )
    if contract.descriptor.deprecated:
        findings.append(
            (
                "action_deprecated",
                "این نسخه منسوخ شده است؛ جایگزین را بررسی کنید.",
                "warning",
            )
        )
    return findings


def resolve_inputs(config, values) -> dict:
    """Read only exact keys; no attribute traversal or expression evaluation."""
    contract = _contract(config)
    inputs = {}
    for name, source in config["input_mapping"].items():
        if name not in contract.input_model.model_fields:
            raise ActionRejected("action_input_unknown")
        if source["kind"] == "constant":
            value = source["value"]
        else:
            if source["kind"] == "context" and source["name"] not in PUBLIC_CONTEXT:
                raise ActionRejected("action_context_forbidden")
            if source["name"] not in values:
                raise ActionRejected("action_input_unresolved")
            value = values[source["name"]]
        inputs[name] = _unwrap(name, value)
    try:
        return contract.input_model.model_validate(inputs).model_dump(mode="json")
    except ValueError:
        raise ActionRejected("action_invalid_input") from None


def write_outputs(config, output, values, declarations) -> None:
    """Validate every write before updating the bounded local variable dictionary."""
    contract = _contract(config)
    updates = {}
    for name, target in config["output_mapping"].items():
        field = contract.output_model.model_fields.get(name)
        variable = declarations.get(target)
        if field is None or variable is None or name not in output:
            raise ActionRejected("action_output_unknown")
        if not _compatible(
            field, variable, name, output=True, action_key=contract.descriptor.key
        ):
            raise ActionRejected("action_output_type_mismatch")
        value = output[name]
        if variable.type.endswith("_ref") and value is not None:
            value = {"kind": variable.type.removesuffix("_ref"), "id": value}
        try:
            updates[target] = cast_value(variable, value)
        except (ValueError, TypeError):
            raise ActionRejected("action_output_type_mismatch") from None
    values.update(updates)
