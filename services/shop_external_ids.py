"""Stable interchange identifiers derived from immutable model ownership."""

from __future__ import annotations

import re

from sqlalchemy import String, cast, literal

from services.shop_admin_security import SecurityRejected

EXTERNAL_ID_FIELD = "external_id"
_RECORD_ID = re.compile(r"[1-9][0-9]{0,18}")


def external_id(model_name: str, store_id: str, record_id: int) -> str:
    """Return the same public identifier for a record on every export."""
    return f"{model_name}:{store_id}:{record_id}"


def external_id_column(model_name: str, model: type):
    """Build the equivalent query projection without persisting aliases."""
    return literal(f"{model_name}:") + model.store_id + literal(":") + cast(
        model.id, String,
    )


def external_record_id(value: str, *, model_name: str, store_id: str) -> int:
    """Resolve an identifier only for the selected model and Store."""
    owner, _, raw_id = value.rpartition(":")
    if (
        owner != f"{model_name}:{store_id}" or not _RECORD_ID.fullmatch(raw_id)
        or int(raw_id) > 9_223_372_036_854_775_807
    ):
        raise SecurityRejected("invalid_external_reference", 422)
    return int(raw_id)
