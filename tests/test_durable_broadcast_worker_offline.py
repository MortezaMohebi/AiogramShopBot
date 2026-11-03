"""Offline lifecycle checks for continuously draining the campaign outbox.

No live Telegram/Bale API, Docker service or PostgreSQL database is started.
SKIP LOCKED and clock_timestamp() concurrency still require final PostgreSQL QA.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import config
import db
from channels.contracts import BotReply, Platform
from models.base import Base
from models.shop_content import ShopIdentity
from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import (
    DEFAULT_STORE_ID, LEGACY_BOT_IDS, ShopBot, ShopStore,
)
from models.shop_staff import ShopStaff
from models.shop_engagement import (
    ShopBroadcastRateSlot, ShopBroadcastWorkerHeartbeat,
    ShopCampaign, ShopCampaignAudit, ShopCampaignDelivery, ShopCampaignMedia,
)
from services.shop_broadcast_control import (
    BroadcastControl, delivery_counts,
)
from services.shop_broadcast_rate import channel_rate, slot_intervals
from services.shop_broadcast_worker import BroadcastWorker
from services.shop_campaigns import CampaignRejected, ShopCampaignService


class AsyncSQLite:
    """Adapt a disposable synchronous SQLite session for async core methods."""

    def __init__(self, session: Session) -> None:
        """Save the isolated SQLAlchemy session."""
        self.session = session

    async def scalar(self, statement):
        """Evaluate an ORM scalar query."""
        return self.session.scalar(statement)

    async def execute(self, statement):
        """Evaluate a database query."""
        return self.session.execute(statement)

    async def get(self, model, key):
        """Load a row by its primary key."""
        return self.session.get(model, key)

    async def flush(self):
        """Flush the pending transaction."""
        self.session.flush()

    async def commit(self):
        """Commit a bounded change to the durable test store."""
        self.session.commit()

    async def rollback(self):
        """Roll back an intentionally rejected action."""
        self.session.rollback()

    def add(self, record):
        """Stage one record."""
        self.session.add(record)


class RecordingTelegram:
    """Fake outbound transport with a valid Telegram bot token."""

    def __init__(self, session: AsyncSQLite) -> None:
        """Store calls and allow a test hook to pause the campaign."""
        self.bot = type(
            "FakeBot", (), {"token": "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAA"}
        )()
        self.sent: list[int] = []
        self.session = session
        self.pause_campaign: int | None = None
        self.fail_for: int | None = None

    async def send(self, chat_id: int, reply: BotReply) -> None:
        """Simulate a Telegram text send with no external network."""
        self.sent.append(chat_id)
        if self.fail_for == chat_id:
            raise TimeoutError("Uncertain Bot API result")
        if self.pause_campaign is not None:
            await BroadcastControl.change(
                self.session, campaign_id=self.pause_campaign,
                actor="staff:1", action="pause",
            )
            self.pause_campaign = None

    async def send_media(self, chat_id: int, attachment) -> None:
        """Record a media send as another non-network Telegram message."""
        self.sent.append(chat_id)


@pytest.fixture
def context(monkeypatch):
    """Build a self-contained marketing database and disable real rate waits."""
    monkeypatch.setattr(config, "SHOP_CAMPAIGN_DISPATCH_ENABLED", True)
    monkeypatch.setattr(config, "SHOP_BROADCAST_WORKER_ENABLED", True)
    monkeypatch.setattr(
        config, "TOKEN", "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    )
    monkeypatch.setattr(config, "BALE_BOT_TOKEN", None)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [
        ShopStaff.__table__, ShopStore.__table__, ShopBot.__table__,
        ShopBotOperations.__table__,
        ShopIdentity.__table__, ShopCampaign.__table__,
        ShopCampaignDelivery.__table__, ShopCampaignMedia.__table__,
        ShopCampaignAudit.__table__,
        ShopBroadcastRateSlot.__table__,
        ShopBroadcastWorkerHeartbeat.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine, expire_on_commit=False) as session:
        session.add(ShopStore(
            id=DEFAULT_STORE_ID, slug="default",
            name="Existing shop", state="active",
        ))
        session.add_all([
            ShopBot(
                id=bot_id, store_id=DEFAULT_STORE_ID,
                slug=f"legacy-{platform}", name=f"Legacy {platform}",
                platform=platform, status="legacy", runtime_owner="legacy",
                version=1, credential_version=1,
            ) for platform, bot_id in LEGACY_BOT_IDS.items()
        ])
        session.add_all([
            ShopBotOperations(
                bot_id=bot_id, desired_state="active",
                environment="staging",
            ) for bot_id in LEGACY_BOT_IDS.values()
        ])
        session.commit()
        adapter = AsyncSQLite(session)

        class SessionContext:
            """Enter an async-compatible disposable session context."""

            async def __aenter__(self):
                """Expose the same transaction for the whole test."""
                return adapter

            async def __aexit__(self, *_args):
                """Let explicit service commit/rollback control the session."""
                return False

        monkeypatch.setattr(db, "session_maker", SessionContext)

        async def no_network_wait(**_kwargs):
            """Replace the PostgreSQL rate reservation with a deterministic stub."""
            return None

        monkeypatch.setattr(
            "services.shop_broadcast_worker.reserve_message_slot",
            no_network_wait,
        )
        yield adapter
    engine.dispose()


def make_campaign(db_session: AsyncSQLite, total: int) -> ShopCampaign:
    """Build a campaign containing any number of opted-in Telegram users."""
    if total < 1:
        raise ValueError("At least one recipient is required.")
    for user_id in range(1, total + 1):
        db_session.session.add(
            ShopIdentity(
                platform="telegram", platform_user_id=user_id,
                is_blocked=False, allow_announcements=True,
            )
        )
    campaign = ShopCampaign(
        title="فروشگاه", text="اطلاعیه", audience="telegram",
        status="draft",
    )
    db_session.session.add(campaign)
    db_session.session.commit()
    return campaign


@pytest.mark.asyncio
async def test_worker_continues_past_ten_recipients_without_manager_clicks(context):
    """A single start drains the whole outbox, not just one ten-user batch."""
    campaign = make_campaign(context, total=27)
    count = await ShopCampaignService.approve(
        context, campaign_id=campaign.id, approver="staff:1"
    )
    assert count == 27
    await BroadcastControl.start(
        context, campaign_id=campaign.id,
        actor="staff:1", bale_mode="standard",
    )
    transport = RecordingTelegram(context)
    worker = BroadcastWorker(telegram=transport, bale_session=None)
    for _ in range(27):
        assert await worker.process_next() is True
    await worker.finalize_campaigns()
    assert await worker.process_next() is False
    assert campaign.status == "completed"
    assert len(transport.sent) == 27
    assert set(transport.sent) == set(range(1, 28))
    assert (await delivery_counts(context, campaign.id))["sent"] == 27


@pytest.mark.asyncio
async def test_pause_resume_and_cancel_are_durable(context):
    """A pause stops further recipients; resume never repeats completed ones."""
    campaign = make_campaign(context, total=4)
    await ShopCampaignService.approve(
        context, campaign_id=campaign.id, approver="staff:2"
    )
    await BroadcastControl.start(
        context, campaign_id=campaign.id, actor="staff:2"
    )
    transport = RecordingTelegram(context)
    worker = BroadcastWorker(telegram=transport, bale_session=None)
    transport.pause_campaign = campaign.id
    assert await worker.process_next() is True
    assert campaign.status == "paused"
    assert await worker.process_next() is False
    assert transport.sent == [1]

    await BroadcastControl.change(
        context, campaign_id=campaign.id,
        actor="staff:2", action="resume",
    )
    assert await worker.process_next() is True
    await BroadcastControl.change(
        context, campaign_id=campaign.id,
        actor="staff:2", action="cancel",
    )
    assert await worker.process_next() is False
    states = await delivery_counts(context, campaign.id)
    assert states.get("sent") == 2
    assert states.get("skipped") == 2
    assert campaign.status == "cancelled"
    assert transport.sent == [1, 2]


@pytest.mark.asyncio
async def test_timeout_pauses_and_never_retries_the_uncertain_recipient(context):
    """Ambiguous delivery is quarantined; only later queued users may continue."""
    campaign = make_campaign(context, total=3)
    await ShopCampaignService.approve(
        context, campaign_id=campaign.id, approver="staff:1"
    )
    await BroadcastControl.start(
        context, campaign_id=campaign.id, actor="staff:1"
    )
    transport = RecordingTelegram(context)
    transport.fail_for = 1
    worker = BroadcastWorker(telegram=transport, bale_session=None)
    assert await worker.process_next() is True
    assert campaign.status == "paused"
    states = await delivery_counts(context, campaign.id)
    assert states.get("unknown") == 1
    assert states.get("queued") == 2

    # The old worker's ID is not used to retry a possibly delivered update.
    newer_worker = BroadcastWorker(telegram=transport, bale_session=None)
    assert await newer_worker.process_next() is False
    first = context.session.scalars(
        select(ShopCampaignDelivery)
        .where(ShopCampaignDelivery.status == "unknown")
    ).one()
    await BroadcastControl.reconcile(
        context,
        campaign_id=campaign.id, delivery_id=first.id,
        actor="staff:1", resolution="skipped",
        evidence="Checked provider evidence: not delivered",
    )
    await BroadcastControl.change(
        context, campaign_id=campaign.id,
        actor="staff:1", action="resume",
    )
    for _ in range(2):
        assert await newer_worker.process_next() is True
    await newer_worker.finalize_campaigns()
    assert campaign.status == "completed"
    assert transport.sent == [1, 2, 3]


@pytest.mark.asyncio
async def test_stale_claim_becomes_unknown_not_queued(context):
    """Worker restart cannot silently send an old in-flight message twice."""
    campaign = make_campaign(context, total=2)
    await ShopCampaignService.approve(
        context, campaign_id=campaign.id, approver="staff:1"
    )
    await BroadcastControl.start(
        context, campaign_id=campaign.id, actor="staff:1"
    )
    first = context.session.scalar(
        select(ShopCampaignDelivery).order_by(ShopCampaignDelivery.id)
    )
    first.status = "sending"
    first.claimed_at = datetime.now(timezone.utc) - timedelta(hours=2)
    context.session.commit()
    assert await BroadcastWorker.quarantine_stale() == 1
    assert first.status == "unknown"
    assert campaign.status == "paused"
    assert (await delivery_counts(context, campaign.id)).get("queued") == 1


def test_rate_config_has_global_and_recipient_spacing(monkeypatch):
    """Reserve no more than the configured global and per-chat rates."""
    monkeypatch.setattr(config, "SHOP_BROADCAST_TELEGRAM_MPS", 5)
    monkeypatch.setattr(config, "SHOP_BROADCAST_BALE_STANDARD_MPS", 1)
    monkeypatch.setattr(config, "SHOP_BROADCAST_BALE_BUSINESS_MPS", 5)
    assert channel_rate(Platform.TELEGRAM, bale_mode="standard") == 5
    assert channel_rate(Platform.BALE, bale_mode="standard") == 1
    assert channel_rate(Platform.BALE, bale_mode="business") == 5
    global_gap, chat_gap = slot_intervals(5)
    assert global_gap == timedelta(milliseconds=200)
    assert chat_gap == timedelta(seconds=1)


@pytest.mark.asyncio
async def test_paid_bale_budget_requires_explicit_worst_case_approval(
    context, monkeypatch
):
    """Business API cannot start with an unbounded or unapproved call budget."""
    monkeypatch.setattr(config, "BALE_BOT_TOKEN", "123456:BBBBBBBBBBBBBBBBBBBBBBBBBBBB")
    monkeypatch.setattr(config, "BALE_BROADCAST_MODE", "business")
    monkeypatch.setattr(config, "BALE_BROADCAST_PAID_ENABLED", True)
    monkeypatch.setattr(config, "SHOP_BROADCAST_MAX_PAID_CALLS", 4)
    customer = ShopIdentity(
        platform="bale", platform_user_id=301,
        is_blocked=False, allow_announcements=True,
    )
    context.session.add(customer)
    campaign = ShopCampaign(
        title="بله", text="اطلاعیه بله", audience="bale", status="draft",
    )
    context.session.add(campaign)
    context.session.commit()
    await ShopCampaignService.approve(
        context, campaign_id=campaign.id, approver="staff:9"
    )
    with pytest.raises(CampaignRejected):
        await BroadcastControl.start(
            context, campaign_id=campaign.id, actor="staff:9",
            bale_mode="business", approved_paid_calls=0,
        )
    assert campaign.status == "approved"
    await BroadcastControl.start(
        context, campaign_id=campaign.id, actor="staff:9",
        bale_mode="business", approved_paid_calls=1,
    )
    assert campaign.max_paid_calls == 1
    assert campaign.paid_calls_reserved == 0


@pytest.mark.asyncio
async def test_opt_out_after_approval_is_rechecked_before_dispatch(context):
    """A recipient may unsubscribe between approval and actual send."""
    campaign = make_campaign(context, total=2)
    await ShopCampaignService.approve(
        context, campaign_id=campaign.id, approver="staff:1"
    )
    await BroadcastControl.start(
        context, campaign_id=campaign.id, actor="staff:1"
    )
    first_identity = context.session.scalar(
        select(ShopIdentity).where(ShopIdentity.platform_user_id == 1)
    )
    first_identity.allow_announcements = False
    context.session.commit()

    recorder = RecordingTelegram(context)
    worker = BroadcastWorker(telegram=recorder, bale_session=None)
    assert await worker.process_next() is True
    assert await worker.process_next() is True
    await worker.finalize_campaigns()
    assert recorder.sent == [2]
    assert (await delivery_counts(context, campaign.id))["skipped"] == 1
    assert campaign.status == "completed"


@pytest.mark.asyncio
async def test_business_api_reserves_exactly_one_paid_call_per_message(
    context, monkeypatch
):
    """An approved cost ceiling cannot be exceeded by replaying a queue row."""
    monkeypatch.setattr(
        config, "BALE_BOT_TOKEN", "123456:BBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    )
    monkeypatch.setattr(config, "BALE_BROADCAST_MODE", "business")
    monkeypatch.setattr(config, "BALE_BROADCAST_PAID_ENABLED", True)
    monkeypatch.setattr(config, "SHOP_BROADCAST_MAX_PAID_CALLS", 1)
    identity = ShopIdentity(
        platform="bale", platform_user_id=904,
        is_blocked=False, allow_announcements=True,
    )
    campaign = ShopCampaign(
        title="خبر", text="یک پیام", audience="bale", status="draft"
    )
    context.session.add_all([identity, campaign])
    context.session.commit()
    await ShopCampaignService.approve(
        context, campaign_id=campaign.id, approver="staff:1"
    )
    await BroadcastControl.start(
        context, campaign_id=campaign.id, actor="staff:1",
        bale_mode="business", approved_paid_calls=1,
    )

    calls = []

    class FakeBale:
        """Replace the paid transport with an offline recording object."""

        def __init__(self, _token, _session, *, business_mode):
            """Record that the paid endpoint has been explicitly selected."""
            assert business_mode is True

        async def send(self, user_id, reply):
            """Record a single simulated billable request."""
            calls.append((user_id, reply.text))

    monkeypatch.setattr(
        "services.shop_broadcast_worker.BaleTransport", FakeBale
    )
    worker = BroadcastWorker(telegram=None, bale_session=object())
    assert await worker.process_next() is True
    await worker.finalize_campaigns()
    assert campaign.status == "completed"
    assert campaign.paid_calls_reserved == 1
    assert campaign.max_paid_calls == 1
    assert calls == [(904, "یک پیام")]
    assert await worker.process_next() is False
    assert campaign.paid_calls_reserved == 1
