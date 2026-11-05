"""Durable Runtime state, immutable publications and transactional delivery intents."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    DDL,
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from models.base import Base


def new_id() -> str:
    """Allocate opaque identities without encoding customer or provider values."""
    return str(uuid4())


class Owned:
    """Explicit non-null Store ownership for every Runtime administrative record."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    store_id: Mapped[str] = mapped_column(
        ForeignKey("shop_stores.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PublishedWorkflow(Owned, Base):
    """An exact source revision copied once; activation is stored separately."""

    __tablename__ = "shop_workflow_publications"
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("shop_workflows.id", ondelete="RESTRICT"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    published_by: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="RESTRICT")
    )
    __table_args__ = (
        UniqueConstraint("workflow_id", "revision"),
        UniqueConstraint("id", "store_id"),
    )


class PublicationPreview(Owned, Base):
    """Expiring approval bound to staff, session, request and current entry pointers."""

    __tablename__ = "shop_workflow_publish_previews"
    workflow_id: Mapped[str] = mapped_column(ForeignKey("shop_workflows.id"))
    revision: Mapped[int] = mapped_column(Integer)
    staff_id: Mapped[int] = mapped_column(ForeignKey("shop_staff.id"))
    session_id: Mapped[str] = mapped_column(String(36))
    digest: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSON)
    report: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    publication_id: Mapped[str | None] = mapped_column(
        ForeignKey("shop_workflow_publications.id")
    )


class RuntimeBinding(Owned, Base):
    """CAS-versioned entry pointer; existing Runs never consult this pointer again."""

    __tablename__ = "shop_workflow_bindings"
    bot_id: Mapped[str] = mapped_column(ForeignKey("shop_bots.id"), index=True)
    publication_id: Mapped[str] = mapped_column(String(36))
    workflow_id: Mapped[str] = mapped_column(ForeignKey("shop_workflows.id"))
    kind: Mapped[str] = mapped_column(String(24))
    key: Mapped[str] = mapped_column(String(64))
    node_id: Mapped[str] = mapped_column(String(64))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    eligibility: Mapped[str] = mapped_column(String(24), default="all")
    fallback: Mapped[str] = mapped_column(String(12), default="legacy")
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("bot_id", "kind", "key"),
        ForeignKeyConstraint(
            ["publication_id", "store_id"],
            ["shop_workflow_publications.id", "shop_workflow_publications.store_id"],
        ),
    )


