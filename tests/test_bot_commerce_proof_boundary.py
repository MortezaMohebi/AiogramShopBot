"""Regressions for policy forms with fresh explicit proof and first revisions."""

import pytest

from dashboard import shop_customer_experience_api, shop_store_commerce_api
from models.shop_admin_control import AdminSession
from services.shop_admin_security import SecurityRejected, clock
from tests.test_bot_onboarding_session_policy import onboarding_app
from tests.test_campaign_admin_store_scope import BOT_A, STORE_A


@pytest.mark.asyncio
async def test_expired_step_up_accepts_bot_commerce_proof(onboarding_app, monkeypatch):
    """A fresh password and MFA proof reaches the guarded bot policy API."""
    proofs = []

    async def verify(_db, _staff, payload):
        """Record the proof presented to the native endpoint."""
        proofs.append((payload.current_password, payload.second_factor))

    monkeypatch.setattr(shop_store_commerce_api, "fresh_proof", verify)
    response = await onboarding_app.request(
        "POST", f"/bot-registry/{BOT_A}/commerce", payload={
            "expected_version": 0,
            "cart_enabled": True,
            "credit_enabled": False,
            "current_password": "fresh-test-password",
            "second_factor": "123456",
        },
    )
    assert response.status_code == 200, response.text
    assert proofs == [("fresh-test-password", "123456")]
    assert response.json()["version"] == 1


@pytest.mark.asyncio
async def test_expired_step_up_rejects_invalid_bot_proof(onboarding_app, monkeypatch):
    """The route exception cannot bypass endpoint password verification."""
    async def reject(_db, _staff, _payload):
        """Simulate the native verifier rejecting a bad password."""
        raise SecurityRejected("invalid_credentials", 401)

    monkeypatch.setattr(shop_store_commerce_api, "fresh_proof", reject)
    response = await onboarding_app.request(
        "POST", f"/bot-registry/{BOT_A}/commerce", payload={
            "expected_version": 0,
            "cart_enabled": True,
            "current_password": "incorrect",
            "second_factor": "123456",
        },
    )
    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_first_store_commerce_policy_has_revision_one(onboarding_app, monkeypatch):
    """A new unflushed Store policy receives revision one."""
    app = onboarding_app
    app.db.get(AdminSession, app.session_id).reauthenticated_at = clock()
    app.db.commit()

    async def verify(_db, _staff, _payload):
        """Keep the test focused on policy initialization."""

    monkeypatch.setattr(shop_store_commerce_api, "fresh_proof", verify)
    response = await app.request(
        "POST", f"/stores/{STORE_A}/commerce", payload={
            "expected_version": 0,
            "cart_scope": "bot",
            "credit_scope": "identity",
            "current_password": "fresh-test-password",
            "second_factor": "123456",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 1


@pytest.mark.asyncio
async def test_expired_step_up_accepts_store_checkout_proof(onboarding_app, monkeypatch):
    """A fresh explicit proof can save Store terms after session step-up expiry."""
    proofs = []

    async def verify(_db, _staff, payload):
        """Record only the credentials sent to the endpoint verifier."""
        proofs.append((payload.current_password, payload.second_factor))

    monkeypatch.setattr(shop_customer_experience_api, "fresh_proof", verify)
    response = await onboarding_app.request(
        "POST", f"/stores/{STORE_A}/checkout-policy", payload={
            "expected_version": 0,
            "mode": "manual",
            "terms_version": "qa-v1",
            "terms_text": "Synthetic QA only; no payment or real delivery.",
            "current_password": "fresh-test-password",
            "second_factor": "123456",
        },
    )
    assert response.status_code == 200, response.text
    assert proofs == [("fresh-test-password", "123456")]
    assert response.json()["terms_version"] == "qa-v1"


@pytest.mark.asyncio
async def test_store_checkout_rejects_invalid_proof(onboarding_app, monkeypatch):
    """The step-up exception preserves the endpoint's proof check."""
    async def reject(_db, _staff, _payload):
        """Model a failed password or MFA verification."""
        raise SecurityRejected("invalid_credentials", 401)

    monkeypatch.setattr(shop_customer_experience_api, "fresh_proof", reject)
    response = await onboarding_app.request(
        "POST", f"/stores/{STORE_A}/checkout-policy", payload={
            "expected_version": 0,
            "mode": "manual",
            "terms_version": "qa-v1",
            "terms_text": "Synthetic QA only; no payment or real delivery.",
            "current_password": "incorrect",
            "second_factor": "123456",
        },
    )
    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "invalid_credentials"
