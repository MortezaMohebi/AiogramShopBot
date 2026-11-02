"""Offline campaign tests for consent, platform routing and bounded dispatch."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models.base import Base
from models.shop_content import ShopIdentity
from models.shop_engagement import ShopCampaign, ShopCampaignDelivery
from services.shop_campaigns import CampaignRejected, ShopCampaignService


class AsyncDb:
    """Use a real isolated SQLite database behind an asynchronous interface."""

    def __init__(self, session: Session) -> None:
        """Save the transaction for test assertions."""
        self.session = session

    async def execute(self, statement):
        """Execute a SQLAlchemy query without a network connection."""
        return self.session.execute(statement)

    async def scalar(self, statement):
        """Read one scalar value."""
        return self.session.scalar(statement)

    async def commit(self):
        """Commit one database transaction."""
        self.session.commit()


@pytest.fixture
def db():
    """Create campaign recipient and opt-in records in disposable memory."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ShopIdentity.__table__,
            ShopCampaign.__table__,
            ShopCampaignDelivery.__table__,
        ],
    )
    with Session(engine) as session:
        yield AsyncDb(session)
    engine.dispose()


def add_identity(db, platform, user_id, *, consent=True, banned=False):
    """Provision one platform-scoped and optionally opted-in customer."""
    identity = ShopIdentity(
        platform=platform,
        platform_user_id=user_id,
        is_blocked=banned,
        allow_announcements=consent,
    )
    db.session.add(identity)
    db.session.flush()
    return identity


@pytest.mark.asyncio
async def test_campaign_requires_approval_and_explicit_optin(db):
    """Only opted-in, unblocked customers can be added to the send queue."""
    add_identity(db, "telegram", 101, consent=True)
    add_identity(db, "telegram", 102, consent=False)
    add_identity(db, "bale", 201, consent=True)
    add_identity(db, "bale", 202, banned=True)
    campaign = ShopCampaign(
        title="اطلاعیه", text="متن اطلاعیه قابل مدیریت",
        audience="all", status="draft",
    )
    db.session.add(campaign)
    db.session.commit()

    async def should_not_send(*args):
        """Fail if the send path bypasses approval."""
        raise AssertionError("unapproved campaign was dispatched")

    with pytest.raises(CampaignRejected):
        await ShopCampaignService.dispatch_batch(
            db, campaign_id=campaign.id, send=should_not_send,
        )

    count = await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:1",
    )
    assert count == 2
    queued = db.session.scalars(select(ShopCampaignDelivery)).all()
    assert len(queued) == 2
    recipients = {record.identity_id for record in queued}
    assert recipients == {1, 3}


@pytest.mark.asyncio
async def test_consent_is_rechecked_after_campaign_approval(db):
    """Unsubscribing after approval must prevent message transmission."""
    first = add_identity(db, "telegram", 101)
    second = add_identity(db, "bale", 201)
    campaign = ShopCampaign(
        title="تخفیف", text="محتوای کمپین", audience="all",
        status="draft",
    )
    db.session.add(campaign)
    db.session.commit()
    await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:8",
    )
    second.allow_announcements = False
    db.session.commit()

    delivered = []

    async def fake_send(platform, user_id, body):
        """Record only the intended platform and customer ID."""
        delivered.append((platform.value, user_id, body))

    sent, skipped = await ShopCampaignService.dispatch_batch(
        db, campaign_id=campaign.id, send=fake_send,
    )
    assert (sent, skipped) == (1, 1)
    assert delivered == [("telegram", 101, "محتوای کمپین")]
    assert campaign.status == "completed"


@pytest.mark.asyncio
async def test_ambiguous_delivery_is_not_retried_automatically(db):
    """Mark an unknown send and preserve the single-attempt outbox."""
    add_identity(db, "bale", 201)
    campaign = ShopCampaign(
        title="خبر", text="خبر فروشگاه", audience="bale", status="draft",
    )
    db.session.add(campaign)
    db.session.commit()
    await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:3",
    )
    calls = []

    async def uncertain_send(platform, user_id, text):
        """Simulate an API timeout after a message may have been sent."""
        calls.append(user_id)
        raise TimeoutError("network timeout")

    sent, skipped = await ShopCampaignService.dispatch_batch(
        db, campaign_id=campaign.id, send=uncertain_send,
    )
    assert (sent, skipped) == (0, 0)
    delivery = db.session.scalar(select(ShopCampaignDelivery))
    assert delivery.status == "unknown"

    again, skipped = await ShopCampaignService.dispatch_batch(
        db, campaign_id=campaign.id, send=uncertain_send,
    )
    assert (again, skipped) == (0, 0)
    assert calls == [201]
