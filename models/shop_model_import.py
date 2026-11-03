"""One-time, session-bound import preview receipts without storing file data.

Receipt consumption is committed atomically with Product/Customer updates.
It prevents a preview from another Store, browser session, context version or
file from authorizing an import, and supports safe outcome reconciliation.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, String, func, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopModelImportPreview(Base):
    """Immutable preview scope and single-use import authorization receipt."""

    __tablename__ = "shop_model_import_previews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    staff_id: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_admin_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    store_context_version: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    dataset_name: Mapped[str] = mapped_column(String(32), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rows: Mapped[int] = mapped_column(Integer, nullable=False)
    creates: Mapped[int] = mapped_column(Integer, nullable=False)
    updates: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    __table_args__ = (
        CheckConstraint(
            "dataset_name IN ('products', 'customers')",
            name="ck_import_preview_dataset",
        ),
        CheckConstraint(
            "rows BETWEEN 1 AND 1000 AND creates >= 0 AND updates >= 0",
            name="ck_import_preview_counts",
        ),
        CheckConstraint(
            "store_context_version > 0",
            name="ck_import_preview_context_version",
        ),
        CheckConstraint(
            "length(file_sha256) = 64",
            name="ck_import_preview_file_sha256",
        ),
        Index(
            "ix_import_previews_staff_session",
            "staff_id", "session_id", "expires_at",
        ),
    )


MODEL_IMPORT_TABLES = frozenset({ShopModelImportPreview.__tablename__})
