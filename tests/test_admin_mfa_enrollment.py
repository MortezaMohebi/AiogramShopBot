"""First MFA enrollment reuses only recent, live, session-bound login proof.

Signed HTTP requests exercise real middleware, routes, SQLAlchemy records and
TOTP enrollment. Only Redis throttling is replaced; no provider is contacted.
"""

from __future__ import annotations

import base64
from datetime import timedelta

import pytest
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from dashboard import admin_control_api as api
from dashboard.next_api import database
from models.shop_admin_control import AdminSession
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_account_proof
from tests.test_campaign_admin_store_scope import campaign_app


@pytest.fixture
def enrollment_app(campaign_app, monkeypatch):
    """Use an unenrolled administrator's real, newly issued device session."""
    member = campaign_app.db.get(ShopStaff, 7)
    member.role = "superadmin"
    # The legacy global harness stubs passlib; keep explicit proof on real Argon2.
    hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    member.password_hash = hasher.hash("Synthetic-enrollment-password-123")
    campaign_app.db.commit()
    campaign_app.app.dependency_overrides[database] = (
        campaign_app.legacy.dependency_overrides[database]
    )
    monkeypatch.setenv(
        "SHOP_SECURITY_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(b"e" * 32).decode(),
    )

    async def throttle(*args):
        """Keep Redis outside the isolated HTTP acceptance boundary."""

    monkeypatch.setattr(api, "throttle", throttle)

    def verify(plain, encoded):
        """Verify the disposable credential with the actual Argon2 algorithm."""
        try:
            return hasher.verify(encoded, plain)
        except VerifyMismatchError:
            return False

    monkeypatch.setattr(api, "verify_password", verify)
    return campaign_app


@pytest.mark.asyncio
async def test_fresh_login_starts_and_confirms_mfa_without_repeating_password(
    enrollment_app,
):
    """The login's recent proof can reveal QR; only a valid OTP enables MFA."""
    app = enrollment_app
    response = await app.request("POST", "/account/mfa-setup", payload={})
    assert response.status_code == 200, response.text
    result = response.json()
    profile = security.profile_for(app.db, 7)
    assert result["qr_data_uri"].startswith("data:image/png;base64,")
    assert result["secret"] not in profile.pending_mfa
    assert profile.mfa_secret is None

    code = security.totp(result["secret"], security.clock().timestamp())
    confirmed = await app.request(
        "POST", "/account/mfa-confirm", payload={"code": code},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert len(confirmed.json()["recovery_codes"]) == 8
    assert security.profile_for(app.db, 7).mfa_secret
    assert app.db.get(AdminSession, app.session_id).revoked_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("remembered", [False, True])
async def test_old_proof_cannot_start_mfa_even_in_a_remembered_session(
    enrollment_app, remembered,
):
    """Activity and cookie persistence cannot extend the five-minute proof."""
    app = enrollment_app
    row = app.db.get(AdminSession, app.session_id)
    row.reauthenticated_at = security.clock() - security.REAUTH_LIMIT
    if remembered:
        row.expires_at = security.utc(row.created_at) + security.REMEMBERED_LIMIT
    app.db.commit()
    response = await app.request("POST", "/account/mfa-setup", payload={})
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "reauthentication_required"
    assert security.profile_for(app.db, 7).pending_mfa is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field", [
    "fresh_login", "reauthenticated_at", "session_id", "staff_id",
])
async def test_browser_fields_cannot_claim_recent_login(enrollment_app, field):
    """A strict setup payload never accepts browser assertions of authority."""
    response = await enrollment_app.request(
        "POST", "/account/mfa-setup", payload={field: "forged"},
    )
    assert response.status_code == 422, response.text
    assert security.profile_for(enrollment_app.db, 7).pending_mfa is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "revoked", "version", "expired", "inactive", "idle",
])
async def test_session_is_rechecked_before_revealing_an_enrollment_secret(
    enrollment_app, monkeypatch, change,
):
    """Revocation after middleware validation still prevents setup's write."""
    app = enrollment_app

    async def invalidate(*args):
        """Change disposable authority after middleware, before route staging."""
        row = app.db.get(AdminSession, app.session_id)
        member = app.db.get(ShopStaff, 7)
        now = security.clock()
        if change == "revoked":
            row.revoked_at = now
        elif change == "version":
            member.session_version += 1
        elif change == "expired":
            row.expires_at = now - timedelta(seconds=1)
        elif change == "inactive":
            member.is_active = False
        else:
            row.last_seen_at = now - security.IDLE_LIMIT
        app.db.commit()

    monkeypatch.setattr(api, "throttle", invalidate)
    response = await app.request("POST", "/account/mfa-setup", payload={})
    assert response.status_code == 401, response.text
    assert security.profile_for(app.db, 7).pending_mfa is None


@pytest.mark.asyncio
async def test_existing_mfa_cannot_be_replaced_using_recent_login(enrollment_app):
    """The setup shortcut cannot rotate an already confirmed authenticator."""
    app = enrollment_app
    profile = security.profile_for(app.db, 7)
    now = security.clock()
    secret = security.begin_mfa(app.db, profile, now=now)
    security.confirm_mfa(
        app.db, profile, security.totp(secret, now.timestamp()), now=now,
    )
    app.db.commit()
    original = profile.mfa_secret
    response = await app.request("POST", "/account/mfa-setup", payload={})
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "mfa_already_enabled"
    assert security.profile_for(app.db, 7).mfa_secret == original


