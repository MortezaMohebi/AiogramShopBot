"""Portable typed Action mapping values with no executable expressions."""

from typing import Literal

from pydantic import Field, model_validator

from services.shop_workflow_schema import Scalar, StrictModel


class ActionInputSource(StrictModel):
    """Read one declared variable, typed constant or allowlisted public context key."""

    kind: Literal["variable", "constant", "context"]
    name: str = Field(default="", max_length=100)
    value: Scalar = None

    @model_validator(mode="after")
    def exclusive_source(self):
        """Reject hidden alternate sources rather than merging multiple meanings."""
        if self.kind == "constant" and self.name:
            raise ValueError("action_constant_has_name")
        if self.kind != "constant" and self.value is not None:
            raise ValueError("action_reference_invalid")
        return self
