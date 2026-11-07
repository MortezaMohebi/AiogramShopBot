"""Exercise Registry campaign ownership with durable rows and fake providers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import config
import db
from channels.contracts import BotReply, MediaAttachment
from models.base import Base
from models.shop_bot_operations import ShopBotOperations
from models.shop_content import ShopIdentity
from models.shop_customer_crm import ShopCustomerProfile
from models.shop_engagement import (
    ShopBroadcastWorkerHeartbeat,
    ShopCampaign,
    ShopCampaignAudit,
    ShopCampaignDelivery,
    ShopCampaignMedia,
)
from models.shop_multibot import (
    ShopBot,
    ShopBotCredential,
    ShopStore,
)
from models.shop_multibot_receiver import ShopBotReceiver
from models.shop_staff import ShopStaff
from services.shop_broadcast_control import BroadcastControl
from services.shop_broadcast_worker import BroadcastWorker
from services.shop_campaigns import CampaignRejected, ShopCampaignService
from services.shop_store_context import (
    AuthorizedStore,
    StoreContext,
    bind_context,
)


class LocalAsyncSession:
    """Keep SQLAlchemy transactions real while adapting local SQLite to async."""

    def __init__(self, session: Session) -> None:
        """Retain the disposable transaction and its identity map."""
        self.session = session

    async def scalar(self, statement):
        """Read one scalar from the isolated database."""
        return self.session.scalar(statement)

    async def execute(self, statement):
        """Execute real SQL against the isolated database."""
        return self.session.execute(statement)

    async def get(self, model, key):
        """Read a row by its real primary key."""
        return self.session.get(model, key)

    async def run_sync(self, operation):
        """Use the same connection for synchronous credential resolution."""
        return operation(self.session)

    async def commit(self):
        """Persist a state transition before a fake provider call."""
        self.session.commit()

    def add(self, row):
        """Stage a real durable model row."""
        self.session.add(row)


@pytest.fixture
def registry(monkeypatch):
    """Seed independent Stores, bots, credentials and opted-in identities."""
    monkeypatch.setattr(config, "SHOP_CAMPAIGN_DISPATCH_ENABLED", True)
    monkeypatch.setattr(config, "SHOP_BROADCAST_WORKER_ENABLED", True)
    monkeypatch.setattr(
        config,
        "SHOP_BROADCAST_REGISTRY_ENABLED",
        True,
        raising=False,
    )
    # Registry sending must work without accidentally requiring legacy tokens
    # or enabling any payment rail.
    monkeypatch.setattr(config, "TOKEN", "", raising=False)
    monkeypatch.setattr(config, "BALE_BOT_TOKEN", "", raising=False)
    monkeypatch.setenv(
        "SHOP_BOT_SECRET_KEY", "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
    )
    from services.shop_bot_secrets import encrypt_for_bot

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ShopStaff.__table__,
            ShopStore.__table__,
            ShopBot.__table__,
            ShopBotCredential.__table__,
            ShopBotOperations.__table__,
            ShopBotReceiver.__table__,
            ShopIdentity.__table__,
            ShopCustomerProfile.__table__,
            ShopCampaign.__table__,
            ShopCampaignDelivery.__table__,
            ShopCampaignMedia.__table__,
            ShopCampaignAudit.__table__,
            ShopBroadcastWorkerHeartbeat.__table__,
        ],
    )
    with Session(engine, expire_on_commit=False) as session:
        stores = [
            ShopStore(id=str(uuid4()), slug=f"store-{i}", name=f"Store {i}")
            for i in range(2)
        ]
        session.add_all(stores)
        bots = []
        tokens = {}
        for i, platform in enumerate(("telegram", "telegram", "bale")):
            bot = ShopBot(
                id=str(uuid4()),
                store_id=stores[i % 2].id,
                slug=f"bot-{i}",
                name=f"Bot {i}",
                platform=platform,
                provider_bot_id=200001 + i,
                status="active",
                runtime_owner="registry",
                credential_version=1,
            )
            token = f"{200001 + i}:" + (chr(65 + i) * 32)
            tokens[bot.id] = token
            session.add_all(
                [
                    bot,
                    ShopBotCredential(
                        id=str(uuid4()),
                        bot_id=bot.id,
                        version=1,
                        source="encrypted",
                        state="active",
                        ciphertext=encrypt_for_bot(bot.id, platform, token),
                        verified_bot_id=bot.provider_bot_id,
                    ),
                    ShopBotOperations(bot_id=bot.id, desired_state="active"),
                    ShopBotReceiver(
                        bot_id=bot.id,
                        binding_id=str(uuid4()),
                        mode="webhook",
                        state="active",
                        webhook_secret_ciphertext="unused",
                        webhook_secret_digest="a" * 64,
                        credential_version=1,
                    ),
                    ShopIdentity(
                        bot_id=bot.id,
                        store_id=bot.store_id,
                        platform=platform,
                        platform_user_id=777,
                        allow_announcements=True,
                    ),
                ]
            )
            bots.append(bot)
        session.commit()
        adapter = LocalAsyncSession(session)

        @asynccontextmanager
        async def sessions():
            """Keep all worker state changes on the disposable database."""
            yield adapter

        monkeypatch.setattr(db, "session_maker", sessions)
        pacing = []

        async def reserve(**kwargs):
            """Replace only the external pacing clock, preserving arguments."""
            pacing.append(kwargs)

        monkeypatch.setattr(
            "services.shop_broadcast_worker.reserve_message_slot",
            reserve,
        )
        yield SimpleNamespace(
            db=adapter,
            bots=bots,
            stores=stores,
            tokens=tokens,
            pacing=pacing,
        )
    engine.dispose()


def draft(registry, bot: ShopBot) -> ShopCampaign:
    """Create one explicit bot-targeted draft without bypassing approval."""
    campaign = ShopCampaign(
        bot_id=bot.id,
        store_id=bot.store_id,
        title="Consent test",
        text="Approved shop announcement",
        audience=bot.platform,
    )
    registry.db.add(campaign)
    registry.db.session.commit()
    return campaign


async def start(registry, campaign: ShopCampaign) -> None:
    """Use the same approval/start path as the authenticated dashboard."""
    assert (
        await ShopCampaignService.approve(
            registry.db,
            campaign_id=campaign.id,
            approver="offline-staff:1",
        )
        == 1
    )
    assert (
        await BroadcastControl.start(
            registry.db,
            campaign_id=campaign.id,
            actor="offline-staff:1",
        )
        == 1
    )


def fake_factory(registry, sent: list, *, fail: bool = False, after_send=None):
    """Replace only provider delivery with an exact, bot-scoped recording."""

    @asynccontextmanager
    async def factory(claim):
        """Yield one transport for the worker's immutable bot claim."""
        from services.shop_broadcast_worker import CampaignTransport

        class Provider:
            """Record the actual recipient and owner of attempted delivery."""

            bot_id = claim.bot_id

            async def send(self, user_id: int, reply: BotReply) -> None:
                """Simulate one result without contacting Telegram or Bale."""
                sent.append((claim.bot_id, user_id, reply.text))
                if fail:
                    raise TimeoutError("Ambiguous fake provider result")
                if after_send is not None:
                    after_send()

            async def send_media(self, user_id, attachment) -> None:
                """Record a media step for consent boundary checks."""
                sent.append((claim.bot_id, user_id, attachment.storage_key))

        yield CampaignTransport(
            bot_id=claim.bot_id,
            platform=claim.platform,
            credential_version=claim.credential_version,
            token=registry.tokens[claim.bot_id],
            transport=Provider(),
        )

    return factory


