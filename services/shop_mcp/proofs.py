"""Verify purpose-isolated Ed25519 proofs without remote key discovery."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping, NoReturn

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, ValidationError

from services.shop_mcp.contracts import Delegation, McpRejected
from services.shop_workflow_schema import StrictModel

MAX_PROOF_BYTES = 16_384
MAX_PROOF_LIFETIME = 60
CLOCK_TOLERANCE = 5
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")


class _Header(StrictModel):
    """Accept a fixed algorithm and a configured key identifier."""

    alg: Literal["EdDSA"]
    typ: str = Field(min_length=1, max_length=60)
    kid: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


@dataclass(frozen=True, slots=True)
class ProofConfiguration:
    """Pinned public keys are deployment trust, never request or tool input."""

    issuer: str
    audience: str
    delegation_keys: Mapping[str, Ed25519PublicKey]
    approval_keys: Mapping[str, Ed25519PublicKey]

    def __post_init__(self) -> None:
        """Copy key sets so runtime mutation cannot silently replace trust."""
        for name in ("delegation_keys", "approval_keys"):
            keys = dict(getattr(self, name))
            if not keys or len(keys) > 8 or any(
                not isinstance(key, Ed25519PublicKey)
                for key in keys.values()
            ):
                raise ValueError("mcp_trust_configuration_invalid")
            object.__setattr__(self, name, MappingProxyType(keys))
        if not self.issuer or not self.audience:
            raise ValueError("mcp_trust_configuration_invalid")
        request_keys = {
            key.public_bytes_raw() for key in self.delegation_keys.values()
        }
        approval_keys = {
            key.public_bytes_raw() for key in self.approval_keys.values()
        }
        if request_keys & approval_keys:
            raise ValueError("mcp_approval_key_must_be_distinct")


def _decode(segment: str) -> bytes:
    """Require canonical unpadded base64url."""
    if not segment or not _BASE64URL.fullmatch(segment):
        raise ValueError("invalid_base64url")
    value = base64.b64decode(
        segment + "=" * (-len(segment) % 4), altchars=b"-_", validate=True
    )
    if base64.urlsafe_b64encode(value).rstrip(b"=").decode() != segment:
        raise ValueError("noncanonical_base64url")
    return value


def _unique_members(pairs):
    """Reject JSON ambiguity before a claim or header can pick an identity."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_member")
        result[key] = value
    return result


def _reject_constant(_value: str) -> NoReturn:
    """Reject JSON NaN and Infinity before typed parsing."""
    raise ValueError("nonfinite_json")


def decode_json_object(value: bytes) -> dict:
    """Decode UTF-8 JSON without duplicate members or numeric constants."""
    result = json.loads(
        value.decode("utf-8"), object_pairs_hook=_unique_members,
        parse_constant=_reject_constant,
    )
    if not isinstance(result, dict):
        raise ValueError("json_object_required")
    return result


def verified_claims(
    token: str, *, kind: str, keys: Mapping[str, Ed25519PublicKey]
) -> dict:
    """Verify the dedicated proof type against pinned keys."""
    try:
        if not isinstance(token, str) or len(token) > MAX_PROOF_BYTES:
            raise ValueError("proof_size_invalid")
        head, payload, signature = token.split(".")
        header = _Header.model_validate(decode_json_object(_decode(head)))
        if header.typ != kind or header.kid not in keys:
            raise ValueError("proof_type_invalid")
        decoded_signature = _decode(signature)
        if len(decoded_signature) != 64:
            raise ValueError("signature_size_invalid")
        keys[header.kid].verify(
            decoded_signature, (head + "." + payload).encode("ascii")
        )
        return decode_json_object(_decode(payload))
    except (
        ValueError, TypeError, ValidationError, UnicodeError,
        binascii.Error, InvalidSignature, RecursionError,
    ):
        raise McpRejected("mcp_proof_invalid", 401) from None


def verify_delegation(
    token: str, *, method: str, target: str, body: bytes,
    configuration: ProofConfiguration, now: int | None = None,
) -> Delegation:
    """Authenticate request bytes before native grant authorization."""
    try:
        value = Delegation.model_validate(
            verified_claims(
                token, kind="wpmcp-delegation+jwt",
                keys=configuration.delegation_keys,
            )
        )
        instant = int(time.time()) if now is None else now
        if (
            value.iss != configuration.issuer
            or value.aud != configuration.audience
            or value.iat > instant + CLOCK_TOLERANCE
            or value.iat < instant - MAX_PROOF_LIFETIME
            or value.exp <= instant
            or not 0 < value.exp - value.iat <= MAX_PROOF_LIFETIME
            or value.method != method
            or value.target != target
            or not hmac.compare_digest(
                value.body_sha256, hashlib.sha256(body).hexdigest()
            )
        ):
            raise ValueError("proof_binding_invalid")
        return value
    except (ValueError, TypeError, ValidationError):
        raise McpRejected("mcp_proof_invalid", 401) from None
