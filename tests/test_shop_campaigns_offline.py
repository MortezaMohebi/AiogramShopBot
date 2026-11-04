"""Offline campaign approval and consent-snapshot regression tests.

Direct manual dispatch has been retired; actual outbound delivery is covered
by tests/test_durable_broadcast_worker_offline.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models.base import Base
from models.shop_content import ShopIdentity
from models.shop_customer_crm import ShopCustomerProfile
from models.shop_engagement import (
    ShopCampaign, ShopCampaignDelivery, ShopCampaignMedia,
)
from services.shop_campaigns import CampaignRejected, ShopCampaignService


class AsyncDb:
    """Run real SQLAlchemy statements against disposable in-memory SQLite."""

    def __init__(self, session: Session) -> None:
        """Keep the isolated transaction."""
        self.session = session

    async def execute(self, statement):
        """Execute a SQLAlchemy query."""
        return self.session.execute(statement)

    async def scalar(self, statement):
        """Return one scalar value."""
        return self.session.scalar(statement)

    async def commit(self):
        """Commit the approval and all recipients."""
        self.session.commit()


@pytest.fixture
def db():
    """Create only independent campaign/identity data."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ShopIdentity.__table__, ShopCampaign.__table__,
            ShopCustomerProfile.__table__,
            ShopCampaignDelivery.__table__, ShopCampaignMedia.__table__,
        ],
    )
    with Session(engine, expire_on_commit=False) as session:
        yield AsyncDb(session)
    engine.dispose()


def identity(db, platform, user_id, *, consent=True, blocked=False):
    """Insert one platform-scoped customer with explicit opt-in."""
    item = ShopIdentity(
        platform=platform, platform_user_id=user_id,
        allow_announcements=consent, is_blocked=blocked,
    )
    db.session.add(item)
    db.session.flush()
    return item


@pytest.mark.asyncio
async def test_approval_only_snapshots_current_opted_in_customers(db):
    """Neither opted-out nor blocked accounts enter the durable outbox."""
    identity(db, "telegram", 101, consent=True)
    identity(db, "telegram", 102, consent=False)
    identity(db, "bale", 201, consent=True)
    identity(db, "bale", 202, blocked=True)
    campaign = ShopCampaign(
        title="اطلاعیه", text="متن فارسی فروشگاه",
        audience="all", status="draft",
    )
    db.session.add(campaign)
    db.session.commit()
    count = await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:1"
    )
    assert count == 2
    assert campaign.status == "approved"
    deliveries = db.session.scalars(select(ShopCampaignDelivery)).all()
    assert len(deliveries) == 2
    recipients = {row.identity_id for row in deliveries}
    assert recipients == {1, 3}

    # Reapproval cannot silently rewrite the recipient snapshot.
    with pytest.raises(CampaignRejected):
        await ShopCampaignService.approve(
            db, campaign_id=campaign.id, approver="staff:1"
        )


@pytest.mark.asyncio
async def test_no_opted_in_recipient_marks_campaign_completed(db):
    """An empty audience cannot be started or broadcast accidentally."""
    identity(db, "bale", 201, consent=False)
    campaign = ShopCampaign(
        title="اطلاعیه", text="متن", audience="bale", status="draft"
    )
    db.session.add(campaign)
    db.session.commit()
    count = await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:1"
    )
    assert count == 0
    assert campaign.status == "completed"
    assert db.session.scalars(select(ShopCampaignDelivery)).all() == []


@pytest.mark.asyncio
async def test_opt_out_after_approval_is_not_overwritten(db):
    """Worker must recheck consent; snapshot must not force re-subscription."""
    person = identity(db, "telegram", 101, consent=True)
    campaign = ShopCampaign(
        title="پیام", text="خبر", audience="telegram", status="draft"
    )
    db.session.add(campaign)
    db.session.commit()
    await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:1"
    )
    person.allow_announcements = False
    db.session.commit()
    assert person.allow_announcements is False
    assert db.session.scalar(
        select(ShopCampaignDelivery.status)
    ) == "queued"