@pytest.mark.asyncio
async def test_registry_campaign_drains_via_its_own_bot_without_payment_flags(
    registry,
):
    """Catch legacy token fallback and same-numeric-user cross-bot delivery."""
    sent = []
    campaigns = [draft(registry, bot) for bot in registry.bots]
    for campaign in campaigns:
        await start(registry, campaign)
    worker = BroadcastWorker(
        registry_transport_factory=fake_factory(registry, sent),
    )
    for _ in range(3):
        assert await worker.process_next() is True
    await worker.finalize_campaigns()
    assert await worker.process_next() is False
    assert sent == [
        (bot.id, 777, "Approved shop announcement") for bot in registry.bots
    ]
    assert [campaign.status for campaign in campaigns] == ["completed"] * 3
    assert [item["bot_id"] for item in registry.pacing] == [
        bot.id for bot in registry.bots
    ]
    assert [item["token"] for item in registry.pacing] == [
        registry.tokens[bot.id] for bot in registry.bots
    ]


@pytest.mark.asyncio
async def test_registry_approval_excludes_same_bot_identity_in_another_store(
    registry,
):
    """Catch unscoped INSERT SELECT even when a poisoned identity shares bot_id."""
    bot = registry.bots[0]
    wrong = ShopIdentity(
        bot_id=bot.id,
        store_id=registry.stores[1].id,
        platform=bot.platform,
        platform_user_id=999,
        allow_announcements=True,
    )
    registry.db.add(wrong)
    campaign = draft(registry, bot)
    assert (
        await ShopCampaignService.approve(
            registry.db,
            campaign_id=campaign.id,
            approver="offline-staff:1",
        )
        == 1
    )
    recipients = registry.db.session.scalars(
        select(ShopCampaignDelivery.identity_id),
    ).all()
    assert wrong.id not in recipients


