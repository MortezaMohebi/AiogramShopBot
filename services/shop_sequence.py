"""Allocate gapped display positions without user-entered numbers.

A PostgreSQL transaction advisory lock serializes competing insertions for
one table while keeping unrelated tables free to allocate concurrently.
Existing rows are never reordered by this allocator.
"""
from __future__ import annotations

from hashlib import sha256

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

POSITION_STEP = 10
MAX_POSITION = 1_000_000


def next_display_position(session: Session, model: type) -> int:
    """Return a monotonic display sequence for a trusted ORM model.

    Call through AsyncSession.run_sync in the same transaction as the insert.
    The caller owns the commit. PostgreSQL locks per-model allocation keys.
    """
    table = getattr(model, "__table__", None)
    if table is None or "position" not in table.c:
        raise TypeError("A sequenced SQLAlchemy model is required.")

    if session.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(
            sha256(f"shop-display:{table.name}".encode()).digest()[:8],
            byteorder="big", signed=True,
        )
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    maximum = session.scalar(select(func.max(table.c.position)))
    result = max(0, int(maximum or 0)) + POSITION_STEP
    if result > MAX_POSITION:
        raise ValueError("Display sequence is exhausted; rebalance is required.")
    return result
