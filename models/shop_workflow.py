"""Store-owned draft heads and immutable portable Workflow revision evidence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from models.base import Base


class ShopWorkflow(Base):
    """A stable Store-owned identity whose current draft is optimistically versioned."""

    __tablename__ = "shop_workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(
        ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("store_id", "key", name="uq_workflow_store_key"),
        UniqueConstraint("id", "store_id", name="uq_workflow_id_store"),
        CheckConstraint("revision > 0", name="ck_workflow_revision"),
        CheckConstraint(
            "status IN ('draft','archived','deleted')",
            name="ck_workflow_state",
        ),
    )


class ShopWorkflowRevision(Base):
    """Immutable snapshot and idempotency receipt; restoration always appends."""

    __tablename__ = "shop_workflow_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "store_id"],
            ["shop_workflows.id", "shop_workflows.store_id"],
            ondelete="RESTRICT",
            name="fk_workflow_revision_owner",
        ),
        UniqueConstraint(
            "workflow_id", "revision", name="uq_workflow_revision_number"
        ),
        UniqueConstraint(
            "store_id", "operation_id", name="uq_workflow_revision_operation"
        ),
        CheckConstraint("revision > 0", name="ck_workflow_snapshot_revision"),
    )


@event.listens_for(Session, "before_flush")
def protect_workflow_revisions(session, _context, _instances):
    """Ordinary application ORM writes may only append revision evidence."""
    for row in list(session.dirty) + list(session.deleted):
        if isinstance(row, ShopWorkflowRevision) and (
            row in session.deleted
            or session.is_modified(row, include_collections=False)
        ):
            raise ValueError("workflow_revision_immutable")
