"""Verify an exact WPMCP human decision without a native approve endpoint."""

from __future__ import annotations

import hmac

from pydantic import ValidationError

from services import shop_admin_security as security
from services.shop_mcp.approval_contracts import Approval
from services.shop_mcp.contracts import McpRejected
from services.shop_mcp.proofs import verified_claims


def verify(token, *, row, principal, configuration) -> Approval:
    """Bind purpose, gateway identity, expiry and native review evidence."""
    try:
        value = Approval.model_validate(
            verified_claims(
                token,
                kind="wpmcp-approval+jwt",
                keys=configuration.approval_keys,
            )
        )
        identity = principal.delegation
        instant = int(security.clock().timestamp())
        if (
            value.iss != configuration.issuer
            or value.aud != configuration.audience
            or value.iss != identity.iss
            or value.aud != identity.aud
            or any(
                getattr(value, key) != getattr(identity, key)
                for key in (
                    "sub",
                    "client_id",
                    "tenant_id",
                    "workspace_id",
                    "connection_id",
                    "grant_id",
                    "grant_version",
                )
            )
            or value.operation_id != row.id
            or value.intent_id != row.id
            or value.kind != row.kind
            or value.store_id != row.store_id
            or value.grant_version != row.grant_version
            or not hmac.compare_digest(
                value.intent_sha256, row.evidence_sha256
            )
            or value.iat > instant + 5
            or value.iat < instant - 120
            or value.exp <= instant
            or not 0 < value.exp - value.iat <= 120
        ):
            raise ValueError("approval_mismatch")
        return value
    except (ValueError, TypeError, ValidationError, RecursionError):
        raise McpRejected("mcp_approval_invalid", 401) from None
