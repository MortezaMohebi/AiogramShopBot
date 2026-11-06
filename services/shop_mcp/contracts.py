"""Pure, bounded identity contracts for a configured WPMCP delegation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field, StrictInt, model_validator

from services.shop_workflow_schema import BotId, StrictModel

SCOPES = frozenset(
    {
        "workflow:read", "workflow:write", "workflow:validate",
        "workflow:simulate", "workflow:publish", "workflow:rollback",
        "runtime:read", "runtime:control", "actions:read", "bots:read",
        "audit:read", "catalog:read",
    }
)


class McpRejected(ValueError):
    """Carry a stable public error code and HTTP status."""

    def __init__(self, code: str, status: int = 403) -> None:
        """Keep claims, signatures and database errors private."""
        self.code, self.status = code, status
        super().__init__(code)


class Delegation(StrictModel):
    """A gateway identity bound to exact request bytes and a native grant."""

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
    scopes: list[str] = Field(min_length=1, max_length=12)
    method: Literal["POST"]
    target: str = Field(
        min_length=1, max_length=120,
        pattern=r"^/internal/mcp/v1/[a-z/]+$",
    )
    body_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    iat: StrictInt = Field(ge=1, le=9_007_199_254_740_991)
    exp: StrictInt = Field(ge=1, le=9_007_199_254_740_991)
    jti: BotId
    correlation_id: BotId

    @model_validator(mode="after")
    def registered_scopes(self):
        """Accept only unique registered scopes."""
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("mcp_duplicate_scope")
        if set(self.scopes) - SCOPES:
            raise ValueError("mcp_unknown_scope")
        return self


class PairingRequest(StrictModel):
    """A requested Store and scope set without a native staff selection."""

    store_ids: list[BotId] = Field(min_length=1, max_length=32)
    scopes: list[str] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_registered_values(self):
        """Reject ambiguous duplicates and any invented execution scope."""
        if len(set(self.store_ids)) != len(self.store_ids):
            raise ValueError("mcp_duplicate_store")
        if (
            len(set(self.scopes)) != len(self.scopes)
            or set(self.scopes) - SCOPES
        ):
            raise ValueError("mcp_unknown_scope")
        return self


class AccessRequest(StrictModel):
    """A fixed native-access probe used before revealing a sensitive review."""

    store_id: BotId
    required_scope: str = Field(default="workflow:read", max_length=40)


@dataclass(frozen=True, slots=True)
class GatewayCaller:
    """Verified gateway identity, explicitly without native staff authority."""

    delegation: Delegation
