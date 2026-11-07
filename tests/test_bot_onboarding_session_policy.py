"""Exercise bot onboarding with a live session and expired step-up proof.

The real signed HTTP boundary, Store scope, encrypted credentials, persistence,
and receiver service run here. Only provider I/O and polling are fake.
"""

from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

import config
from dashboard import shop_multibot_management_api, shop_multibot_receiver_api
from models.shop_admin_control import AdminSession
from models.shop_multibot import ShopBot, ShopBotCredential
from models.shop_multibot_receiver import ShopBotReceiver
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_bot_verification as verification
from services import shop_multibot_receiver_control as receivers
from tests.test_campaign_admin_store_scope import STORE_A, campaign_app

TOKEN = "12345678:" + "A" * 35


@pytest.fixture
def onboarding_app(campaign_app, monkeypatch):
    """Keep session authentication valid while expiring the step-up timestamp."""
    fixture = campaign_app
    monkeypatch.setenv("SHOP_SECURITY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("MULTIBOT_WEBHOOK_BASE_URL", "https://hooks.example.org")
    monkeypatch.setattr(config, "MULTIBOT_V2_RUNTIME_ENABLED", True)
    member = fixture.db.get(ShopStaff, 7)
    member.role = "superadmin"
    profile = security.profile_for(fixture.db, 7)
    now = security.clock()
    secret = security.begin_mfa(fixture.db, profile, now=now)
    security.confirm_mfa(
        fixture.db, profile, security.totp(secret, now.timestamp()), now=now,
    )
    fixture.db.get(AdminSession, fixture.session_id).reauthenticated_at = (
        now - security.REAUTH_LIMIT - timedelta(seconds=1)
    )
    fixture.db.commit()

    async def throttle(*args):
        """Avoid Redis while retaining all authentication and record checks."""

    monkeypatch.setattr(shop_multibot_management_api, "throttle", throttle)
    monkeypatch.setattr(shop_multibot_receiver_api, "throttle", throttle)

    async def identity(platform, token):
        """Return a deterministic provider identity for the disposable token."""
        assert (platform, token) == ("telegram", TOKEN)
        return verification.ProviderBotIdentity(12345678, "offline_test_bot")

    monkeypatch.setattr(verification, "provider_get_me", identity)
    started = []

    async def check_lease():
        """Model the owned receiver supervisor without opening a provider."""

    async def start_polling(bot_id):
        """Record receiver startup without creating a live worker."""
        started.append(bot_id)

    fixture.app.state.multi_bot_supervisor = SimpleNamespace(
        owns_lease=True, check_lease=check_lease, start_polling=start_polling,
    )
    fixture.app.state.test_started_bots = started

    class Provider:
        """Implement only the read calls needed for safe Polling activation."""

        async def get_me(self):
            """Return the exact identity verified during credential setup."""
            return SimpleNamespace(id=12345678)

        async def get_webhook_info(self):
            """Require an empty webhook without deleting any webhook."""
            return SimpleNamespace(url="")

    @asynccontextmanager
    async def provider(platform, token, *, bot_id):
        """Bind provider access to the verified bot and its encrypted token."""
        assert (platform, token) == ("telegram", TOKEN)
        assert fixture.db.get(ShopBot, bot_id) is not None
        yield Provider()

    monkeypatch.setattr(receivers, "provider_client", provider)
    return fixture


async def create_verified_bot(app):
    """Drive real create, secret storage, and identity verification endpoints."""
    response = await app.request("POST", "/bot-registry", payload={
        "store_id": STORE_A, "platform": "telegram", "slug": "session-test",
        "name": "Session test bot",
    })
    assert response.status_code == 201, response.text
    bot_id = response.json()["bot"]["id"]
    response = await app.request(
        "POST", f"/bot-registry/{bot_id}/credentials/stage", payload={"token": TOKEN},
    )
    assert response.status_code == 201, response.text
    assert TOKEN not in response.text
    version = response.json()["credential_version"]
    response = await app.request(
        "POST", f"/bot-registry/{bot_id}/verify", payload={"version": version},
    )
    assert response.status_code == 200, response.text
    return bot_id, version


@pytest.mark.asyncio
async def test_onboarding_and_activation_do_not_repeat_password_or_mfa(onboarding_app):
    """An authenticated administrator can fully onboard despite old step-up."""
    app = onboarding_app
    bot_id, version = await create_verified_bot(app)
    response = await app.request(
        "POST", f"/bot-registry/{bot_id}/receiver/stage", payload={"mode": "polling"},
    )
    assert response.status_code == 201, response.text
    response = await app.request(
        "POST", f"/bot-registry/{bot_id}/receiver/activate",
        payload={"expected_version": response.json()["version"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "active"
    assert app.db.get(ShopBot, bot_id).status == "active"
    assert app.db.get(ShopBotReceiver, bot_id).state == "active"
    assert app.app.state.test_started_bots == [bot_id]
    credential = app.db.query(ShopBotCredential).filter_by(
        bot_id=bot_id, version=version,
    ).one()
    assert credential.state == "active" and TOKEN not in credential.ciphertext
    assert security.utc(app.db.get(AdminSession, app.session_id).reauthenticated_at) < (
        security.clock() - security.REAUTH_LIMIT
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["delete", "revoke", "disable"])
async def test_destructive_bot_operations_keep_recent_mfa_requirement(
    onboarding_app, operation,
):
    """Onboarding cannot be used to discard a bot's persisted credentials."""
    app = onboarding_app
    bot_id, version = await create_verified_bot(app)
    bot = app.db.get(ShopBot, bot_id)
    route = f"/bot-registry/{bot_id}"
    method, payload = "DELETE", {}
    if operation == "revoke":
        method, route = "POST", route + "/credentials/revoke"
        payload = {"version": version}
    elif operation == "disable":
        method, route = "POST", route + "/state"
        payload = {"expected_version": bot.version, "state": "disabled", "reason": "Test removal"}
    response = await app.request(method, route, payload=payload)
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "reauthentication_required"
    assert app.db.get(ShopBot, bot_id).status == "draft"
    assert app.db.query(ShopBotCredential).filter_by(bot_id=bot_id).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "content", "sales", "marketing"])
async def test_onboarding_still_requires_server_owned_admin_permission(onboarding_app, role):
    """Removing step-up never grants ordinary roles bot-management access."""
    app = onboarding_app
    app.db.get(ShopStaff, 7).role = role
    app.db.commit()
    response = await app.request("POST", "/bot-registry", payload={
        "store_id": STORE_A, "platform": "telegram", "slug": "forbidden-bot",
        "name": "Forbidden bot",
    })
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "permission_denied"


@pytest.mark.asyncio
async def test_revoked_session_cannot_onboard(onboarding_app):
    """A stale browser cookie cannot reuse the onboarding exemption."""
    app = onboarding_app
    app.db.get(AdminSession, app.session_id).revoked_at = security.clock()
    app.db.commit()
    response = await app.request("POST", "/bot-registry", payload={
        "store_id": STORE_A, "platform": "telegram", "slug": "revoked-bot",
        "name": "Revoked bot",
    })
    assert response.status_code == 401, response.text
