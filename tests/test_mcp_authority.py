"""Pin the signed WPMCP boundary without a real gateway or customer provider."""

from __future__ import annotations

import base64
import importlib
import json
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

NOW = 1_794_000_000
TARGET = "/internal/mcp/v1/tools/call"
BODY = b'{"name":"context.get_profile","arguments":{}}'
ISSUER = "https://gateway.example.test"
AUDIENCE = "urn:bot-workflows:30000000-0000-4000-8000-000000000001"
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
APPROVAL_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))


def encoded(value: bytes) -> str:
    """Use standard unpadded base64url independently of production helpers."""
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def delegation_claims(**overrides) -> dict:
    """Construct only gateway identity; native staff is never a caller claim."""
    import hashlib

    return {
        "v": 1,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "gateway-test-owner",
        "client_id": "gateway-test-client",
        "tenant_id": "40000000-0000-4000-8000-000000000001",
        "workspace_id": "40000000-0000-4000-8000-000000000002",
        "connection_id": "40000000-0000-4000-8000-000000000003",
        "grant_id": "40000000-0000-4000-8000-000000000004",
        "grant_version": 1,
        "scopes": ["workflow:read", "workflow:validate"],
        "method": "POST",
        "target": TARGET,
        "body_sha256": hashlib.sha256(BODY).hexdigest(),
        "iat": NOW,
        "exp": NOW + 45,
        "jti": str(uuid4()),
        "correlation_id": str(uuid4()),
        **overrides,
    }


def signed(claims=None, *, header=None, raw_header=None, raw_claims=None, key=PRIVATE):
    """Sign actual JWS bytes so malformed claims still have a valid signature."""
    header = header or {
        "alg": "EdDSA", "typ": "wpmcp-delegation+jwt",
        "kid": "wpmcp-delegation-test",
    }
    head = raw_header or json.dumps(header, separators=(",", ":")).encode()
    payload = raw_claims or json.dumps(
        claims or delegation_claims(), separators=(",", ":")
    ).encode()
    message = (encoded(head) + "." + encoded(payload)).encode("ascii")
    return message.decode() + "." + encoded(key.sign(message))


@pytest.fixture
def proof_boundary():
    """Import lazily so missing implementation is an explicit observed RED."""
    try:
        module = importlib.import_module("services.shop_mcp.proofs")
    except ModuleNotFoundError:
        return None, None
    configuration = module.ProofConfiguration(
        issuer=ISSUER,
        audience=AUDIENCE,
        delegation_keys={"wpmcp-delegation-test": PRIVATE.public_key()},
        approval_keys={"wpmcp-approval-test": APPROVAL_PRIVATE.public_key()},
    )
    return module, configuration


def verify(boundary, token, **overrides):
    """Exercise the actual verifier with explicit request bytes and trusted config."""
    module, configuration = boundary
    assert module is not None, "The signed private MCP boundary is missing."
    arguments = {
        "method": "POST", "target": TARGET, "body": BODY,
        "configuration": configuration, "now": NOW,
        **overrides,
    }
    return module.verify_delegation(token, **arguments)


def test_delegation_authenticates_exact_identity_and_request_bytes(proof_boundary):
    """A configured gateway key permits only its bound native installation."""
    result = verify(proof_boundary, signed())
    assert result.sub == "gateway-test-owner"
    assert result.grant_version == 1
    assert result.scopes == ["workflow:read", "workflow:validate"]
    assert result.target == TARGET


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://other-gateway.example.test"},
        {"aud": "urn:bot-workflows:foreign"},
        {"exp": NOW},
        {"iat": NOW + 6},
        {"exp": NOW + 61},
        {"iat": True},
        {"grant_version": 0},
        {"grant_id": "untrusted"},
        {"sub": ""},
        {"scopes": ["workflow:read", "workflow:read"]},
        {"scopes": ["execute:anything"]},
        {"staff_id": 7},
    ],
)
def test_signed_but_untrusted_claims_cannot_grant_authority(proof_boundary, overrides):
    """A real signature does not excuse a wrong issuer, scope or invented staff."""
    module, _ = proof_boundary
    assert module is not None, "The signed private MCP boundary is missing."
    with pytest.raises(module.McpRejected) as rejected:
        verify(proof_boundary, signed(delegation_claims(**overrides)))
    assert rejected.value.status == 401
    assert "gateway-test-owner" not in str(rejected.value)


@pytest.mark.parametrize(
    "change",
    [
        {"method": "GET"},
        {"target": "/internal/mcp/v1/commit"},
        {"body": BODY + b" "},
    ],
)
def test_delegation_cannot_be_retargeted_after_signing(proof_boundary, change):
    """Even semantically equivalent JSON needs its own exact request signature."""
    module, _ = proof_boundary
    assert module is not None, "The signed private MCP boundary is missing."
    with pytest.raises(module.McpRejected):
        verify(proof_boundary, signed(), **change)


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "none", "typ": "wpmcp-delegation+jwt", "kid": "wpmcp-delegation-test"},
        {"alg": "EdDSA", "typ": "JWT", "kid": "wpmcp-delegation-test"},
        {"alg": "EdDSA", "typ": "wpmcp-delegation+jwt", "kid": "unknown-key"},
        {"alg": "EdDSA", "typ": "wpmcp-delegation+jwt", "kid": "wpmcp-approval-test"},
        {"alg": "EdDSA", "typ": "wpmcp-delegation+jwt", "kid": "wpmcp-delegation-test", "jku": "https://attacker.invalid/keys"},
    ],
)
def test_header_cannot_select_an_algorithm_or_external_trust_source(proof_boundary, header):
    """The endpoint trusts only configured delegation keys and the dedicated type."""
    module, _ = proof_boundary
    assert module is not None, "The signed private MCP boundary is missing."
    with pytest.raises(module.McpRejected):
        verify(proof_boundary, signed(header=header))


def test_duplicate_json_members_and_false_signatures_fail_closed(proof_boundary):
    """Ambiguous parsing cannot choose another actor or header after verification."""
    module, _ = proof_boundary
    assert module is not None, "The signed private MCP boundary is missing."
    raw = json.dumps(delegation_claims()).encode()
    duplicate = raw[:-1] + b',"sub":"forged-owner"}'
    tokens = [
        signed(raw_claims=duplicate),
        signed(raw_header=b'{"alg":"none","alg":"EdDSA","typ":"wpmcp-delegation+jwt","kid":"wpmcp-delegation-test"}'),
        signed(key=APPROVAL_PRIVATE),
        "A" * 20_000,
    ]
    for token in tokens:
        with pytest.raises(module.McpRejected):
            verify(proof_boundary, token)


def test_gateway_wire_fixture_is_verified_with_the_same_pinned_native_boundary(proof_boundary):
    """The actual Node signer and Python verifier share identical request bytes."""
    from pathlib import Path

    fixture = json.loads((
        Path(__file__).resolve().parent.parent
        / "contracts/wpmcp/delegation-v1.json"
    ).read_text())
    result = verify(proof_boundary, fixture["token"])
    assert result.sub == "gateway-test-owner"
    assert result.jti == "50000000-0000-4000-8000-000000000001"