@pytest.mark.asyncio
async def test_registry_campaign_store_must_own_target_bot(registry):
    """A campaign cannot approve another Store's bot by guessing its UUID."""
    campaign = draft(registry, registry.bots[0])
    campaign.store_id = registry.stores[1].id
    registry.db.session.commit()
    with pytest.raises(CampaignRejected):
        await ShopCampaignService.approve(
            registry.db,
            campaign_id=campaign.id,
            approver="offline-staff:1",
        )
    assert campaign.status == "draft"


@pytest.mark.asyncio
async def test_registry_resume_requires_runtime_and_registry_opt_in(
    registry,
    monkeypatch,
):
    """A paused campaign cannot resume after the Registry deployment gate closes."""
    campaign = draft(registry, registry.bots[0])
    await start(registry, campaign)
    await BroadcastControl.change(
        registry.db,
        campaign_id=campaign.id,
        actor="offline-staff:1",
        action="pause",
    )
    monkeypatch.setattr(config, "SHOP_BROADCAST_REGISTRY_ENABLED", False)
    with pytest.raises(CampaignRejected):
        await BroadcastControl.change(
            registry.db,
            campaign_id=campaign.id,
            actor="offline-staff:1",
            action="resume",
        )
    assert campaign.status == "paused"


@pytest.mark.asyncio
async def test_paid_registry_bale_preflight_uses_only_its_own_file_namespace(
    registry,
    monkeypatch,
    tmp_path,
):
    """Paid media preflight cannot require or borrow the legacy Bale credential."""
    monkeypatch.setattr(config, "SHOP_MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(config, "BALE_BROADCAST_MODE", "business")
    monkeypatch.setattr(config, "BALE_BROADCAST_PAID_ENABLED", True)
    monkeypatch.setattr(config, "SHOP_BROADCAST_MAX_PAID_CALLS", 2)
    bot = registry.bots[2]
    campaign = draft(registry, bot)
    key = "a" * 32 + ".png"
    original = b"\x89PNG\r\n\x1a\nfixture"
    (tmp_path / key).write_bytes(original)
    registry.db.add(
        ShopCampaignMedia(
            campaign_id=campaign.id,
            storage_key=key,
            original_filename="photo.png",
            kind="photo",
            mime_type="image/png",
            size_bytes=len(original),
        )
    )
    registry.db.session.commit()
    from services.shop_broadcast_control import _business_media_ready
    from services.shop_media_delivery import bot_fingerprint

    calls = []

    async def cached(**kwargs):
        """Return a file ID only for this exact bot and credential namespace."""
        calls.append(kwargs)
        if kwargs.get("bot_id") == bot.id and kwargs["bot_key"] == bot_fingerprint(
            registry.tokens[bot.id]
        ):
            return "only-this-registry-bot-file-id"
        return None

    monkeypatch.setattr("services.shop_broadcast_control.cached_file_id", cached)
    assert await _business_media_ready(registry.db, campaign) == 1
    assert calls[0]["bot_id"] == bot.id
    assert (
        await ShopCampaignService.approve(
            registry.db,
            campaign_id=campaign.id,
            approver="offline-staff:1",
        )
        == 1
    )
    assert (
        await BroadcastControl.start(
            registry.db,
            campaign_id=campaign.id,
            actor="offline-staff:1",
            bale_mode="business",
            approved_paid_calls=2,
        )
        == 1
    )
    sent = []
    worker = BroadcastWorker(
        registry_transport_factory=fake_factory(registry, sent),
    )
    assert await worker.process_next() is True
    assert len(sent) == 2
    assert campaign.paid_calls_reserved == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["approve", "start", "pause", "resume", "cancel", "reconcile"]
)
async def test_campaign_mutations_require_the_trusted_current_store(
    registry,
    operation,
):
    """Direct service calls must not bypass Store writes through identity-map rows."""
    from services.shop_admin_security import SecurityRejected

    campaign = draft(registry, registry.bots[0])
    if operation != "approve":
        await start(registry, campaign)
    if operation in {"resume", "reconcile"}:
        campaign.status = "paused"
    delivery = registry.db.session.scalar(select(ShopCampaignDelivery))
    if operation == "reconcile":
        delivery.status = "unknown"
    registry.db.session.commit()
    store = registry.stores[1]
    scope = StoreContext(
        staff_id=1,
        session_id="offline-session",
        allowed_stores=(
            AuthorizedStore(
                id=store.id,
                slug=store.slug,
                name=store.name,
                state="active",
                access_level="manager",
            ),
        ),
        active_store_ids=(store.id,),
        current_store_id=store.id,
        default_store_id=store.id,
        version=1,
    )
    before = campaign.status
    # The live ORM filter may hide the row before the explicit scope check.
    # Both denial paths must preserve the durable campaign and delivery.
    with bind_context(scope), pytest.raises((SecurityRejected, CampaignRejected)):
        if operation == "approve":
            await ShopCampaignService.approve(
                registry.db,
                campaign_id=campaign.id,
                approver="offline-staff:1",
            )
        elif operation == "start":
            # Reset only the campaign state; retain the durable approved queue.
            campaign.status = "approved"
            before = "approved"
            await BroadcastControl.start(
                registry.db,
                campaign_id=campaign.id,
                actor="offline-staff:1",
            )
        elif operation == "reconcile":
            await BroadcastControl.reconcile(
                registry.db,
                campaign_id=campaign.id,
                delivery_id=delivery.id,
                actor="offline-staff:1",
                resolution="skipped",
                evidence="Offline evidence of non-delivery",
            )
        else:
            await BroadcastControl.change(
                registry.db,
                campaign_id=campaign.id,
                actor="offline-staff:1",
                action=operation,
            )
    assert campaign.status == before


