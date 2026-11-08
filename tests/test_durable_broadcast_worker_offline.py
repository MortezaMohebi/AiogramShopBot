"""Offline lifecycle checks for continuously draining the campaign outbox.

No live Telegram/Bale API, Docker service or PostgreSQL database is started.
SKIP LOCKED and clock_timestamp() concurrency still require final PostgreSQL QA.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import config
import db
from channels.contracts import BotReply, Platform
from models.shop_content import ShopIdentity
from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import (
    DEFAULT_STORE_ID, ShopBot, ShopBotCredential,
)
from models.shop_multibot_receiver import ShopBotReceiver
from models.shop_engagement import ShopCampaign, ShopCampaignDelivery
from services.shop_broadcast_control import (
    BroadcastControl, delivery_counts,
)
from services.shop_broadcast_rate import channel_rate, slot_intervals
from services.shop_broadcast_worker import BroadcastWorker, CampaignTransport
from services.shop_campaigns import CampaignRejected, ShopCampaignService
from tests.schema_support import TEST_BOT_IDS, create_shop_schema, seed_registry

TEST_TOKENS = {
    "telegram": "200001:" + "A" * 32,
    "bale": "200002:" + "B" * 32,
}


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

    async def run_sync(self, operation):
        """Resolve an encrypted credential on the same isolated connection."""
        return operation(self.session)

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


class RecordingTransport:
    """Record a registered bot transport without opening provider clients."""

    def __init__(
        self, session: AsyncSQLite, *, platform: str = "telegram",
        bale_mode: str = "standard",
    ) -> None:
        """Store calls and allow a test hook to pause the campaign."""
        self.bot_id = TEST_BOT_IDS[platform]
        self.platform = Platform(platform)
        self.bale_mode = bale_mode
        self.messages: list[tuple[int, str]] = []
        self.sent: list[int] = []
        self.session = session
        self.pause_campaign: int | None = None
        self.fail_for: int | None = None

    async def send(self, chat_id: int, reply: BotReply) -> None:
        """Record one scoped provider request without external network."""
        self.sent.append(chat_id)
        self.messages.append((chat_id, reply.text))
        if self.fail_for == chat_id:
            raise TimeoutError("Uncertain Bot API result")
        if self.pause_campaign is not None:
            await BroadcastControl.change(
                self.session, campaign_id=self.pause_campaign,
                actor="staff:1", action="pause",
            )
            self.pause_campaign = None

    async def send_media(self, chat_id: int, attachment) -> None:
        """Record one scoped media request without external network."""
        self.sent.append(chat_id)


def transport_factory(transport: RecordingTransport):
    """Supply only the exact registered bot selected by the durable claim."""

    @asynccontextmanager
    async def factory(claim):
        """Assert claim ownership before returning the fake provider."""
        assert claim.bot_id == transport.bot_id
        assert claim.platform == transport.platform
        assert claim.credential_version == 1
        assert claim.bale_mode == transport.bale_mode
        yield CampaignTransport(
            bot_id=claim.bot_id,
            platform=claim.platform,
            credential_version=claim.credential_version,
            token=TEST_TOKENS[claim.platform.value],
            transport=transport,
        )

    return factory


@pytest.fixture
def context(monkeypatch):
    """Build a self-contained marketing database and disable real rate waits."""
    monkeypatch.setattr(config, "SHOP_CAMPAIGN_DISPATCH_ENABLED", True)
    monkeypatch.setattr(config, "SHOP_BROADCAST_WORKER_ENABLED", True)
    monkeypatch.setattr(
        config, "SHOP_BROADCAST_REGISTRY_ENABLED", True, raising=False
    )
    monkeypatch.setenv(
        "SHOP_BOT_SECRET_KEY", "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
    )
    from services.shop_bot_secrets import encrypt_for_bot

    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_shop_schema(engine)
    with Session(engine, expire_on_commit=False) as session:
        seed_registry(session)
        for index, (platform, bot_id) in enumerate(TEST_BOT_IDS.items(), start=1):
            bot = session.get(ShopBot, bot_id)
            bot.provider_bot_id = 200000 + index
            session.add_all([
                ShopBotCredential(
                    id=f"credential-{platform}", bot_id=bot_id, version=1,
                    source="encrypted", state="active",
                    ciphertext=encrypt_for_bot(
                        bot_id, platform, TEST_TOKENS[platform]
                    ),
                    verified_bot_id=bot.provider_bot_id,
                ),
                ShopBotOperations(bot_id=bot_id, desired_state="active"),
                ShopBotReceiver(
                    bot_id=bot_id, binding_id=f"receiver-{platform}",
                    mode="webhook", state="active", credential_version=1,
                    webhook_secret_ciphertext="unused",
                    webhook_secret_digest="a" * 64,
                ),
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
                bot_id=TEST_BOT_IDS["telegram"], store_id=DEFAULT_STORE_ID,
                platform="telegram", platform_user_id=user_id,
                is_blocked=False, allow_announcements=True,
            )
        )
    campaign = ShopCampaign(
        bot_id=TEST_BOT_IDS["telegram"], store_id=DEFAULT_STORE_ID,
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
    transport = RecordingTransport(context)
    worker = BroadcastWorker(
        registry_transport_factory=transport_factory(transport)
    )
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
    transport = RecordingTransport(context)
    worker = BroadcastWorker(
        registry_transport_factory=transport_factory(transport)
    )
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
    transport = RecordingTransport(context)
    transport.fail_for = 1
    worker = BroadcastWorker(
        registry_transport_factory=transport_factory(transport)
    )
    assert await worker.process_next() is True
    assert campaign.status == "paused"
    states = await delivery_counts(context, campaign.id)
    assert states.get("unknown") == 1
    assert states.get("queued") == 2

    # The old worker's ID is not used to retry a possibly delivered update.
    newer_worker = BroadcastWorker(
        registry_transport_factory=transport_factory(transport)
    )
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
    monkeypatch.setattr(config, "BALE_BROADCAST_MODE", "business")
    monkeypatch.setattr(config, "BALE_BROADCAST_PAID_ENABLED", True)
    monkeypatch.setattr(config, "SHOP_BROADCAST_MAX_PAID_CALLS", 4)
    customer = ShopIdentity(
        bot_id=TEST_BOT_IDS["bale"], store_id=DEFAULT_STORE_ID,
        platform="bale", platform_user_id=301,
        is_blocked=False, allow_announcements=True,
    )
    context.session.add(customer)
    campaign = ShopCampaign(
        bot_id=TEST_BOT_IDS["bale"], store_id=DEFAULT_STORE_ID,
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

    recorder = RecordingTransport(context)
    worker = BroadcastWorker(
        registry_transport_factory=transport_factory(recorder)
    )
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
    monkeypatch.setattr(config, "BALE_BROADCAST_MODE", "business")
    monkeypatch.setattr(config, "BALE_BROADCAST_PAID_ENABLED", True)
    monkeypatch.setattr(config, "SHOP_BROADCAST_MAX_PAID_CALLS", 1)
    identity = ShopIdentity(
        bot_id=TEST_BOT_IDS["bale"], store_id=DEFAULT_STORE_ID,
        platform="bale", platform_user_id=904,
        is_blocked=False, allow_announcements=True,
    )
    campaign = ShopCampaign(
        bot_id=TEST_BOT_IDS["bale"], store_id=DEFAULT_STORE_ID,
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

    transport = RecordingTransport(
        context, platform="bale", bale_mode="business"
    )
    worker = BroadcastWorker(
        registry_transport_factory=transport_factory(transport)
    )
    assert await worker.process_next() is True
    await worker.finalize_campaigns()
    assert campaign.status == "completed"
    assert campaign.paid_calls_reserved == 1
    assert campaign.max_paid_calls == 1
    assert transport.sent == [904]
    assert transport.messages == [(904, "یک پیام")]
    assert await worker.process_next() is False
    assert campaign.paid_calls_reserved == 1
