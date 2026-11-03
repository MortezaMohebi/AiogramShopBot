"""Regression tests for one-time staff security and provider feature switches.

These tests exercise real SQLAlchemy models and production lifecycle functions,
not browser mocks or provider API integrations.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from channels.contracts import InboundEvent, Platform
from models.base import Base
from models.shop_admin_control import AdminEvent, AdminProfile, AdminSession
from models.shop_channel_features import ShopChannelFeature
from models.shop_content import ShopSettings
from models.shop_staff import ShopStaff
from models.shop_staff_security import (
    ShopPasswordPolicy,
    ShopStaffInvitation,
    ShopStaffPasswordReset,
)
from services import shop_admin_security as security
from services import shop_staff_lifecycle as lifecycle
from services.shop_cart import ShopCartFlow
from services.shop_channel_catalog import CatalogFlow
from services.shop_channel_features import get_features
from services.shop_engagement_flow import ShopEngagementFlow

NOW = datetime(2026, 11, 3, tzinfo=timezone.utc)


@pytest.fixture
def db():
    """Create an isolated relational schema for capability lifecycle tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ShopStaff.__table__,
            ShopSettings.__table__,
            AdminProfile.__table__,
            AdminSession.__table__,
            AdminEvent.__table__,
            ShopPasswordPolicy.__table__,
            ShopStaffInvitation.__table__,
            ShopStaffPasswordReset.__table__,
            ShopChannelFeature.__table__,
        ],
    )
    with Session(engine) as session:
        session.add_all([
            ShopStaff(
                id=1, username="shopadmin", password_hash="initial-hash",
                role="superadmin", is_active=True, session_version=1,
            ),
            ShopStaff(
                id=2, username="viewer", password_hash="original-hash",
                role="viewer", is_active=True, session_version=1,
            ),
        ])
        session.commit()
        yield session
    engine.dispose()


def expect_rejected(action, code: str) -> None:
    """Assert that a rejected operation fails with a safe machine code."""
    with pytest.raises(security.SecurityRejected) as raised:
        action()
    assert raised.value.code == code


def test_invitation_accepts_once_and_never_stores_raw_token(db: Session):
    """An invite is single-use and creates its member with the chosen role."""
    invite, token = lifecycle.issue_invitation(
        db, actor_id=1, username="operator", role="finance", now=NOW,
    )
    db.commit()
    assert db.scalar(select(ShopStaff).where(
        ShopStaff.username == "operator",
    )) is None
    assert len(token) == 43
    assert token not in invite.token_hash
    assert token not in str(invite.__dict__)

    lifecycle.prepare_redemption(db, "invite", token, "Test password length14!", now=NOW)
    lifecycle.redeem(
        db, "invite", token, "hashed-password", "Test password length14!", now=NOW,
    )
    db.commit()

    member = db.scalar(select(ShopStaff).where(ShopStaff.username == "operator"))
    assert member is not None
    assert member.role == "finance"
    assert member.password_hash == "hashed-password"
    assert invite.accepted_at is not None
    expect_rejected(
        lambda: lifecycle.redeem(
            db, "invite", token, "another-hash", "Test password length14!", now=NOW,
        ),
        "invalid_link",
    )
    events = db.scalars(select(AdminEvent)).all()
    assert all(token not in event.target for event in events)


def test_cancel_and_expire_invites(db: Session):
    """Cancellation or expiry invalidates a capability without creating users."""
    invite, token = lifecycle.issue_invitation(
        db, actor_id=1, username="cancelled", role="viewer", now=NOW,
    )
    lifecycle.cancel_invitation(db, 1, invite.id, now=NOW)
    db.commit()
    expect_rejected(
        lambda: lifecycle.prepare_redemption(
            db, "invite", token, "Test password length14!", now=NOW,
        ),
        "invalid_link",
    )

    expired, token2 = lifecycle.issue_invitation(
        db, actor_id=1, username="expired", role="viewer", now=NOW,
    )
    assert lifecycle.invitation_status(
        expired, now=NOW + timedelta(hours=49),
    ) == "expired"
    expect_rejected(
        lambda: lifecycle.prepare_redemption(
            db, "invite", token2, "Test password length14!",
            now=NOW + timedelta(hours=49),
        ),
        "invalid_link",
    )


