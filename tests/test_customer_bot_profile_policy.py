"""Offline CRM, provider-policy and verified linking behavioral tests.

These exercise real SQLAlchemy constraints and application services. They
never call Telegram/Bale, create real orders, or change live webhook state.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models.base import Base
from models.shop_admin_control import AdminEvent
from models.shop_bot_profile import ShopBotProfile
from models.shop_channel_features import ShopChannelFeature
from models.shop_content import ShopIdentity
from models.shop_customer_crm import (
    ShopCustomerAudit,
    ShopCustomerConsentEvent,
    ShopCustomerNote,
    ShopCustomerProfile,
)
from models.shop_customer_links import (
    ShopCustomerIdentityLink,
    ShopCustomerLinkRequest,
)
from models.shop_payment_rail import ShopPaymentRail
from models.shop_staff import ShopStaff
from services import shop_customer_crm as crm
from services import shop_identity_links as linking
from services import shop_payment_rails as rails
from services.shop_bot_profiles import get_bot_options, validate_allowed_updates


@pytest.fixture
def session():
    """Build an isolated relational store with no provider side effects."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        ShopStaff.__table__,
        AdminEvent.__table__,
        ShopIdentity.__table__,
        ShopCustomerProfile.__table__,
        ShopCustomerNote.__table__,
        ShopCustomerConsentEvent.__table__,
        ShopCustomerAudit.__table__,
        ShopCustomerLinkRequest.__table__,
        ShopCustomerIdentityLink.__table__,
        ShopBotProfile.__table__,
        ShopChannelFeature.__table__,
        ShopPaymentRail.__table__,
    ])
    with Session(engine) as db:
        db.add_all([
            ShopStaff(
                id=10, username="operator", password_hash="test-hash",
                role="superadmin", is_active=True, session_version=1,
            ),
            ShopIdentity(
                id=101, platform="telegram", platform_user_id=5001,
                username="sender", first_name="Sender",
                is_blocked=False, allow_announcements=False,
            ),
            ShopIdentity(
                id=102, platform="bale", platform_user_id=6001,
                username="receiver", first_name="Receiver",
                is_blocked=False, allow_announcements=False,
            ),
            ShopIdentity(
                id=103, platform="bale", platform_user_id=7001,
                username="intruder", first_name="Intruder",
                is_blocked=False, allow_announcements=False,
            ),
        ])
        db.commit()
        yield db
    engine.dispose()


class AsyncSessionAdapter:
    """Forward async ORM operations to a synchronous disposable SQLite session."""

    def __init__(self, db: Session):
        """Store a test-only transactional session."""
        self.db = db

    async def get(self, model, key):
        """Read a mapped object using the same SQLAlchemy metadata."""
        return self.db.get(model, key)

    async def scalar(self, statement):
        """Read one ORM scalar."""
        return self.db.scalar(statement)

    async def scalars(self, statement):
        """Read SQLAlchemy scalar results."""
        return self.db.scalars(statement)

    async def commit(self):
        """Commit the current isolated transaction."""
        self.db.commit()

    def add(self, item):
        """Attach a mapped record."""
        self.db.add(item)


def test_customer_notes_and_documented_expiring_restrictions(session):
    """Block state has a reason and expiry; no consent flag is changed."""
    crm.add_note(session, identity_id=101, actor_id=10, content="Follow-up")
    until = datetime(2026, 11, 4, tzinfo=timezone.utc)
    crm.change_restriction(
        session, identity_id=101, actor_id=10,
        blocked=True, reason="Repeated spam complaints",
        until=until, now=datetime(2026, 11, 3, tzinfo=timezone.utc),
    )
    session.commit()
    profile = session.get(ShopCustomerProfile, 101)
    assert profile.restriction_reason == "Repeated spam complaints"
    assert session.get(ShopIdentity, 101).allow_announcements is False
    assert len(session.query(ShopCustomerNote).all()) == 1
    assert crm.effective_restriction(
        True, until, now=datetime(2026, 11, 3, tzinfo=timezone.utc),
    )
    assert not crm.effective_restriction(
        True, until, now=datetime(2026, 11, 5, tzinfo=timezone.utc),
    )


def test_staff_cannot_fabricate_marketing_consent(session):
    """CRM edits may assign labels but never toggle the customer opt-in."""
    crm.update_profile(
        session, identity_id=101, actor_id=10,
        tags=["VIP", "Dealer", "VIP"], owner_staff_id=10,
        support_status="pending",
    )
    session.commit()
    profile = session.get(ShopCustomerProfile, 101)
    assert crm.tags_from_json(profile.tags_json) == ["VIP", "Dealer"]
    assert session.get(ShopIdentity, 101).allow_announcements is False
    assert session.query(ShopCustomerConsentEvent).count() == 0
    assert session.query(ShopCustomerAudit).count() == 1


def test_three_step_link_requires_source_confirmation(session):
    """A claim alone never links two users or their financial histories."""
    adapter = AsyncSessionAdapter(session)
    token = asyncio.run(linking.begin(
        adapter, platform="telegram", user_id=5001,
    ))
    assert len(token) == 43
    assert token not in session.query(ShopCustomerLinkRequest).first().token_hash

    with pytest.raises(linking.LinkRejected):
        asyncio.run(linking.claim(
            adapter, platform="telegram", user_id=5001, token=token,
        ))
    asyncio.run(linking.claim(
        adapter, platform="bale", user_id=6001, token=token,
    ))
    assert session.query(ShopCustomerIdentityLink).count() == 0

    with pytest.raises(linking.LinkRejected):
        asyncio.run(linking.approve(
            adapter, platform="bale", user_id=6001, token=token,
        ))
    asyncio.run(linking.approve(
        adapter, platform="telegram", user_id=5001, token=token,
    ))
    assert session.query(ShopCustomerIdentityLink).count() == 1
    with pytest.raises(linking.LinkRejected):
        asyncio.run(linking.approve(
            adapter, platform="telegram", user_id=5001, token=token,
        ))


def test_payment_methods_are_provider_scoped_and_default_compatible(session):
    """Bale wallet toggles do not alter Telegram payments or old balances."""
    adapter = AsyncSessionAdapter(session)
    assert asyncio.run(rails.rail_enabled(adapter, "telegram", "telegram_stars"))
    assert not asyncio.run(rails.rail_enabled(adapter, "bale", "telegram_stars"))
    session.add(ShopPaymentRail(
        platform="bale", rail_type="bale_wallet",
        display_name="کیف پول بله", enabled=False,
    ))
    session.commit()
    assert not asyncio.run(rails.rail_enabled(adapter, "bale", "bale_wallet"))
    assert asyncio.run(rails.rail_enabled(adapter, "telegram", "store_credit"))


def test_bot_profile_persisted_maintenance_and_allowed_updates(session):
    """Never store provider tokens; options are effective per provider."""
    adapter = AsyncSessionAdapter(session)
    session.add(ShopBotProfile(
        platform="bale", maintenance_enabled=True,
        display_name="Store Bale",
        environment="codespaces",
        poll_timeout_seconds=9,
        request_timeout_seconds=20,
        allowed_updates_json='["message","callback_query"]',
    ))
    session.commit()
    profile = asyncio.run(get_bot_options(adapter, "bale"))
    assert profile.maintenance_enabled is True
    assert profile.poll_timeout_seconds == 9
    assert profile.allowed_updates == ("callback_query", "message")
    assert "TOKEN" not in str(profile)
    with pytest.raises(ValueError):
        validate_allowed_updates(["message", "message"])
