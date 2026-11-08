"""Typed native preparation requests and purpose-isolated approval claims."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictInt

from services.shop_mcp.tool_contracts import Mutation, WorkflowMutation
from services.shop_runtime.contracts import BindingSpec
from services.shop_workflow_schema import BotId, StrictModel

IntentKind = Literal[
    "changes.apply",
    "workflow.publish",
    "workflow.rollback",
    "runtime.gate",
    "runtime.retry",
    "runtime.cancel",
    "runtime.delivery_retry",
]


class PreparePublication(WorkflowMutation):
    """Review an immutable revision, current head and routing selection."""

    revision: int = Field(ge=1)
    bindings: list[BindingSpec] = Field(min_length=1, max_length=100)


class PrepareRollback(PreparePublication):
    """Select an owned publication for a separate rollback review."""

    publication_id: BotId


class PrepareChangeSet(Mutation):
    """Prepare an already frozen exact proposal version for WPMCP review."""

    change_set_id: BotId
    expected_version: int = Field(ge=1)


class PrepareGate(Mutation):
    """Review Store or Bot opt-in flags and their exact current version."""

    bot_id: BotId | None
    expected_version: int = Field(ge=0)
    enabled: bool
    killed: bool


class PrepareRun(Mutation):
    """Review a pinned Run recovery without any fresh customer input."""

    run_id: BotId
    expected_version: int = Field(ge=0)


class PrepareDelivery(Mutation):
    """Review only a definitely rejected, current delivery attempt."""

    outbox_id: BotId
    expected_attempts: int = Field(ge=1, le=4)


class Approval(StrictModel):
    """Bind a WPMCP decision to one immutable evidence hash."""

    v: StrictInt = Field(ge=1, le=1)
    iss: str = Field(min_length=1, max_length=300)
    aud: str = Field(min_length=1, max_length=200)
    sub: str = Field(min_length=1, max_length=200)
    client_id: str = Field(min_length=1, max_length=200)
    tenant_id: BotId
    workspace_id: BotId
    connection_id: BotId
    grant_id: BotId
    grant_version: StrictInt = Field(ge=1, le=2_147_483_647)
    operation_id: BotId
    approval_id: BotId
    intent_id: BotId
    kind: IntentKind
    store_id: BotId
    intent_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    iat: StrictInt = Field(ge=1, le=9_007_199_254_740_991)
    exp: StrictInt = Field(ge=1, le=9_007_199_254_740_991)
    jti: BotId


class PrivatePreparation(StrictModel):
    """Private envelope with a strict model for each closed intent kind."""

    kind: IntentKind
    arguments: dict


class IntentRequest(StrictModel):
    """Select an intent without conferring Store or approval authority."""

    intent_id: BotId


class CommitRequest(IntentRequest):
    """Accept a signed decision without replacement business data."""

    approval_proof: str = Field(min_length=1, max_length=16_384)


class ReceiptRequest(StrictModel):
    """Inspect a prior native receipt without repeating its business effect."""

    operation_id: BotId