@pytest.mark.asyncio
@pytest.mark.parametrize("correct", [True, False])
async def test_older_client_explicit_password_contract_is_preserved(
    enrollment_app, correct,
):
    """A rolling upgrade accepts real explicit proof, never an incorrect one."""
    app = enrollment_app
    row = app.db.get(AdminSession, app.session_id)
    row.reauthenticated_at = security.clock() - security.REAUTH_LIMIT
    app.db.commit()
    response = await app.request("POST", "/account/mfa-setup", payload={
        "current_password": (
            "Synthetic-enrollment-password-123" if correct else "incorrect"
        ),
    })
    assert response.status_code == (200 if correct else 401), response.text
    assert bool(security.profile_for(app.db, 7).pending_mfa) is correct


@pytest.mark.asyncio
async def test_account_wizard_proof_checks_password_and_is_action_scoped(enrollment_app):
    """The browser proof works with a password and cannot authorize another operation."""
    app = enrollment_app
    profile = security.profile_for(app.db, 7)
    now = security.clock()
    secret = security.begin_mfa(app.db, profile, now=now)
    security.confirm_mfa(app.db, profile, security.totp(secret, now.timestamp()), now=now)
    row = app.db.get(AdminSession, app.session_id)
    row.reauthenticated_at = now - security.REAUTH_LIMIT
    app.db.commit()
    payload = {"action": "reauthenticate", "current_password": "incorrect"}
    denied = await app.request("POST", "/account/verify-password", payload=payload)
    assert denied.status_code == 401
    verified = await app.request("POST", "/account/verify-password", payload={
        **payload, "current_password": "Synthetic-enrollment-password-123",
    })
    assert verified.status_code == 200, verified.text
    proof = {"proof_token": verified.json()["proof_token"]}
    other_action = await app.request("POST", "/account/username", payload={
        **proof, "username": "another-name",
    })
    assert other_action.status_code == 403
    password_only = await app.request("POST", "/account/reauthenticate", payload=proof)
    assert password_only.status_code == 422, password_only.text
    change = {"enabled": True, "expected_version": 0}
    denied = await app.request("POST", "/services/receivers", payload=change)
    assert denied.status_code == 403 and denied.json()["detail"] == "reauthentication_required"
    denied = await app.request("POST", "/account/reauthenticate", payload={
        "current_password": "incorrect",
    })
    assert denied.status_code == 401
    confirmed = await app.request("POST", "/account/reauthenticate", payload={
        "current_password": "Synthetic-enrollment-password-123",
    })
    assert confirmed.status_code == 200, confirmed.text
    for key in ("receivers", "workflow-runtime"):
        changed = await app.request("POST", f"/services/{key}", payload=change)
        assert changed.status_code == 200, changed.text


def test_account_wizard_proof_expires_and_cannot_move_to_another_session():
    """A proof cannot be reused after session rotation or outside its TTL."""
    secret = "synthetic-bridge-secret-for-account-proof-tests"
    issued = 1_800_000_000
    proof = shop_account_proof.issue(secret, "session-a", 2, "password", now=issued)
    assert shop_account_proof.valid(secret, proof, "session-a", 2, "password", now=issued)
    assert not shop_account_proof.valid(secret, proof, "session-b", 2, "password", now=issued)
    assert not shop_account_proof.valid(secret, proof, "session-a", 3, "password", now=issued)
    assert not shop_account_proof.valid(
        secret, proof, "session-a", 2, "password",
        now=issued + shop_account_proof.PROOF_LIFETIME,
    )


@pytest.mark.asyncio
async def test_unenrolled_admin_can_verify_only_for_enrollment(enrollment_app):
    """A setup-only session can open the authenticator wizard, not step up."""
    app = enrollment_app
    password = "Synthetic-enrollment-password-123"
    for action, status in [("reauthenticate", 428), ("mfa-setup", 200)]:
        verified = await app.request("POST", "/account/verify-password", payload={
            "action": action, "current_password": password,
        })
        assert verified.status_code == status, verified.text
    staged = await app.request("POST", "/account/mfa-setup", payload={
        "proof_token": verified.json()["proof_token"],
    })
    assert staged.status_code == 200, staged.text
    assert staged.json()["qr_data_uri"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["mfa-disable", "password", "username"])
async def test_other_sensitive_actions_still_require_password(enrollment_app, action):
    """Removing duplicate proof at setup does not alter other action contracts."""
    profile = security.profile_for(enrollment_app.db, 7)
    now = security.clock()
    secret = security.begin_mfa(enrollment_app.db, profile, now=now)
    security.confirm_mfa(
        enrollment_app.db, profile,
        security.totp(secret, now.timestamp()), now=now,
    )
    enrollment_app.db.commit()
    response = await enrollment_app.request(
        "POST", "/account/" + action, payload={},
    )
    assert response.status_code == 422, response.text
    assert any(error["loc"][-1] == "current_password"
               for error in response.json()["detail"])