@pytest.mark.asyncio
async def test_cli_injects_dynamically_gated_registry_factory(
    registry,
    monkeypatch,
):
    """The real command must wire scoped transports without opening legacy clients."""

    async def no_database_startup():
        """Avoid touching a configured deployment database."""
        return

    monkeypatch.setattr(
        db,
        "engine",
        SimpleNamespace(dispose=no_database_startup),
        raising=False,
    )
    import workers.shop_broadcast as entrypoint

    recorded = []

    class Worker:
        """Finish immediately while recording CLI runtime construction."""

        def __init__(self, **kwargs):
            """Capture the explicitly selected runtime capabilities."""
            recorded.append(kwargs)

        async def run_forever(self):
            """Avoid starting background polling in this offline wiring test."""
            return

    monkeypatch.setattr(entrypoint, "BroadcastWorker", Worker)
    monkeypatch.setattr(entrypoint, "create_db_and_tables", no_database_startup)
    for enabled in (False, True):
        monkeypatch.setattr(config, "SHOP_BROADCAST_REGISTRY_ENABLED", enabled)
        await entrypoint.main()
    assert [item["registry_transport_factory"] for item in recorded] == [
        entrypoint.registry_transport, entrypoint.registry_transport,
    ]


@pytest.mark.asyncio
async def test_consent_change_while_reserving_paid_budget_stops_the_send(
    registry,
    monkeypatch,
):
    """A campaign-row lock wait must not outlive the last marketing consent check."""
    monkeypatch.setattr(config, "BALE_BROADCAST_MODE", "business")
    monkeypatch.setattr(config, "BALE_BROADCAST_PAID_ENABLED", True)
    monkeypatch.setattr(config, "SHOP_BROADCAST_MAX_PAID_CALLS", 1)
    campaign = draft(registry, registry.bots[2])
    assert (
        await ShopCampaignService.approve(
            registry.db,
            campaign_id=campaign.id,
            approver="offline-staff:1",
        )
        == 1
    )
    await BroadcastControl.start(
        registry.db,
        campaign_id=campaign.id,
        actor="offline-staff:1",
        bale_mode="business",
        approved_paid_calls=1,
    )
    sent = []
    worker = BroadcastWorker(
        registry_transport_factory=fake_factory(registry, sent),
    )
    reserve = worker._paid_reservation

    async def withdraw_during_reservation(claim):
        """Model a live unsubscribe committed during a budget transaction."""
        await reserve(claim)
        identity = registry.db.session.get(ShopIdentity, claim.identity_id)
        identity.allow_announcements = False
        registry.db.session.commit()

    monkeypatch.setattr(worker, "_paid_reservation", withdraw_during_reservation)
    assert await worker.process_next() is True
    assert sent == []
    assert campaign.paid_calls_reserved == 1
    assert registry.db.session.scalar(select(ShopCampaignDelivery.status)) == "skipped"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [
        "operations",
        "store",
        "bot",
        "receiver",
        "credential",
        "scope",
        "flag",
    ],
)
async def test_registry_claim_remains_queued_when_runtime_is_not_permitted(
    registry,
    monkeypatch,
    changed,
):
    """Paused runtime or invalid ownership cannot create a provider attempt."""
    bot = registry.bots[0]
    campaign = draft(registry, bot)
    await start(registry, campaign)
    session = registry.db.session
    if changed == "operations":
        session.get(ShopBotOperations, bot.id).desired_state = "paused"
    elif changed == "store":
        registry.stores[0].state = "paused"
    elif changed == "bot":
        bot.status = "disabled"
    elif changed == "receiver":
        session.get(ShopBotReceiver, bot.id).state = "needs_review"
    elif changed == "credential":
        session.scalar(
            select(ShopBotCredential).where(
                ShopBotCredential.bot_id == bot.id,
            )
        ).state = "revoked"
    elif changed == "scope":
        campaign.store_id = registry.stores[1].id
    else:
        monkeypatch.setattr(config, "SHOP_BROADCAST_REGISTRY_ENABLED", False)
    session.commit()
    sent = []
    worker = BroadcastWorker(
        registry_transport_factory=fake_factory(registry, sent),
    )
    assert await worker.process_next() is False
    assert session.scalar(select(ShopCampaignDelivery.status)) == "queued"
    assert sent == []


