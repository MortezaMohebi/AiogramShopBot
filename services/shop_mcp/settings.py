"""Default-off deployment trust for the private WPMCP integration."""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from services.shop_mcp.contracts import McpRejected
from services.shop_mcp.proofs import ProofConfiguration, decode_json_object
from services.shop_service_controls import service_override


@dataclass(frozen=True, slots=True)
class McpSettings:
    """Server-selected settings cannot be supplied through tool arguments."""

    enabled: bool = False
    proofs: ProofConfiguration | None = None

    def __post_init__(self) -> None:
        """Require explicit trust when the adapter is enabled."""
        if type(self.enabled) is not bool or (
            self.enabled and not isinstance(self.proofs, ProofConfiguration)
        ):
            raise ValueError("mcp_configuration_invalid")


def _keys(value) -> dict[str, Ed25519PublicKey]:
    """Load bounded raw Ed25519 public keys, never a URL or private key."""
    if not isinstance(value, dict) or not 1 <= len(value) <= 8:
        raise ValueError("invalid_keys")
    result = {}
    for key_id, encoded in value.items():
        if not isinstance(key_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", key_id,
        ):
            raise ValueError("invalid_key_id")
        if not isinstance(encoded, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{43}", encoded,
        ):
            raise ValueError("invalid_public_key")
        raw = base64.b64decode(encoded + "=", altchars=b"-_", validate=True)
        result[key_id] = Ed25519PublicKey.from_public_bytes(raw)
    return result


def from_environment() -> McpSettings:
    """Stay disabled until every required trust setting is configured."""
    override = service_override("mcp")
    enabled = os.environ.get("SHOP_MCP_ENABLED", "false") if override is None else str(override).lower()
    if enabled == "false":
        return McpSettings()
    if enabled != "true":
        raise McpRejected("mcp_configuration_invalid", 503)
    return configured_trust()


def configured_trust() -> McpSettings:
    """Validate the deployment trust before a dashboard can enable MCP."""
    try:
        issuer = os.environ["SHOP_MCP_GATEWAY_ISSUER"].rstrip("/")
        parsed = urlsplit(issuer)
        if (
            parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password
            or parsed.query or parsed.fragment
        ):
            raise ValueError("invalid_issuer")
        installation = str(UUID(os.environ["SHOP_MCP_INSTALLATION_ID"]))
        encoded = os.environ["SHOP_MCP_GATEWAY_KEYS_JSON"]
        if len(encoded) > 16_384:
            raise ValueError("key_set_too_large")
        keys = decode_json_object(encoded.encode("utf-8"))
        if (
            not isinstance(keys, dict)
            or set(keys) != {"delegation", "approval"}
        ):
            raise ValueError("invalid_trust_sets")
        return McpSettings(
            enabled=True,
            proofs=ProofConfiguration(
                issuer=issuer, audience="urn:bot-workflows:" + installation,
                delegation_keys=_keys(keys["delegation"]),
                approval_keys=_keys(keys["approval"]),
            ),
        )
    except (KeyError, ValueError, TypeError, RecursionError):
        raise McpRejected("mcp_configuration_invalid", 503) from None
