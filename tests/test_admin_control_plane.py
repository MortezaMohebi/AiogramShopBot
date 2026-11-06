"""Behavioral security tests: real SQLAlchemy rows, no provider requests."""

from tests.schema_support import create_shop_schema
from datetime import datetime, timedelta, timezone
from importlib.util import find_spec
from types import SimpleNamespace
import pytest
from sqlalchemy import Column, Integer, String, Boolean, create_engine, select
from sqlalchemy.orm import Session
from models.base import Base

# The real project already registers ShopStaff; this stand-alone test checkout
# supplies only the pre-existing FK table, never a mock security implementation.
if find_spec('models.shop_staff') is not None:
    from models.shop_staff import ShopStaff
if 'shop_staff' not in Base.metadata.tables:
    from sqlalchemy import Table
    Table('shop_staff', Base.metadata,
          Column('id', Integer, primary_key=True),
          Column('username', String(80)), Column('password_hash', String(255)),
          Column('role', String(20)), Column('is_active', Boolean),
          Column('session_version', Integer))


def security():
    """Fail with a useful feature assertion before implementation exists."""
    assert find_spec('services.shop_admin_security') is not None, 'Server-side sessions are not implemented'
    from services import shop_admin_security
    return shop_admin_security


def test_session_lifecycle_and_isolation():
    sec = security()
    from models.shop_admin_control import AdminSession
    engine = create_engine('sqlite:///:memory:')
    create_shop_schema(engine)
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    user = SimpleNamespace(id=1, session_version=1, is_active=True, role='viewer')
    with Session(engine) as db:
        first = sec.issue_session(db, user, 'Laptop', now=now)
        second = sec.issue_session(db, user, 'Phone', now=now)
        db.commit()
        assert first != second
        assert db.scalar(select(AdminSession.token_hash)) != first
        assert sec.validate_session(db, user, first, now=now).staff_id == 1
        foreign = SimpleNamespace(id=2, session_version=1, is_active=True, role='viewer')
        with pytest.raises(sec.SecurityRejected):
            sec.validate_session(db, foreign, first, now=now)
        row = sec.validate_session(db, user, first, now=now)
        sec.revoke_session(db, user.id, row.id, now=now)
        db.commit()
        with pytest.raises(sec.SecurityRejected):
            sec.validate_session(db, user, first, now=now)
        assert sec.validate_session(db, user, second, now=now).staff_id == 1


def test_idle_absolute_and_version_expiry():
    sec = security()
    engine = create_engine('sqlite:///:memory:')
    create_shop_schema(engine)
    user = SimpleNamespace(id=1, session_version=2, is_active=True, role='sales')
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with Session(engine) as db:
        token = sec.issue_session(db, user, 'Browser', now=now)
        db.commit()
        with pytest.raises(sec.SecurityRejected):
            sec.validate_session(db, user, token, now=now+timedelta(minutes=31))
        user.session_version = 3
        with pytest.raises(sec.SecurityRejected):
            sec.validate_session(db, user, token, now=now)


def test_permissions_are_explicit_and_fail_closed():
    sec = security()
    assert sec.has_permission('viewer', 'account.manage_self')
    assert not sec.has_permission('viewer', 'bots.apply')
    assert not sec.has_permission('finance', 'staff.manage')
    assert sec.has_permission('superadmin', 'bots.apply')
    assert not sec.has_permission('unrecognized', 'account.manage_self')
    assert not sec.has_permission('superadmin', 'unrecognized.permission')


def test_totp_rfc_vector_and_recovery_are_single_use(monkeypatch):
    sec = security()
    import base64
    monkeypatch.setenv('SHOP_SECURITY_ENCRYPTION_KEY', base64.urlsafe_b64encode(b'k'*32).decode())
    # RFC 6238 SHA-1 T=59, 8-digit code 94287082 -> six digits 287082.
    assert sec.totp('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ', 59) == '287082'
    engine = create_engine('sqlite:///:memory:')
    create_shop_schema(engine)
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with Session(engine) as db:
        profile = sec.profile_for(db, 1)
        secret = sec.begin_mfa(db, profile, now=now)
        assert secret not in profile.pending_mfa
        code = sec.totp(secret, now.timestamp())
        recovery = sec.confirm_mfa(db, profile, code, now=now)
        db.commit()
        assert len(recovery) == 8
        with pytest.raises(sec.SecurityRejected):
            sec.verify_second_factor(db, profile, code, now=now)
        sec.verify_second_factor(db, profile, recovery[0], now=now)
        db.commit()
        with pytest.raises(sec.SecurityRejected):
            sec.verify_second_factor(db, profile, recovery[0], now=now)