class RuntimeGate(Owned, Base):
    """Persistent Store or Bot opt-in and emergency kill switch; absent means off."""

    __tablename__ = "shop_workflow_gates"
    scope_key: Mapped[str] = mapped_column(String(64), unique=True)
    bot_id: Mapped[str | None] = mapped_column(ForeignKey("shop_bots.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    killed: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)


class RuntimeAudit(Owned, Base):
    """Append-only redacted publication, activation and recovery evidence."""

    __tablename__ = "shop_workflow_runtime_audit"
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("shop_staff.id"))
    action: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class RuntimeSlot(Owned, Base):
    """Serialize first start and every input for one Bot/customer interaction."""

    __tablename__ = "shop_workflow_slots"
    bot_id: Mapped[str] = mapped_column(ForeignKey("shop_bots.id"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    run_id: Mapped[str | None] = mapped_column(String(36))
    next_sequence: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("bot_id", "user_id"),)


class WorkflowRun(Owned, Base):
    """Persistent typed state pinned to one immutable published Workflow."""

    __tablename__ = "shop_workflow_runs"
    bot_id: Mapped[str] = mapped_column(ForeignKey("shop_bots.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("shop_store_customers.id"))
    identity_id: Mapped[int] = mapped_column(ForeignKey("shop_identities.id"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    platform: Mapped[str] = mapped_column(String(12))
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("shop_workflows.id"), index=True
    )
    publication_id: Mapped[str] = mapped_column(String(36), index=True)
    binding_id: Mapped[str] = mapped_column(ForeignKey("shop_workflow_bindings.id"))
    node_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    values: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    lock_version: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_input_id: Mapped[str | None] = mapped_column(String(100))
    last_outbound_id: Mapped[str | None] = mapped_column(String(36))
    correlation_id: Mapped[str] = mapped_column(String(36), default=new_id)
    error_code: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (
        UniqueConstraint("id", "store_id"),
        ForeignKeyConstraint(
            ["publication_id", "store_id"],
            ["shop_workflow_publications.id", "shop_workflow_publications.store_id"],
        ),
        Index("ix_workflow_runs_active", "bot_id", "user_id", "status"),
    )


class WorkflowEvent(Owned, Base):
    """Deduplicated input receipt with safe metadata, never raw customer text."""

    __tablename__ = "shop_workflow_events"
    run_id: Mapped[str] = mapped_column(ForeignKey("shop_workflow_runs.id"), index=True)
    bot_id: Mapped[str] = mapped_column(ForeignKey("shop_bots.id"))
    input_id: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(24))
    node_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))
    correlation_id: Mapped[str] = mapped_column(String(36))
    __table_args__ = (UniqueConstraint("bot_id", "input_id"),)


class WorkflowWait(Owned, Base):
    """One current durable interaction/timeout boundary per Run."""

    __tablename__ = "shop_workflow_waits"
    run_id: Mapped[str] = mapped_column(
        ForeignKey("shop_workflow_runs.id"), unique=True
    )
    node_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(24))
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    epoch: Mapped[int] = mapped_column(Integer)
    resume_node: Mapped[str | None] = mapped_column(String(64))
    timeout_node: Mapped[str | None] = mapped_column(String(64))
    cancel_node: Mapped[str | None] = mapped_column(String(64))


class WorkflowCallback(Owned, Base):
    """Hashed opaque, expiring, single-use capability scoped to exact interaction."""

    __tablename__ = "shop_workflow_callbacks"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("shop_workflow_runs.id"), index=True)
    bot_id: Mapped[str] = mapped_column(ForeignKey("shop_bots.id"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    node_id: Mapped[str] = mapped_column(String(64))
    epoch: Mapped[int] = mapped_column(Integer)
    value: Mapped[str] = mapped_column(String(80))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowActionJob(Owned, Base):
    """Stable action identity reconciles an independent Layer 2 commit after crash."""

    __tablename__ = "shop_workflow_action_jobs"
    run_id: Mapped[str] = mapped_column(ForeignKey("shop_workflow_runs.id"), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    epoch: Mapped[int] = mapped_column(Integer)
    invocation_id: Mapped[str] = mapped_column(String(36), unique=True, default=new_id)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    action_key: Mapped[str] = mapped_column(String(80))
    action_version: Mapped[str] = mapped_column(String(24))
    input: Mapped[dict] = mapped_column(JSON)
    confirmation_id: Mapped[str | None] = mapped_column(Text)
    approval_id: Mapped[str | None] = mapped_column(Text)
    receipt_id: Mapped[str | None] = mapped_column(String(36))
    error_code: Mapped[str | None] = mapped_column(String(80))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    __table_args__ = (UniqueConstraint("run_id", "node_id", "epoch"),)


class WorkflowOutbox(Owned, Base):
    """Transactional outbound intent; private provider credentials never enter it."""

    __tablename__ = "shop_workflow_outbox"
    run_id: Mapped[str] = mapped_column(ForeignKey("shop_workflow_runs.id"), index=True)
    bot_id: Mapped[str] = mapped_column(ForeignKey("shop_bots.id"))
    node_id: Mapped[str] = mapped_column(String(64))
    epoch: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_ids: Mapped[list] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)


class WorkflowDeliveryAttempt(Owned, Base):
    """One physical provider attempt, with an explicit known/unknown outcome."""

    __tablename__ = "shop_workflow_delivery_attempts"
    outbox_id: Mapped[str] = mapped_column(
        ForeignKey("shop_workflow_outbox.id"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(24))
    message_ids: Mapped[list] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (UniqueConstraint("outbox_id", "number"),)


RUNTIME_MODELS = (
    PublishedWorkflow,
    PublicationPreview,
    RuntimeBinding,
    RuntimeGate,
    RuntimeAudit,
    RuntimeSlot,
    WorkflowRun,
    WorkflowEvent,
    WorkflowWait,
    WorkflowCallback,
    WorkflowActionJob,
    WorkflowOutbox,
    WorkflowDeliveryAttempt,
)


@event.listens_for(Session, "before_flush")
def immutable_publications(session, *_):
    """Prevent ORM mutation of exact published versions and audit evidence."""
    for row in session.dirty | session.deleted:
        if isinstance(row, (PublishedWorkflow, RuntimeAudit)):
            raise ValueError("runtime_immutable_record")


# PostgreSQL also protects against direct SQL and bulk ORM writes.
event.listen(
    PublishedWorkflow.__table__,
    "after_create",
    DDL("""
CREATE FUNCTION reject_workflow_publication_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'runtime_immutable_record'; END;
$$ LANGUAGE plpgsql
""").execute_if(dialect="postgresql"),
)
event.listen(
    PublishedWorkflow.__table__,
    "after_create",
    DDL("""
CREATE TRIGGER workflow_publication_immutable BEFORE UPDATE OR DELETE ON shop_workflow_publications
FOR EACH ROW EXECUTE FUNCTION reject_workflow_publication_mutation()
""").execute_if(dialect="postgresql"),
)
event.listen(
    PublishedWorkflow.__table__,
    "after_drop",
    DDL("DROP FUNCTION IF EXISTS reject_workflow_publication_mutation()").execute_if(
        dialect="postgresql"
    ),
)


class WorkflowInbox(Owned, Base):
    """Recoverable normalized input accepted before any outer provider receipt."""

    __tablename__ = "shop_workflow_inbox"
    bot_id: Mapped[str] = mapped_column(ForeignKey("shop_bots.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    input_id: Mapped[str] = mapped_column(String(100))
    sequence: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("shop_workflow_runs.id"))
    node_id: Mapped[str | None] = mapped_column(String(64))
    epoch: Mapped[int | None] = mapped_column(Integer)
    was_existing: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    outcome: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    error_code: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (
        UniqueConstraint("bot_id", "input_id"),
        Index("ix_workflow_inbox_user_created", "bot_id", "user_id", "created_at"),
    )


RUNTIME_MODELS = (*RUNTIME_MODELS, WorkflowInbox)


class WorkflowUpload(Owned, Base):
    """Private verified customer evidence, scoped to the receiving Bot and customer."""

    __tablename__ = "shop_workflow_uploads"
    bot_id: Mapped[str] = mapped_column(ForeignKey("shop_bots.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("shop_store_customers.id"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(16))
    file_id: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


RUNTIME_MODELS = (*RUNTIME_MODELS, WorkflowUpload)