@pytest.mark.asyncio
async def test_default_worker_leaves_registry_outbox_untouched(registry):
    """A global flag cannot turn a legacy-only worker into a Registry sender."""
    campaign = draft(registry, registry.bots[0])
    await start(registry, campaign)
    worker = BroadcastWorker()
    assert await worker.process_next() is False
    assert registry.db.session.scalar(select(ShopCampaignDelivery.status)) == "queued"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [
        "consent",
        "blocked",
        "identity_store",
        "identity_user",
        "delivery_bot",
        "campaign_bot",
        "campaign_store",
        "operations",
        "credential",
        "receiver",
    ],
)
async def test_scoped_claim_is_revalidated_after_pacing_wait(
    registry,
    monkeypatch,
    changed,
):
    """A frozen recipient cannot change owner or permission while awaiting its slot."""
    bot = registry.bots[0]
    campaign = draft(registry, bot)
    await start(registry, campaign)
    sent = []
    worker = BroadcastWorker(
        registry_transport_factory=fake_factory(registry, sent),
    )

    async def change_while_waiting(**kwargs):
        """Commit the same changes an administrator or opt-out can make."""
        session = registry.db.session
        delivery = session.scalar(select(ShopCampaignDelivery))
        identity = session.get(ShopIdentity, delivery.identity_id)
        if changed == "consent":
            identity.allow_announcements = False
        elif changed == "blocked":
            identity.is_blocked = True
        elif changed == "identity_store":
            identity.store_id = registry.stores[1].id
        elif changed == "identity_user":
            identity.platform_user_id = 888
        elif changed == "delivery_bot":
            delivery.bot_id = registry.bots[1].id
        elif changed == "campaign_bot":
            campaign.bot_id = registry.bots[1].id
        elif changed == "campaign_store":
            campaign.store_id = registry.stores[1].id
        elif changed == "operations":
            session.get(ShopBotOperations, bot.id).desired_state = "maintenance"
        elif changed == "credential":
            bot.credential_version = 2
        elif changed == "receiver":
            session.get(ShopBotReceiver, bot.id).state = "paused"
        session.commit()

    monkeypatch.setattr(
        "services.shop_broadcast_worker.reserve_message_slot",
        change_while_waiting,
    )
    assert await worker.process_next() is True
    assert sent == []
    assert registry.db.session.scalar(select(ShopCampaignDelivery.status)) == "skipped"


