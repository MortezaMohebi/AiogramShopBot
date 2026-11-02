"""Offline media Broadcast behavior on both Telegram and Bale.

All sends are fake callbacks. No network traffic, live users or campaigns.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import config
from models.base import Base
from models.shop_content import ShopIdentity
from models.shop_engagement import (
    ShopCampaign, ShopCampaignDelivery, ShopCampaignMedia,
)
from services.shop_campaigns import CampaignRejected, ShopCampaignService


class AsyncDb:
    """Wrap one disposable SQLite transaction in async-compatible methods."""

    def __init__(self, session: Session) -> None:
        """Remember the test-scoped database session."""
        self.session = session

    async def execute(self, statement):
        """Execute a SQLAlchemy query."""
        return self.session.execute(statement)

    async def scalar(self, statement):
        """Load one SQLAlchemy scalar."""
        return self.session.scalar(statement)

    async def commit(self):
        """Commit the test transaction."""
        self.session.commit()


@pytest.fixture
def shop(tmp_path, monkeypatch):
    """Seed opted-in recipients and an original media file."""
    monkeypatch.setattr(config, "SHOP_MEDIA_ROOT", str(tmp_path))
    key = "a" * 32 + ".png"
    original = b"\x89PNG\r\n\x1a\n" + b"test-content"
    (tmp_path / key).write_bytes(original)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ShopIdentity.__table__, ShopCampaign.__table__,
            ShopCampaignMedia.__table__,
            ShopCampaignDelivery.__table__,
        ],
    )
    with Session(engine, expire_on_commit=False) as session:
        session.add_all([
            ShopIdentity(
                platform="telegram", platform_user_id=101,
                allow_announcements=True, is_blocked=False,
            ),
            ShopIdentity(
                platform="bale", platform_user_id=202,
                allow_announcements=True, is_blocked=False,
            ),
            ShopIdentity(
                platform="bale", platform_user_id=303,
                allow_announcements=False, is_blocked=False,
            ),
        ])
        campaign = ShopCampaign(
            title="کمپین رسانه‌دار",
            text="اطلاعیه فروشگاه",
            audience="all",
            status="draft",
        )
        session.add(campaign)
        session.flush()
        session.add(ShopCampaignMedia(
            campaign_id=campaign.id,
            storage_key=key,
            original_filename="image.png",
            kind="photo",
            mime_type="image/png",
            size_bytes=len(original),
            caption="تصویر اصلی",
            position=0,
        ))
        session.commit()
        yield AsyncDb(session), campaign
    engine.dispose()


@pytest.mark.asyncio
async def test_broadcast_reaches_only_opted_in_customers_with_media(shop):
    """Send the same original file through separate platform adapters."""
    db, campaign = shop
    count = await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:3"
    )
    assert count == 2
    events = []

    async def send_text(platform, user_id, text):
        """Capture merchant message without contacting a Bot API."""
        events.append((platform.value, user_id, "text", text))

    async def send_attachment(platform, user_id, attachment):
        """Capture one correctly typed private attachment."""
        events.append(
            (platform.value, user_id, attachment.kind, attachment.storage_key)
        )

    async def preflight(attachments):
        """Verify media is known before any user is contacted."""
        assert len(attachments) == 1
        assert attachments[0].caption == "تصویر اصلی"

    sent, skipped = await ShopCampaignService.dispatch_batch(
        db,
        campaign_id=campaign.id,
        send=send_text,
        send_attachment=send_attachment,
        media_preflight=preflight,
    )
    assert (sent, skipped) == (2, 0)
    assert {
        (event[0], event[1]) for event in events
    } == {("telegram", 101), ("bale", 202)}
    assert len(events) == 4
    deliveries = db.session.scalars(select(ShopCampaignDelivery)).all()
    assert all(row.status == "sent" for row in deliveries)


@pytest.mark.asyncio
async def test_paid_business_preflight_fails_before_any_message(shop):
    """A missing file_id must prevent expensive unknown-mode broadcast sends."""
    db, campaign = shop
    await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:3"
    )
    sent = []

    async def send_text(platform, user_id, text):
        """Record unexpected messages."""
        sent.append(user_id)

    async def send_attachment(platform, user_id, attachment):
        """Record unexpected media."""
        sent.append(user_id)

    async def preflight(attachments):
        """Emulate a paid Bale file lacking a preuploaded per-bot file ID."""
        raise CampaignRejected("فایل Business API آماده نیست.")

    with pytest.raises(CampaignRejected):
        await ShopCampaignService.dispatch_batch(
            db,
            campaign_id=campaign.id,
            send=send_text,
            send_attachment=send_attachment,
            media_preflight=preflight,
        )
    assert not sent
    assert all(
        row.status == "queued"
        for row in db.session.scalars(select(ShopCampaignDelivery)).all()
    )


@pytest.mark.asyncio
async def test_partial_broadcast_media_failure_is_never_blindly_replayed(shop):
    """A send timeout leaves an explicit unknown receipt requiring review."""
    db, campaign = shop
    await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:3"
    )
    attempts = []

    async def send_text(platform, user_id, text):
        """Record a successful text delivery before a media timeout."""
        attempts.append(("text", user_id))

    async def send_attachment(platform, user_id, attachment):
        """Simulate ambiguous Bot API media delivery."""
        attempts.append(("media", user_id))
        raise TimeoutError("network is unavailable")

    sent, _ = await ShopCampaignService.dispatch_batch(
        db,
        campaign_id=campaign.id,
        send=send_text,
        send_attachment=send_attachment,
    )
    assert sent == 0
    assert all(
        row.status == "unknown"
        for row in db.session.scalars(select(ShopCampaignDelivery)).all()
    )
    calls = list(attempts)
    again, _ = await ShopCampaignService.dispatch_batch(
        db,
        campaign_id=campaign.id,
        send=send_text,
        send_attachment=send_attachment,
    )
    assert again == 0
    assert attempts == calls
