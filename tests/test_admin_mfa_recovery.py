"""Owner-terminal MFA recovery must preserve password proof and revoke sessions."""
from datetime import datetime, timezone
import base64

import pytest
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models.shop_staff import ShopStaff
from models.shop_admin_control import AdminSession
from scripts.manage_shop_staff import recover_admin_mfa
from services import shop_admin_security as security
from tests.schema_support import create_shop_schema
from scripts import manage_shop_staff


@pytest.fixture
def account(monkeypatch):
    """Create a synthetic administrator with an enrolled authenticator."""
    monkeypatch.setenv('SHOP_SECURITY_ENCRYPTION_KEY', base64.urlsafe_b64encode(b'x' * 32).decode())
    # The repository-wide legacy harness replaces passlib with a placeholder.
    # Keep this security regression on a real Argon2 proof instead.
    hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)

    def verify(plain, encoded):
        """Verify only the synthetic Argon2 credential used in this fixture."""
        try:
            return hasher.verify(encoded, plain)
        except VerifyMismatchError:
            return False

    monkeypatch.setattr(manage_shop_staff, 'verify_password', verify)
    engine = create_engine('sqlite:///:memory:')
    create_shop_schema(engine)
    with Session(engine) as db:
        user = ShopStaff(username='shopadmin', password_hash=hasher.hash('Synthetic-only-password-123'), role='superadmin', is_active=True, session_version=3)
        db.add(user)
        db.flush()
        profile = security.profile_for(db, user.id)
        now = datetime.now(timezone.utc)
        secret = security.begin_mfa(db, profile, now=now)
        security.confirm_mfa(db, profile, security.totp(secret, now.timestamp()), now=now)
        security.issue_session(db, user, 'Synthetic browser', now=now)
        db.commit()
        yield db, user, profile
    engine.dispose()


def test_owner_recovery_clears_enrollment_and_revokes_every_session(account):
    """A proven terminal recovery requires fresh enrollment on next login."""
    db, user, profile = account
    recover_admin_mfa(db, 'shopadmin', 'Synthetic-only-password-123')
    db.commit()
    assert profile.mfa_secret is None
    assert profile.pending_mfa is None
    assert profile.recovery_hashes == '[]'
    assert user.session_version == 4
    assert user.is_active and user.role == 'superadmin'
    assert 'superadmin' in security.MFA_REQUIRED_ROLES
    assert all(row.revoked_at is not None for row in db.scalars(select(AdminSession)))


def test_wrong_password_cannot_clear_mfa_or_revoke_sessions(account):
    """Knowledge of an account name is insufficient for owner recovery."""
    db, user, profile = account
    with pytest.raises(ValueError, match='current password'):
        recover_admin_mfa(db, 'shopadmin', 'wrong')
    assert profile.mfa_secret
    assert user.session_version == 3
    assert all(row.revoked_at is None for row in db.scalars(select(AdminSession)))


def test_non_admin_account_is_not_eligible_for_admin_recovery(account):
    """The recovery command never changes permissions or bypasses roles."""
    db, user, profile = account
    user.role = 'viewer'
    db.commit()
    with pytest.raises(ValueError, match='administrator'):
        recover_admin_mfa(db, 'shopadmin', 'Synthetic-only-password-123')
    assert profile.mfa_secret
    assert user.role == 'viewer' and user.session_version == 3
