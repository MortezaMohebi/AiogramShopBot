"""Reject retired runtime inputs before credentials or provider connections."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from services.shop_admin_security import SecurityRejected
from services.shop_bot_secrets import resolve_active_token
from services.shop_multibot_client import provider_client
from services.shop_runtime.contracts import BindingSpec

BOT_ID = "00000000-0000-4000-8000-000000000101"


@pytest.mark.parametrize("field,value", [("kind", "legacy_bridge"), ("fallback", "legacy")])
def test_workflow_binding_rejects_retired_runtime_contract(field, value):
    """Publication cannot persist bridge entries or receiver fallback modes."""
    binding = {"bot_id": BOT_ID, "kind": "command", "key": "example", "node_id": "start"}
    with pytest.raises(ValidationError):
        BindingSpec.model_validate(binding | {field: value})


def test_environment_credential_cannot_resolve_from_deployment(monkeypatch):
    """Even a forged historical credential never reads an environment token."""
    monkeypatch.setenv("TOKEN", "123456:" + "A" * 32)
    bot = SimpleNamespace(
        id=BOT_ID, platform="telegram", runtime_owner="registry", status="active",
        credential_version=1,
    )
    credential = SimpleNamespace(source="environment", environment_key="TOKEN", ciphertext=None)
    database = SimpleNamespace(get=lambda *_: bot, scalar=lambda *_: credential)
    with pytest.raises(SecurityRejected, match="bot_secret_unavailable"):
        resolve_active_token(database, bot_id=BOT_ID)


@pytest.mark.asyncio
async def test_provider_client_requires_explicit_registry_owner():
    """A platform and token alone cannot select a global receiver transport."""
    with pytest.raises(ValueError, match="registered bot ID"):
        async with provider_client("telegram", "123456:" + "A" * 32):
            pytest.fail("An unscoped provider connection was opened")


def test_registry_ciphertext_rejects_wrong_deployment_key(monkeypatch):
    """Replacing an encryption key cannot trigger a plaintext token fallback."""
    from cryptography.fernet import Fernet
    from services.shop_bot_secrets import decrypt_for_bot, encrypt_for_bot

    monkeypatch.delenv("SHOP_BOT_SECRET_KEY", raising=False)
    monkeypatch.setenv("SHOP_SECURITY_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    token = "123456:" + "A" * 32
    ciphertext = encrypt_for_bot(BOT_ID, "telegram", token)
    assert token not in ciphertext
    monkeypatch.setenv("SHOP_SECURITY_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("TOKEN", token)
    with pytest.raises(SecurityRejected, match="bot_secret_unreadable"):
        decrypt_for_bot(BOT_ID, "telegram", ciphertext)


def test_receiver_authenticator_cannot_be_copied_between_bots(monkeypatch):
    """Webhook authentication uses purpose-bound ciphertext for its exact bot."""
    from cryptography.fernet import Fernet
    from services.shop_bot_secrets import decrypt_receiver_secret, encrypt_receiver_secret

    monkeypatch.setenv("SHOP_BOT_SECRET_KEY", Fernet.generate_key().decode("ascii"))
    authenticator = "A" * 43
    ciphertext = encrypt_receiver_secret(BOT_ID, authenticator)
    assert authenticator not in ciphertext
    assert decrypt_receiver_secret(BOT_ID, ciphertext) == authenticator
    with pytest.raises(SecurityRejected, match="bot_secret_binding_mismatch"):
        decrypt_receiver_secret("00000000-0000-4000-8000-000000000102", ciphertext)


@pytest.mark.asyncio
async def test_receiver_activation_requires_current_exclusive_lease(monkeypatch):
    """A lost process lease prevents database writes or provider mutations."""
    from unittest.mock import AsyncMock
    import config
    from services.shop_multibot_receiver_control import activate_receiver

    monkeypatch.setattr(config, "MULTIBOT_V2_RUNTIME_ENABLED", True)
    supervisor = SimpleNamespace(
        owns_lease=True,
        check_lease=AsyncMock(side_effect=SecurityRejected("receiver_lease_lost", 503)),
    )
    with pytest.raises(SecurityRejected, match="receiver_lease_lost"):
        await activate_receiver(
            object(), bot_id=BOT_ID, actor_id=1, expected_version=1,
            supervisor=supervisor,
        )
    supervisor.check_lease.assert_awaited_once()


@pytest.mark.asyncio
async def test_receiver_activation_rejects_stale_configuration_before_provider(monkeypatch):
    """Optimistic revision checks run before decrypting or sending credentials."""
    from unittest.mock import AsyncMock
    import config
    from services.shop_multibot_receiver_control import activate_receiver

    monkeypatch.setattr(config, "MULTIBOT_V2_RUNTIME_ENABLED", True)
    supervisor = SimpleNamespace(owns_lease=True, check_lease=AsyncMock())
    database = SimpleNamespace(scalar=AsyncMock(side_effect=[object(), SimpleNamespace(version=2)]))
    with pytest.raises(SecurityRejected, match="configuration_changed"):
        await activate_receiver(
            database, bot_id=BOT_ID, actor_id=1, expected_version=1,
            supervisor=supervisor,
        )
    assert database.scalar.await_count == 2
