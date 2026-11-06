"""Require explicit, unambiguous deployment trust before enabling WPMCP."""

import base64
import json

import pytest

from services.shop_mcp.contracts import McpRejected
from services.shop_mcp.settings import from_environment
from tests.test_mcp_authority import (
    APPROVAL_PRIVATE, ISSUER, PRIVATE,
)


def public_key(key) -> str:
    """Encode public test keys using the documented raw Ed25519 format."""
    return base64.urlsafe_b64encode(
        key.public_key().public_bytes_raw()
    ).rstrip(b"=").decode()


def configured(monkeypatch) -> dict:
    """Configure public test trust without touching a deployment secret."""
    keys = {
        "delegation": {"wpmcp-delegation-test": public_key(PRIVATE)},
        "approval": {"wpmcp-approval-test": public_key(APPROVAL_PRIVATE)},
    }
    monkeypatch.setenv("SHOP_MCP_ENABLED", "true")
    monkeypatch.setenv("SHOP_MCP_GATEWAY_ISSUER", ISSUER)
    monkeypatch.setenv(
        "SHOP_MCP_INSTALLATION_ID", "30000000-0000-4000-8000-000000000001",
    )
    monkeypatch.setenv("SHOP_MCP_GATEWAY_KEYS_JSON", json.dumps(keys))
    return keys


def test_no_flag_means_disabled_even_with_missing_or_invalid_trust(monkeypatch):
    """Installing the code cannot activate an unconfigured integration."""
    monkeypatch.delenv("SHOP_MCP_ENABLED", raising=False)
    monkeypatch.setenv("SHOP_MCP_GATEWAY_KEYS_JSON", "invalid configuration")
    settings = from_environment()
    assert settings.enabled is False
    assert settings.proofs is None


def test_enabled_configuration_pins_issuer_installation_and_distinct_key_sets(monkeypatch):
    """No external key discovery or native bearer token is needed."""
    configured(monkeypatch)
    settings = from_environment()
    assert settings.enabled is True
    assert settings.proofs.issuer == ISSUER
    assert settings.proofs.audience == (
        "urn:bot-workflows:30000000-0000-4000-8000-000000000001"
    )
    assert set(settings.proofs.delegation_keys) == {"wpmcp-delegation-test"}
    assert set(settings.proofs.approval_keys) == {"wpmcp-approval-test"}


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SHOP_MCP_ENABLED", "yes"),
        ("SHOP_MCP_GATEWAY_ISSUER", "http://gateway.example.test"),
        ("SHOP_MCP_GATEWAY_ISSUER", "https://user:secret@gateway.example.test"),
        ("SHOP_MCP_INSTALLATION_ID", "another installation"),
        ("SHOP_MCP_GATEWAY_KEYS_JSON", '{"jku":"https://attacker.invalid"}'),
    ],
)
def test_incomplete_or_untrusted_configuration_fails_closed(monkeypatch, name, value):
    """A mistyped setting cannot silently change the private trust boundary."""
    configured(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(McpRejected) as rejected:
        from_environment()
    assert rejected.value.code == "mcp_configuration_invalid"
    assert rejected.value.status == 503


def test_duplicate_trust_members_cannot_choose_the_last_public_key(monkeypatch):
    """The loader must reject ambiguous JSON instead of silently replacing trust."""
    keys = configured(monkeypatch)
    raw = (
        '{"delegation":{"wpmcp-delegation-test":'
        + json.dumps(public_key(PRIVATE))
        + ',"wpmcp-delegation-test":'
        + json.dumps(public_key(APPROVAL_PRIVATE))
        + '},"approval":' + json.dumps(keys["approval"]) + '}'
    )
    monkeypatch.setenv("SHOP_MCP_GATEWAY_KEYS_JSON", raw)
    with pytest.raises(McpRejected):
        from_environment()