def test_connection_changes_are_idempotent_and_state_guarded():
    sec = security()
    from models.shop_admin_control import ConnectionChange
    from services.shop_connection_control import stage_change, transition
    engine = create_engine('sqlite:///:memory:')
    create_shop_schema(engine)
    with Session(engine) as db:
        first = stage_change(db, actor_id=1, platform='telegram', current_mode='webhook', requested_mode='polling', key='00000000-0000-4000-8000-000000000001')
        same = stage_change(db, actor_id=1, platform='telegram', current_mode='webhook', requested_mode='polling', key='00000000-0000-4000-8000-000000000001')
        assert first.id == same.id
        assert first.state == 'pending'
        transition(db, first, 'queued', actor_id=1)
        transition(db, first, 'applying', actor_id=1)
        transition(db, first, 'succeeded', actor_id=1)
        db.commit()
        with pytest.raises(sec.SecurityRejected):
            transition(db, first, 'queued', actor_id=1)
        assert db.scalars(select(ConnectionChange)).all() == [first]


def test_revoke_others_preserves_current_session_and_records_event():
    sec = security()
    from models.shop_admin_control import AdminEvent
    engine = create_engine('sqlite:///:memory:')
    create_shop_schema(engine)
    user = SimpleNamespace(id=1, session_version=1, is_active=True, role='content')
    with Session(engine) as db:
        first = sec.issue_session(db, user, 'A')
        second = sec.issue_session(db, user, 'B')
        current = sec.validate_session(db, user, second)
        assert sec.revoke_others(db, user.id, current.id) == 1
        with pytest.raises(sec.SecurityRejected):
            sec.validate_session(db, user, first)
        assert sec.validate_session(db, user, second).id == current.id
        assert 'session.others_revoked' in db.scalars(select(AdminEvent.action)).all()


def test_expiry_is_absolute_even_when_session_has_recent_activity():
    sec = security()
    from models.shop_admin_control import AdminSession
    engine = create_engine('sqlite:///:memory:')
    create_shop_schema(engine)
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    user = SimpleNamespace(id=1, session_version=1, is_active=True, role='viewer')
    with Session(engine) as db:
        token = sec.issue_session(db, user, 'A', now=now)
        row = db.scalar(select(AdminSession))
        row.last_seen_at = now + timedelta(hours=8)
        with pytest.raises(sec.SecurityRejected):
            sec.validate_session(db, user, token, now=now+timedelta(hours=8))


def test_disabled_account_and_foreign_revocation_fail_closed():
    sec = security()
    engine = create_engine('sqlite:///:memory:')
    create_shop_schema(engine)
    user = SimpleNamespace(id=1, session_version=1, is_active=True, role='viewer')
    with Session(engine) as db:
        token = sec.issue_session(db, user, 'A')
        row = sec.validate_session(db, user, token)
        with pytest.raises(sec.SecurityRejected):
            sec.revoke_session(db, 2, row.id)
        user.is_active = False
        with pytest.raises(sec.SecurityRejected):
            sec.validate_session(db, user, token)


def test_recent_authentication_and_device_cap():
    sec = security()
    from models.shop_admin_control import AdminSession
    engine = create_engine('sqlite:///:memory:')
    create_shop_schema(engine)
    user = SimpleNamespace(id=1, session_version=1, is_active=True, role='superadmin')
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with Session(engine) as db:
        tokens = [sec.issue_session(db, user, str(i), now=now+timedelta(seconds=i)) for i in range(11)]
        assert sum(v.revoked_at is None for v in db.scalars(select(AdminSession))) == 10
        with pytest.raises(sec.SecurityRejected):
            sec.validate_session(db, user, tokens[0], now=now+timedelta(seconds=20))
        row = sec.validate_session(db, user, tokens[-1], now=now+timedelta(seconds=20))
        sec.require_recent(row, now=now+timedelta(minutes=1))
        with pytest.raises(sec.SecurityRejected):
            sec.require_recent(row, now=now+timedelta(minutes=6))


def test_profile_validates_timezone_and_preserves_identity():
    sec = security()
    engine = create_engine('sqlite:///:memory:')
    create_shop_schema(engine)
    with Session(engine) as db:
        profile = sec.update_profile(db, 1, '  Operator  ', 'Asia/Tehran')
        assert profile.display_name == 'Operator'
        assert profile.staff_id == 1
        with pytest.raises(sec.SecurityRejected):
            sec.update_profile(db, 1, 'Name', '../../etc/passwd')


