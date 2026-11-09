"""Validate and apply a complete order within an already authorized row set."""

from typing import Annotated, Protocol

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

OrderId = Annotated[int, Field(gt=0, le=2**63 - 1)]


class DisplayOrder(BaseModel):
    """A bounded replacement order with the browser's previous snapshot."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected: list[OrderId] = Field(min_length=2, max_length=2000)
    ids: list[OrderId] = Field(min_length=2, max_length=2000)


class OrderedRecord(Protocol):
    id: int
    position: int


def apply_display_order(rows: list[OrderedRecord], payload: DisplayOrder) -> None:
    """Reject unrelated or changed rows before assigning any positions."""
    by_id = {row.id: row for row in rows}
    current = [row.id for row in sorted(rows, key=lambda row: (row.position, row.id))]
    if current != payload.expected:
        raise HTTPException(409, "display_order_changed")
    if len(payload.ids) != len(by_id) or set(payload.ids) != set(by_id):
        raise HTTPException(422, "invalid_display_order")
    if current != payload.ids:
        for position, record_id in enumerate(payload.ids):
            by_id[record_id].position = position