@pytest.mark.asyncio
async def test_uncertain_registry_send_is_quarantined_and_never_retried(registry):
    """A timeout may have delivered; it must pause the campaign without replay."""
    campaign = draft(registry, registry.bots[0])
    await start(registry, campaign)
    sent = []
    factory = fake_factory(registry, sent, fail=True)
    worker = BroadcastWorker(
        registry_transport_factory=factory,
    )
    assert await worker.process_next() is True
    assert campaign.status == "paused"
    assert registry.db.session.scalar(select(ShopCampaignDelivery.status)) == "unknown"
    restarted = BroadcastWorker(
        registry_transport_factory=factory,
    )
    assert await restarted.process_next() is False
    assert len(sent) == 1
    assert registry.db.session.scalar(select(ShopCampaignAudit.action)) == "start"
    assert (
        "delivery_uncertain"
        in registry.db.session.scalars(
            select(ShopCampaignAudit.action),
        ).all()
    )


@pytest.mark.asyncio
async def test_registry_partial_delivery_is_quarantined_after_pause(registry):
    """A confirmed text followed by a revoked permission must not send media."""
    bot = registry.bots[0]
    campaign = draft(registry, bot)
    await start(registry, campaign)
    sent = []

    def pause_after_text():
        """Pause only this bot after the first confirmed provider response."""
        registry.db.session.get(ShopBotOperations, bot.id).desired_state = "paused"
        registry.db.session.commit()

    worker = BroadcastWorker(
        registry_transport_factory=fake_factory(
            registry,
            sent,
            after_send=pause_after_text,
        ),
    )
    claim = await worker._claim_one()
    await worker._send_one(
        claim,
        text=campaign.text,
        attachments=(
            MediaAttachment(
                storage_key="b" * 32 + ".png",
                kind="photo",
                mime_type="image/png",
            ),
        ),
    )
    delivery = registry.db.session.scalar(select(ShopCampaignDelivery))
    assert delivery.status == "unknown"
    assert delivery.completed_steps == 1
    assert campaign.status == "paused"
    assert len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bot_index,business", [(0, False), (1, False), (2, False), (2, True)]
)
async def test_cli_factory_resolves_exact_encrypted_credential_and_closes_client(
    registry,
    monkeypatch,
    bot_index,
    business,
):
    """Exercise production credential decryption and transport selection offline."""
    import aiohttp

    from channels.bale import BaleTransport
    from channels.telegram import TelegramTransport
    from services.shop_broadcast_worker import registry_transport

    bot = registry.bots[bot_index]
    campaign = draft(registry, bot)
    await ShopCampaignService.approve(
        registry.db,
        campaign_id=campaign.id,
        approver="offline-staff:1",
    )
    if business:
        monkeypatch.setattr(config, "BALE_BROADCAST_MODE", "business")
        monkeypatch.setattr(config, "BALE_BROADCAST_PAID_ENABLED", True)
        monkeypatch.setattr(config, "SHOP_BROADCAST_MAX_PAID_CALLS", 1)
    await BroadcastControl.start(
        registry.db,
        campaign_id=campaign.id,
        actor="offline-staff:1",
        bale_mode="business" if business else "standard",
        approved_paid_calls=1 if business else 0,
    )
    worker = BroadcastWorker(
        registry_transport_factory=registry_transport,
    )
    claim = await worker._claim_one()
    lifecycle = []

    @asynccontextmanager
    async def provider(platform, token, *, bot_id):
        """Replace the external connection while retaining production selection."""
        lifecycle.append(("opened", platform, bot_id))
        try:
            yield SimpleNamespace(token=token)
        finally:
            lifecycle.append(("closed", platform, bot_id))

    @asynccontextmanager
    async def http_session(**kwargs):
        """Replace only aiohttp's external-session boundary for Bale."""
        assert kwargs["trust_env"] is False
        lifecycle.append(("opened", "bale", bot.id))
        try:
            yield object()
        finally:
            lifecycle.append(("closed", "bale", bot.id))

    monkeypatch.setattr("services.shop_multibot_client.provider_client", provider)
    monkeypatch.setattr(aiohttp, "ClientSession", http_session)
    with pytest.raises(RuntimeError, match="local cleanup probe"):
        async with registry_transport(claim) as outbound:
            assert outbound.bot_id == bot.id
            assert outbound.token == registry.tokens[bot.id]
            assert outbound.credential_version == 1
            assert outbound.transport.bot_id == bot.id
            assert registry.tokens[bot.id] not in repr(outbound)
            if bot.platform == "telegram":
                assert isinstance(outbound.transport, TelegramTransport)
                assert outbound.transport.bot.token == registry.tokens[bot.id]
            else:
                assert isinstance(outbound.transport, BaleTransport)
                assert outbound.transport._bot_token == registry.tokens[bot.id]
                assert outbound.transport._business_mode is business
            raise RuntimeError("local cleanup probe")
    assert lifecycle == [
        ("opened", bot.platform, bot.id),
        ("closed", bot.platform, bot.id),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("bot_index", [0, 2])
@pytest.mark.parametrize("restriction", ["expired", "future", "permanent"])
@pytest.mark.parametrize("stage", ["approval", "claim", "rate_wait"])
async def test_campaign_rechecks_effective_restrictions_at_every_send_boundary(
    registry, monkeypatch, bot_index, restriction, stage,
):
    """CRM expiry restores consent eligibility; current/permanent restrictions deny."""
    bot = registry.bots[bot_index]
    person = registry.db.session.scalar(select(ShopIdentity).where(
        ShopIdentity.bot_id == bot.id,
    ))

    def restrict():
        """Preserve the audit flag while applying the exact identity's expiry."""
        person.is_blocked = True
        registry.db.add(ShopCustomerProfile(
            identity_id=person.id,
            restriction_until=(
                None if restriction == "permanent" else
                datetime.now(UTC) + timedelta(minutes=-1 if restriction == "expired" else 5)
            ),
        ))
        registry.db.session.commit()

    campaign = draft(registry, bot)
    if stage == "approval":
        restrict()
        count = await ShopCampaignService.approve(
            registry.db, campaign_id=campaign.id, approver="offline-staff:1",
        )
        assert count == (1 if restriction == "expired" else 0)
        if count == 0:
            assert campaign.status == "completed"
            return
        await BroadcastControl.start(
            registry.db, campaign_id=campaign.id, actor="offline-staff:1",
        )
    else:
        await start(registry, campaign)
        if stage == "claim":
            restrict()
        else:
            async def reserve(**kwargs):
                """Change real CRM state after the worker reserves its rate slot."""
                registry.pacing.append(kwargs)
                restrict()

            monkeypatch.setattr("services.shop_broadcast_worker.reserve_message_slot", reserve)
    sent = []
    worker = BroadcastWorker(
        registry_transport_factory=fake_factory(registry, sent),
    )
    assert await worker.process_next()
    assert bool(sent) is (restriction == "expired")
    assert person.is_blocked is True
