"""Native consent, delegation grants and replay guards for the WPMCP adapter.

Operation approval decisions belong exclusively to WPMCP. These records never
provide an alternate approve/deny mechanism for business or Runtime operations.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DDL,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    inspect,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from models.base import Base


class McpGrant(Base):
    """An explicitly consented, independently revocable native staff grant."""

    __tablename__ = "shop_mcp_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    staff_id: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    staff_version: Mapped[int] = mapped_column(Integer, nullable=False)
    gateway_issuer: Mapped[str] = mapped_column(String(300), nullable=False)
    audience: Mapped[str] = mapped_column(String(200), nullable=False)
    gateway_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    gateway_client_id: Mapped[str] = mapped_column(String(200), nullable=False)
    gateway_tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    gateway_workspace_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    gateway_connection_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    __table_args__ = (
        UniqueConstraint(
            "gateway_issuer",
            "gateway_connection_id",
            name="uq_mcp_grant_gateway_connection",
        ),
        CheckConstraint("version > 0", name="ck_mcp_grant_version"),
        CheckConstraint(
            "staff_version > 0",
            name="ck_mcp_grant_staff_version",
        ),
        CheckConstraint(
            "length(scopes_json) <= 4096",
            name="ck_mcp_grant_scopes_size",
        ),
    )


class McpGrantStore(Base):
    """Store selections in a grant never replace live native memberships."""

    __tablename__ = "shop_mcp_grant_stores"

    grant_id: Mapped[str] = mapped_column(
        ForeignKey("shop_mcp_grants.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class McpPairing(Base):
    """A short-lived signed gateway request awaiting native manager consent."""

    __tablename__ = "shop_mcp_pairings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    identity_json: Mapped[str] = mapped_column(Text, nullable=False)
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False)
    stores_json: Mapped[str] = mapped_column(Text, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="RESTRICT"),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    __table_args__ = (
        CheckConstraint(
            "length(identity_json) <= 8192",
            name="ck_mcp_pairing_identity_size",
        ),
        CheckConstraint(
            "length(stores_json) <= 4096",
            name="ck_mcp_pairing_stores_size",
        ),
        CheckConstraint(
            "length(scopes_json) <= 4096",
            name="ck_mcp_pairing_scopes_size",
        ),
    )


class McpNonce(Base):
    """A consumed request ID, including enrollment before a grant exists."""

    __tablename__ = "shop_mcp_nonces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    grant_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )


class McpRequest(Base):
    """Bind an operation UUID to one grant, tool and complete normalized input.

    This journal is committed with the domain receipt. It records execution,
    never an independent human approval decision.
    """

    __tablename__ = "shop_mcp_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    grant_id: Mapped[str] = mapped_column(
        ForeignKey("shop_mcp_grants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    tool: Mapped[str] = mapped_column(String(80), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
    )
    result_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','succeeded','awaiting_gateway','cancelled')",
            name="ck_mcp_request_state",
        ),
        CheckConstraint(
            "length(arguments_json) <= 262144",
            name="ck_mcp_request_size",
        ),
    )


class McpChangeSet(Base):
    """A versioned proposal that has no effect until explicitly applied."""

    __tablename__ = "shop_mcp_change_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    grant_id: Mapped[str] = mapped_column(
        ForeignKey("shop_mcp_grants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # A proposed new Workflow has no domain row yet; deliberately no FK here.
    workflow_id: Mapped[str] = mapped_column(String(36), nullable=False)
    base_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="draft",
    )
    base_json: Mapped[str] = mapped_column(Text, nullable=False)
    effect_operation_id: Mapped[str | None] = mapped_column(String(36))
    applied_revision: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("version > 0", name="ck_mcp_changes_version"),
        CheckConstraint(
            "base_revision >= 0",
            name="ck_mcp_changes_base_revision",
        ),
        CheckConstraint(
            "kind IN ('create','save','restore','duplicate','archive')",
            name="ck_mcp_changes_kind",
        ),
        CheckConstraint(
            "status IN ('draft','pending_gateway','applied','cancelled',"
            "'expired')",
            name="ck_mcp_changes_status",
        ),
    )


class McpChangeSetRevision(Base):
    """Append-only evidence of each displayed proposal version."""

    __tablename__ = "shop_mcp_change_set_revisions"

    change_set_id: Mapped[str] = mapped_column(
        ForeignKey("shop_mcp_change_sets.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        unique=True,
    )
    proposal_json: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    risk: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("version > 0", name="ck_mcp_proposal_version"),
        CheckConstraint(
            "risk IN ('low','high','destructive')",
            name="ck_mcp_proposal_risk",
        ),
        CheckConstraint(
            "length(proposal_json) <= 262144",
            name="ck_mcp_proposal_size",
        ),
    )


class McpIntent(Base):
    """Immutable native preparation and recoverable execution state.

    This stores no human decision. WPMCP proves its decision for the exact
    canonical evidence hash before native admission can change domain state.
    """

    __tablename__ = "shop_mcp_intents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    grant_id: Mapped[str] = mapped_column(
        ForeignKey("shop_mcp_grants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    grant_version: Mapped[int] = mapped_column(Integer, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="prepared",
    )
    approval_id: Mapped[str | None] = mapped_column(String(36))
    result_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('prepared','admitted','succeeded')",
            name="ck_mcp_intent_state",
        ),
        UniqueConstraint("approval_id", name="uq_mcp_intent_approval"),
        CheckConstraint(
            "length(evidence_json) <= 1048576",
            name="ck_mcp_intent_evidence_size",
        ),
    )


@event.listens_for(Session, "before_flush")
def protect_mcp_proposals(session, _context, _instances):
    """Reject ORM updates or deletion of immutable proposal versions."""
    for row in list(session.dirty) + list(session.deleted):
        if isinstance(row, McpIntent):
            mutable = {"state", "approval_id", "result_json"}
            if row in session.deleted or any(
                inspect(row).attrs[key].history.has_changes()
                for key in McpIntent.__table__.columns.keys()
                if key not in mutable
            ):
                raise ValueError("mcp_intent_immutable")
        if isinstance(row, McpChangeSetRevision) and (
            row in session.deleted
            or session.is_modified(row, include_collections=False)
        ):
            raise ValueError("mcp_proposal_immutable")


# PostgreSQL enforces the same append-only rule for bulk SQL and maintenance
# code, independently of the ordinary ORM guard above.
event.listen(
    McpChangeSetRevision.__table__,
    "after_create",
    DDL("""