def test_mfa_expiry_and_recovery_secrets_are_not_stored(monkeypatch):
    sec = security()
    import base64
    monkeypatch.setenv('SHOP_SECURITY_ENCRYPTION_KEY', base64.urlsafe_b64encode(b'x'*32).decode())
    engine = create_engine('sqlite:///:memory:')
    create_shop_schema(engine)
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with Session(engine) as db:
        profile = sec.profile_for(db, 1)
        secret = sec.begin_mfa(db, profile, now=now)
        with pytest.raises(sec.SecurityRejected):
            sec.confirm_mfa(db, profile, sec.totp(secret, (now+timedelta(minutes=11)).timestamp()), now=now+timedelta(minutes=11))
        recovery = sec.confirm_mfa(db, profile, sec.totp(secret, now.timestamp()), now=now)
        assert all(code not in profile.recovery_hashes for code in recovery)
        assert secret not in profile.mfa_secret
        next_time = now+timedelta(seconds=30)
        sec.verify_second_factor(db, profile, sec.totp(secret, next_time.timestamp()), now=next_time)
        with pytest.raises(sec.SecurityRejected):
            sec.verify_second_factor(db, profile, sec.totp(secret, next_time.timestamp()), now=next_time)


def test_connection_conflicts_cancellation_and_unknown_reconciliation():
    sec = security()
    from services.shop_connection_control import stage_change, transition
    from models.shop_admin_control import ConnectionConfig
    engine = create_engine('sqlite:///:memory:')
    create_shop_schema(engine)
    with Session(engine) as db:
        first = stage_change(db, actor_id=1, platform='bale', current_mode='webhook', requested_mode='polling', key='00000000-0000-4000-8000-000000000002')
        with pytest.raises(sec.SecurityRejected):
            stage_change(db, actor_id=1, platform='bale', current_mode='webhook', requested_mode='webhook', key=first.idempotency_key)
        with pytest.raises(sec.SecurityRejected):
            stage_change(db, actor_id=2, platform='bale', current_mode='webhook', requested_mode='webhook', key='00000000-0000-4000-8000-000000000003')
        transition(db, first, 'queued', actor_id=1)
        transition(db, first, 'applying', actor_id=1)
        transition(db, first, 'needs_review', actor_id=1, error_code='timeout')
        with pytest.raises(sec.SecurityRejected):
            transition(db, first, 'queued', actor_id=1)
        first.verification_only = True
        transition(db, first, 'queued', actor_id=1)
        transition(db, first, 'applying', actor_id=1)
        transition(db, first, 'succeeded', actor_id=1)
        assert db.get(ConnectionConfig, 'bale').mode == 'polling'
        assert db.get(ConnectionConfig, 'bale').version == 2
        second = stage_change(db, actor_id=1, platform='bale', current_mode='polling', requested_mode='webhook', key='00000000-0000-4000-8000-000000000004')
        transition(db, second, 'cancelled', actor_id=1)
        assert db.get(ConnectionConfig, 'bale').mode == 'polling'


def test_additive_bootstrap_preserves_existing_tables():
    from scripts.security_bootstrap import permitted_missing
    expected = {'shop_staff', 'shop_orders', 'shop_admin_sessions'}
    additions = {'shop_admin_sessions'}
    assert permitted_missing(set(), expected, additions) == expected
    assert permitted_missing({'shop_staff', 'shop_orders'}, expected, additions) == additions
    assert permitted_missing(expected, expected, additions) == set()
    with pytest.raises(RuntimeError):
        permitted_missing({'shop_staff'}, expected, additions)
    with pytest.raises(RuntimeError):
        permitted_missing(expected | {'unknown'}, expected, additions)


@pytest.mark.parametrize('digits', ['۰۱۲۳۴۵۶۷۸۹', '٠١٢٣٤٥٦٧٨٩'])
def test_totp_accepts_localized_digits_without_changing_its_step(digits):
    """Persian/Arabic input must use the same verified RFC counter."""
    sec = security()
    secret = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
    instant = datetime.fromtimestamp(59, timezone.utc)
    localized = '287082'.translate(str.maketrans('0123456789', digits))
    assert sec.matching_step(secret, localized, instant) == 1


def test_totp_accepts_copied_groups_but_rejects_unrelated_unicode():
    """Normalize human spacing without accepting arbitrary Unicode digits."""
    sec = security()
    secret = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
    instant = datetime.fromtimestamp(59, timezone.utc)
    assert sec.matching_step(secret, '۲۸۷ ۰۸۲', instant) == 1
    assert sec.matching_step(secret, '२८७०८२', instant) is None
