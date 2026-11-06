"""Closed, typed designer requests shared with WPMCP's actual MCP catalog."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from services.shop_mcp.patches import Patch
from services.shop_workflow_schema import (
    BotAssignment,
    BotId,
    Definition,
    EditorLayout,
    Platform,
    StrictModel,
)
from services.shop_workflow_simulator import (
    SimulatedCustomer,
    SimulationEvent,
)


class StoreRequest(StrictModel):
    """Select one explicitly granted native Store."""

    store_id: BotId


class ContextRequest(StrictModel):
    """Discover granted Stores before selecting an operational Store."""

    store_id: BotId | None = None


class ToolCall(StrictModel):
    """A private transport envelope; the closed catalog validates arguments."""

    name: str = Field(min_length=1, max_length=80)
    arguments: dict


class ResourceRequest(StoreRequest):
    """Read one allowlisted Store resource and bounded metadata page."""

    name: str = Field(min_length=1, max_length=80)
    page: int = Field(default=1, ge=1, le=100_000)


class PromptRequest(StoreRequest):
    """Request guidance with bounded untrusted requirements, not permission."""

    name: str = Field(min_length=1, max_length=80)
    requirements: str = Field(default="", max_length=4000)


class PageRequest(StoreRequest):
    """Bound pages and searches without a global Bot registration limit."""

    page: int = Field(default=1, ge=1, le=100_000)
    q: str = Field(default="", max_length=120)


class WorkflowRequest(StoreRequest):
    """Address a Workflow only inside the selected Store."""

    workflow_id: BotId


class WorkflowGet(WorkflowRequest):
    """Read the head or an immutable, specifically numbered revision."""

    revision: int | None = Field(default=None, ge=1)


class WorkflowList(PageRequest):
    """Filter current draft identities without returning full definitions."""

    status: Literal["draft", "archived", "deleted", "all"] = "draft"


class WorkflowPage(WorkflowRequest):
    """Page owned revision metadata."""

    page: int = Field(default=1, ge=1, le=100_000)


class Mutation(StoreRequest):
    """Retain this UUID and the entire request across an uncertain retry."""

    operation_id: BotId


class CreateWorkflow(Mutation):
    """Create a draft; stage mutating Action templates for review."""

    id: BotId
    expected_revision: Literal[0]
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    template: Literal[
        "blank",
        "return_request",
        "wholesale_application",
    ] = "blank"


class WorkflowMutation(Mutation, WorkflowRequest):
    """Require the immutable draft base for every existing Workflow edit."""

    expected_revision: int = Field(ge=1)


class MetadataEdit(WorkflowMutation):
    """Edit metadata without replacing graph fields implicitly."""

    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def explicit_edit(self):
        """Require a value and reject explicit nulls on selected fields."""
        fields = self.model_fields_set & {"name", "description"}
        if not fields or any(getattr(self, key) is None for key in fields):
            raise ValueError("mcp_metadata_required")
        return self


class DefinitionEdit(WorkflowMutation):
    """Replace a portable graph while preserving unrelated metadata."""

    definition: Definition
    layout: EditorLayout | None = None


class PatchEdit(WorkflowMutation):
    """Apply an atomic ordered batch of allowlisted domain edits."""

    patches: list[Patch] = Field(min_length=1, max_length=128)


class AssignmentEdit(WorkflowMutation):
    """Change only draft assignment, never live customer routing."""

    assignment: BotAssignment


class RestoreWorkflow(WorkflowMutation):
    """Copy an owned historical definition into a new draft revision."""

    revision: int = Field(ge=1)


class DuplicateWorkflow(CreateWorkflow):
    """Pin both a source revision and its current head before copying."""

    source_workflow_id: BotId
    source_revision: int = Field(ge=1)
    expected_source_revision: int = Field(ge=1)


class ChangeSetCreate(WorkflowMutation):
    """Persist a proposal, not a domain edit or approval decision."""

    id: BotId
    definition: Definition | None = None
    layout: EditorLayout | None = None
    patches: list[Patch] | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    @model_validator(mode="after")
    def one_edit(self):
        """Keep replacement and incremental patch requests unambiguous."""
        if (self.definition is None) == (self.patches is None):
            raise ValueError("mcp_one_edit_required")
        return self


class ChangeSetRequest(StoreRequest):
    """Address a proposal owned by the current grant."""

    change_set_id: BotId


class ChangeSetGet(ChangeSetRequest):
    """Read the current or an immutable prior proposal version."""

    version: int | None = Field(default=None, ge=1)


class ChangeSetMutation(ChangeSetRequest, Mutation):
    """Compare and swap proposal content before apply, cancel or update."""

    expected_version: int = Field(ge=1)


class ChangeSetUpdate(ChangeSetMutation):
    """Patch the current proposal while retaining history."""

    patches: list[Patch] = Field(min_length=1, max_length=128)


class ValidateWorkflow(WorkflowRequest):
    """Validate the saved graph or one explicitly supplied inert proposal."""

    definition: Definition | None = None


class Simulation(StoreRequest):
    """Accept synthetic events only; this never executes a commerce Action."""

    bot_id: BotId
    platform: Platform
    context: SimulatedCustomer = Field(default_factory=SimulatedCustomer)
    events: list[SimulationEvent] = Field(default_factory=list, max_length=100)


class SimulateWorkflow(Simulation, WorkflowRequest):
    """Pin a saved revision for a safe preview."""

    revision: int = Field(ge=1)


class SimulateChangeSet(Simulation, ChangeSetRequest):
    """Preview the current proposal without creating a Workflow revision."""


class CompareRevisions(WorkflowRequest):
    """Compare exact owned revision numbers."""

    left: int = Field(ge=1)
    right: int = Field(ge=1)


class OperationStatus(StoreRequest):
    """Recover the exact result of an operation belonging to this grant."""

    operation_id: BotId


class ActionList(PageRequest):
    """Inspect registered typed Actions; this is not an executor."""

    bot_id: BotId | None = None
    platform: Platform | None = None


class ActionDetail(StoreRequest):
    """Read one exact version of an allowlisted Action contract."""

    key: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=40)
    bot_id: BotId | None = None
    platform: Platform | None = None


class RuntimeList(StoreRequest):
    """Page redacted operational Run metadata in one granted Store."""

    page: int = Field(default=1, ge=1, le=100_000)
    workflow_id: BotId | None = None


class RuntimeRun(StoreRequest):
    """Inspect one owned Run without exposing customer values."""

    run_id: BotId


class CatalogPage(StoreRequest):
    """Read current public catalog metadata under one owned Bot's ACL."""

    bot_id: BotId
    page: int = Field(default=1, ge=1, le=10_001)
    page_size: int = Field(default=20, ge=1, le=50)


class CatalogSearch(CatalogPage):
    """Search through the existing typed catalog contract."""

    query: str = Field(default="", max_length=100)
    field: Literal["all", "name", "sku", "description"] = "all"
    category_id: int | None = Field(default=None, ge=1)


class CatalogProduct(StoreRequest):
    """Read a Bot-visible public product or its exact sales unit."""

    bot_id: BotId
    product_id: int = Field(ge=1, le=9_007_199_254_740_991)