CREATE FUNCTION reject_mcp_proposal_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'mcp_proposal_immutable'; END;
$$ LANGUAGE plpgsql
""").execute_if(dialect="postgresql"),
)
event.listen(
    McpChangeSetRevision.__table__,
    "after_create",
    DDL("""
CREATE TRIGGER mcp_proposal_immutable BEFORE UPDATE OR DELETE
ON shop_mcp_change_set_revisions
FOR EACH ROW EXECUTE FUNCTION reject_mcp_proposal_mutation()
""").execute_if(dialect="postgresql"),
)
event.listen(
    McpChangeSetRevision.__table__,
    "after_drop",
    DDL("DROP FUNCTION IF EXISTS reject_mcp_proposal_mutation()").execute_if(
        dialect="postgresql"
    ),
)


event.listen(
    McpIntent.__table__,
    "after_create",
    DDL("""
CREATE FUNCTION protect_mcp_intent_evidence() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'mcp_intent_immutable';
  END IF;
  IF ROW(NEW.id, NEW.grant_id, NEW.store_id, NEW.kind, NEW.grant_version,
         NEW.request_sha256, NEW.request_json, NEW.evidence_json,
         NEW.evidence_sha256, NEW.execution_json,
         NEW.created_at, NEW.expires_at)
     IS DISTINCT FROM
     ROW(OLD.id, OLD.grant_id, OLD.store_id, OLD.kind, OLD.grant_version,
         OLD.request_sha256, OLD.request_json, OLD.evidence_json,
         OLD.evidence_sha256, OLD.execution_json,
         OLD.created_at, OLD.expires_at)
  THEN
    RAISE EXCEPTION 'mcp_intent_immutable';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql
""").execute_if(dialect="postgresql"),
)
event.listen(
    McpIntent.__table__,
    "after_create",
    DDL("""
CREATE TRIGGER mcp_intent_immutable BEFORE UPDATE OR DELETE ON shop_mcp_intents
FOR EACH ROW EXECUTE FUNCTION protect_mcp_intent_evidence()
""").execute_if(dialect="postgresql"),
)
event.listen(
    McpIntent.__table__,
    "after_drop",
    DDL("DROP FUNCTION IF EXISTS protect_mcp_intent_evidence()").execute_if(
        dialect="postgresql"
    ),
)


MCP_MODELS = (
    McpGrant,
    McpGrantStore,
    McpPairing,
    McpNonce,
    McpRequest,
    McpChangeSet,
    McpChangeSetRevision,
    McpIntent,
)