def test_password_reset_rotates_session_and_invalidates_link(db: Session):
    """A staff member chooses a new password and all old sessions become invalid."""
    member = db.get(ShopStaff, 2)
    old_session = security.issue_session(db, member, "Laptop", now=NOW)
    reset, token = lifecycle.issue_reset(db, 1, member.id, now=NOW)
    db.commit()

    lifecycle.prepare_redemption(db, "reset", token, "Unique new password 22", now=NOW)
    lifecycle.redeem(
        db, "reset", token, "replacement-hash", "Unique new password 22", now=NOW,
    )
    db.commit()
    assert reset.used_at is not None
    assert member.password_hash == "replacement-hash"
    assert member.session_version == 2
    expect_rejected(
        lambda: security.validate_session(db, member, old_session, now=NOW),
        "session_expired",
    )
    expect_rejected(
        lambda: lifecycle.redeem(
            db, "reset", token, "replay-hash", "Unique new password 22", now=NOW,
        ),
        "invalid_link",
    )


def test_password_policy_supports_complexity_without_rewriting_existing_hashes(db: Session):
    """All new passwords must meet merchant policy; existing credentials survive."""
    before = db.get(ShopStaff, 2).password_hash
    lifecycle.configure_policy(
        db, 1, min_length=16, require_upper=True, require_lower=True,
        require_digit=True, require_symbol=True,
    )
    expect_rejected(
        lambda: lifecycle.validate_password(db, "lowercase all words longer"),
        "password_policy_failed",
    )
    expect_rejected(
        lambda: lifecycle.validate_password(db, "UppercaseWith99Space "),
        "password_policy_failed",
    )
    lifecycle.validate_password(db, "ValidPolicyPass#19")
    assert db.get(ShopStaff, 2).password_hash == before
    assert db.get(ShopPasswordPolicy, 1).min_length == 16


class _FeatureDb:
    """Minimal async adapter around a real ORM session for read-only flows."""

    def __init__(self, session: Session):
        self.session = session

    async def get(self, model, key):
        """Delegate the mapped ORM get without network activity."""
        return self.session.get(model, key)


def test_cart_and_credit_toggles_are_independent_by_platform(db: Session):
    """Bale may disable shopping while Telegram stays fully functional."""
    db.add(ShopChannelFeature(
        platform="bale", cart_enabled=False,
        store_credit_enabled=False,
        store_credit_label="اعتبار بله",
    ))
    db.commit()
    adapter = _FeatureDb(db)
    bale = asyncio.run(get_features(adapter, "bale"))
    telegram = asyncio.run(get_features(adapter, "telegram"))
    assert not bale.cart_enabled and not bale.store_credit_enabled
    assert telegram.cart_enabled and telegram.store_credit_enabled

    cart = asyncio.run(ShopCartFlow().reply(
        InboundEvent(platform=Platform.BALE, chat_id=5, user_id=5, text="/cart"),
        adapter,
    ))
    assert cart is not None and "غیرفعال" in cart.text
    wallet = asyncio.run(ShopEngagementFlow().reply(
        InboundEvent(platform=Platform.BALE, chat_id=5, user_id=5, text="/wallet"),
        adapter,
    ))
    assert wallet is not None and "غیرفعال" in wallet.text
    home = asyncio.run(CatalogFlow()._home(adapter, "bale"))
    assert all(
        action.callback_data != "shop:cart"
        for row in home.rows for action in row
    )
    telegram_home = asyncio.run(CatalogFlow()._home(adapter, "telegram"))
    assert any(
        action.callback_data == "shop:cart"
        for row in telegram_home.rows for action in row
    )


def test_mfa_is_compulsory_for_finance_and_superadmin():
    """Only the fixed sensitive roles require an enrolled second factor."""
    assert security.MFA_REQUIRED_ROLES == {"finance", "superadmin"}
    assert not (security.MFA_REQUIRED_ROLES & {"viewer", "sales", "content"})
