"""Shared strict request contracts for HTTP and future authenticated MCP callers."""

from typing import Literal

from pydantic import Field, ValidationError

from services import shop_admin_security as security
from services.shop_workflow_schema import (
    BotId,
    Definition,
    EditorLayout,
    StrictModel,
)


class Operation(StrictModel):
    """One immutable receipt identity and an explicit optimistic draft base."""

    operation_id: BotId
    expected_revision: int = Field(ge=1)


class DuplicateDraft(StrictModel):
    """A new identity and metadata for copying a specifically addressed source."""

    id: BotId
    operation_id: BotId
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)


class CreateDraft(DuplicateDraft):
    """A current-Store creation; client-selected ownership is never accepted."""

    template: Literal["blank", "return_request", "wholesale_application"] = "blank"


class SaveDraft(Operation):
    """Metadata, typed graph and layout are updated as one immutable revision."""

    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    definition: Definition
    layout: EditorLayout


class RestoreDraft(Operation):
    """An owned historical number, never a caller-supplied raw snapshot."""

    revision: int = Field(ge=1)


class ValidateDraft(StrictModel):
    """Unsaved graph validation remains a read-only service operation."""

    definition: Definition | None = None


def checked_payload(model, value) -> dict:
    """Validate at the shared service boundary without exposing raw bad inputs."""
    try:
        return model.model_validate(value).model_dump(mode="json")
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise security.SecurityRejected(
            "workflow_invalid_request", 422
        ) from None
