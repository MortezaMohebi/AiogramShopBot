"""Offline campaign media preflight before approval and durable queueing.

Direct dispatch no longer exists. Worker delivery, rate limits and retries are
tested separately in tests/test_durable_broadcast_worker_offline.py.
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
    """Adapt an isolated SQLite session for the async campaign controller."""

    def __init__(self, session: Session) -> None:
        """Keep a single disposable transaction."""
        self.session = session

    async def execute(self, statement):
        """Execute a SQL query without a live database."""
        return self.session.execute(statement)

    async def scalar(self, statement):
        """Read one scalar value."""
        return self.session.scalar(statement)

    async def commit(self):
        """Commit the isolated test transaction."""
        self.session.commit()


@pytest.fixture
def shop(tmp_path, monkeypatch):
    """Create two opted-in identities and an original campaign image."""
    monkeypatch.setattr(config, "SHOP_MEDIA_ROOT", str(tmp_path))
    key = "a" * 32 + ".png"
    original = b"\x89PNG\r\n\x1a\n" + b"test-content"
    (tmp_path / key).write_bytes(original)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ShopIdentity.__table__, ShopCampaign.__table__,
            ShopCampaignMedia.__table__, ShopCampaignDelivery.__table__,
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
        ])
        campaign = ShopCampaign(
            title="رسانه", text="محتوای فروشگاه",
            audience="all", status="draft",
        )
        session.add(campaign)
        session.flush()
        session.add(
            ShopCampaignMedia(
                campaign_id=campaign.id,
                storage_key=key,
                original_filename="image.png",
                kind="photo",
                mime_type="image/png",
                size_bytes=len(original),
                caption="توضیح تصویر",
                position=0,
            )
        )
        session.commit()
        yield AsyncDb(session), campaign, tmp_path, key
    engine.dispose()


@pytest.mark.asyncio
async def test_original_media_is_validated_before_outbox_approval(shop):
    """The durable queue may start only with available compatible originals."""
    db, campaign, _, key = shop
    attachments = await ShopCampaignService._attachments(db, campaign)
    assert len(attachments) == 1
    assert attachments[0].storage_key == key
    assert attachments[0].caption == "توضیح تصویر"
    count = await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:3"
    )
    assert count == 2
    assert campaign.status == "approved"
    assert db.session.scalars(
        select(ShopCampaignDelivery.status)
    ).all() == ["queued", "queued"]


@pytest.mark.asyncio
async def test_missing_original_blocks_approval(shop):
    """Do not approve a media campaign if the private asset was deleted."""
    db, campaign, directory, key = shop
    (directory / key).unlink()
    with pytest.raises(CampaignRejected, match="حذف شده"):
        await ShopCampaignService.approve(
            db, campaign_id=campaign.id, approver="staff:3"
        )
    assert campaign.status == "draft"


@pytest.mark.asyncio
async def test_modified_media_size_blocks_approval(shop):
    """A media file changed after dashboard upload needs manual reapproval."""
    db, campaign, directory, key = shop
    with (directory / key).open("ab") as handle:
        handle.write(b"unexpected mutation")
    with pytest.raises(CampaignRejected, match="تغییر"):
        await ShopCampaignService.approve(
            db, campaign_id=campaign.id, approver="staff:3"
        )
    assert campaign.status == "draft"
