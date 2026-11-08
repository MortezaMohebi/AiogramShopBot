"""Exercise PostgreSQL Registry broadcasts with native provider fakes only.

Importing the existing fixture enforces the named, isolated Beta QA stack
before application modules load. All enabled flags are temporary Python
overrides in this process; no receiver, webhook or real provider is activated.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

# This import must precede application imports: it enforces the isolated
# database identity, disabled provider flags and empty provider credentials.
# isort: split
from scripts.beta_storefront_e2e import FakeBaleSession, FakeTelegram

# isort: split
from sqlalchemy import func, select, text

import config
from db import engine, session_maker
from models.shop_bot_operations import ShopBotOperations
from models.shop_content import ShopIdentity
from models.shop_engagement import (
    ShopBroadcastRateSlot,
    ShopCampaign,
    ShopCampaignAudit,
    ShopCampaignDelivery,
)
from models.shop_multibot import ShopBot, ShopBotCredential, ShopStore
from models.shop_multibot_receiver import ShopBotReceiver
from services.shop_bot_secrets import encrypt_for_bot, encrypt_receiver_secret
from services.shop_broadcast_control import BroadcastControl
from services.shop_broadcast_rate import reserve_message_slot
from services.shop_broadcast_worker import BroadcastWorker, registry_transport
from services.shop_campaigns import CampaignRejected, ShopCampaignService

RESULT = Path("/qa/beta-broadcast-result.json")
CLEANUP_RESULT = Path("/qa/beta-broadcast-cleanup-result.json")


@dataclass(frozen=True, slots=True)
class SyntheticBot:
    """Keep the exact scope of one synthetic credential out of public output."""

    id: str
    store_id: str
    platform: str
    label: str
    token: str = field(repr=False)


class FakeConnections:
    """Intercept SDK and HTTP construction below the production factory."""

    def __init__(self, bots: list[SyntheticBot]) -> None:
        """Allocate independent native fakes and connection cleanup evidence."""
        self.bots = {bot.id: bot for bot in bots}
        self.clients = {
            bot.id: FakeTelegram() if bot.platform == "telegram" else FakeBaleSession()
            for bot in bots
        }
        for bot in bots:
            if bot.platform == "telegram":
                self.clients[bot.id].token = bot.token
        self.opened = 0
        self.closed = 0

    @asynccontextmanager
    async def telegram(self, platform: str, token: str, *, bot_id: str):
        """Yield only the fake attached to the exact saved bot and credential."""
        bot = self.bots[bot_id]
        assert platform == bot.platform == "telegram"
        assert token == bot.token
        self.opened += 1
        try:
            yield self.clients[bot_id]
        finally:
            self.closed += 1

    @asynccontextmanager
    async def bale(self, **kwargs):
        """Replace aiohttp without creating any socket or network-capable session."""
        assert kwargs["trust_env"] is False
        owner = self

        class Router:
            """Route one native Bale request only to a known synthetic token."""

            def post(self, url: str, **payload):
                """Reject every URL outside the known fake regular Bot API routes."""
                for bot in owner.bots.values():
                    if bot.platform == "bale" and url.startswith(
                        f"https://tapi.bale.ai/bot{bot.token}/"
                    ):
                        return owner.clients[bot.id].post(url, **payload)
                raise AssertionError("Unexpected external Bale target")

        self.opened += 1
        try:
            yield Router()
        finally:
            self.closed += 1

    def message_count(self, bot: SyntheticBot) -> int:
        """Count actual native adapter calls for one independently scoped bot."""
        return len(self.clients[bot.id].messages)


async def seed() -> list[SyntheticBot]:
    """Add only private, synthetic Registry rows without provider activation."""
    run_id = uuid4().hex[:12]
    now = datetime.now(UTC)
    store_ids = [str(uuid4()), str(uuid4())]
    bots = []
    async with session_maker() as db:
        assert await db.scalar(text("SELECT current_database()")) == "shop_codespace"
        assert await db.scalar(text("SELECT current_user")) == "shop_codespace"
        # The worker intentionally has a shared queue. Refuse an unrelated
        # active campaign rather than changing or consuming another QA run.
        assert not await db.scalar(
            select(func.count())
            .select_from(ShopCampaign)
            .where(ShopCampaign.status == "sending")
        ), "Another broadcast acceptance run still has an active campaign"
        for index, store_id in enumerate(store_ids):
            db.add(
                ShopStore(
                    id=store_id,
                    slug=f"qa-broadcast-{run_id}-{index}",
                    name=f"Synthetic broadcast Store {index}",
                    state="active",
                )
            )
        await db.flush()
        for index, (label, platform, store_index) in enumerate(
            (
                ("telegram-alpha", "telegram", 0),
                ("telegram-beta", "telegram", 1),
                ("bale-alpha", "bale", 0),
            )
        ):
            bot_id = str(uuid4())
            provider_id = 8_000_000_000 + (uuid4().int % 1_000_000_000) * 10 + index
            token = f"{provider_id}:" + secrets.token_urlsafe(32)
            bot = SyntheticBot(
                id=bot_id,
                store_id=store_ids[store_index],
                platform=platform,
                label=label,
                token=token,
            )
            bots.append(bot)
            db.add(
                ShopBot(
                    id=bot.id,
                    store_id=bot.store_id,
                    slug=f"qa-{label}-{run_id}",
                    name=f"Synthetic {label}",
                    platform=platform,
                    provider_bot_id=provider_id,
                    status="active",
                    runtime_owner="registry",
                    credential_version=1,
                    verified_at=now,
                )
            )
            await db.flush()
            secret = secrets.token_urlsafe(32)
            db.add_all(
                [
                    ShopBotCredential(
                        id=str(uuid4()),
                        bot_id=bot.id,
                        version=1,
                        source="encrypted",
                        state="active",
                        ciphertext=encrypt_for_bot(bot.id, platform, token),
                        verified_bot_id=provider_id,
                        verified_at=now,
                        activated_at=now,
                    ),
                    ShopBotOperations(
                        bot_id=bot.id,
                        desired_state="active",
                        environment="staging",
                    ),
                    ShopBotReceiver(
                        bot_id=bot.id,
                        binding_id=str(uuid4()),
                        mode="webhook",
                        state="active",
                        credential_version=1,
                        webhook_secret_ciphertext=encrypt_receiver_secret(
                            bot.id, secret
                        ),
                        webhook_secret_digest=hashlib.sha256(
                            secret.encode("ascii")
                        ).hexdigest(),
                    ),
                ]
            )
        await db.commit()
    return bots


async def approved_campaign(bot: SyntheticBot, *, user_id: int, label: str) -> int:
    """Approve only a fresh synthetic opt-in, scoped by exact Store and Bot."""
    async with session_maker() as db:
        previous = (
            await db.scalars(
                select(ShopIdentity).where(
                    ShopIdentity.bot_id == bot.id,
                )
            )
        ).all()
        for identity in previous:
            identity.allow_announcements = False
        db.add(
            ShopIdentity(
                bot_id=bot.id,
                store_id=bot.store_id,
                platform=bot.platform,
                platform_user_id=user_id,
                allow_announcements=True,
            )
        )
        campaign = ShopCampaign(
            bot_id=bot.id,
            store_id=bot.store_id,
            title=f"Synthetic {label}",
            text=f"Isolated QA announcement: {label}",
            audience="all",
            status="draft",
        )
        db.add(campaign)
        await db.commit()
        assert (
            await ShopCampaignService.approve(
                db,
                campaign_id=campaign.id,
                approver="isolated-beta-qa",
            )
            == 1
        )
        return campaign.id


async def start_campaign(campaign_id: int) -> None:
    """Use the production approval gate with no paid calls or payment features."""
    async with session_maker() as db:
        assert (
            await BroadcastControl.start(
                db,
                campaign_id=campaign_id,
                actor="isolated-beta-qa",
            )
            == 1
        )


def worker() -> BroadcastWorker:
    """Enable only the explicit production Registry factory inside this process."""
    return BroadcastWorker(registry_transport_factory=registry_transport)


async def drain(workers: list[BroadcastWorker], *, rounds: int = 12) -> None:
    """Exercise PostgreSQL skip-locked claims with a bounded concurrent loop."""
    for _ in range(rounds):
        results = await asyncio.gather(*(item.process_next() for item in workers))
        if not any(results):
            await workers[0].finalize_campaigns()
            return
    raise AssertionError("Synthetic broadcast queue did not drain within its bound")


async def deliveries(campaign_id: int) -> list[ShopCampaignDelivery]:
    """Read the production delivery ledger after committed worker outcomes."""
    async with session_maker() as db:
        return list(
            (
                await db.scalars(
                    select(ShopCampaignDelivery)
                    .where(
                        ShopCampaignDelivery.campaign_id == campaign_id,
                    )
                    .order_by(ShopCampaignDelivery.id)
                )
            ).all()
        )


async def pause_synthetic_bots(*, bot_ids: set[str] | None = None) -> dict:
    """Pause only this runner's proven synthetic QA rows, with no provider calls.

    An explicit ID set is used in a run's finally block. Retrospective cleanup
    scans only the private broadcast Store prefix, then verifies every Store,
    Bot, receiver and encrypted credential marker before mutating any row.
    It never deletes financial, campaign, identity or credential evidence.
    """
    if any(getattr(config, flag, False) for flag in (
        "MULTIBOT_V2_RUNTIME_ENABLED", "SHOP_CAMPAIGN_DISPATCH_ENABLED",
        "SHOP_BROADCAST_WORKER_ENABLED", "SHOP_BROADCAST_REGISTRY_ENABLED",
        "BALE_BROADCAST_PAID_ENABLED",
    )):
        raise RuntimeError("Broadcast cleanup requires disabled public runtime flags")
    async with session_maker() as db:
        if (
            await db.scalar(text("SELECT current_database()")) != "shop_codespace"
            or await db.scalar(text("SELECT current_user")) != "shop_codespace"
        ):
            raise RuntimeError("Broadcast cleanup requires the isolated QA database")
        query = select(ShopBot, ShopStore).join(
            ShopStore, ShopStore.id == ShopBot.store_id,
        ).where(ShopStore.slug.like("qa-broadcast-%"))
        if bot_ids is not None:
            query = query.where(ShopBot.id.in_(bot_ids))
        rows = (await db.execute(query.with_for_update())).all()
        if bot_ids is not None and {bot.id for bot, _ in rows} != bot_ids:
            raise RuntimeError("A requested cleanup Bot lacks synthetic ownership proof")
        verified = []
        for bot, store in rows:
            marker = re.fullmatch(r"qa-broadcast-([a-f0-9]{12})-([01])", store.slug)
            bot_marker = re.fullmatch(
                r"qa-(telegram-alpha|telegram-beta|bale-alpha)-([a-f0-9]{12})",
                bot.slug,
            )
            operations = await db.get(ShopBotOperations, bot.id)
            receiver = await db.get(ShopBotReceiver, bot.id)
            credentials = (await db.scalars(select(ShopBotCredential).where(
                ShopBotCredential.bot_id == bot.id,
            ))).all()
            label = bot_marker.group(1) if bot_marker else None
            credential = credentials[0] if len(credentials) == 1 else None
            valid = bool(
                marker and bot_marker
                and marker.group(1) == bot_marker.group(2)
                and store.name == f"Synthetic broadcast Store {marker.group(2)}"
                and marker.group(2) == ("1" if label == "telegram-beta" else "0")
                and bot.name == f"Synthetic {label}"
                and bot.platform == ("bale" if label == "bale-alpha" else "telegram")
                and bot.runtime_owner == "registry"
                and bot.status in {"active", "paused", "maintenance"}
                and bot.credential_version == 1
                and bot.provider_bot_id is not None
                and 8_000_000_000 <= bot.provider_bot_id < 18_000_000_000
                and operations is not None and operations.environment == "staging"
                and operations.desired_state in {"active", "paused", "maintenance"}
                and receiver is not None and receiver.mode == "webhook"
                and receiver.state in {"active", "paused"}
                and receiver.credential_version == 1
                and credential is not None and credential.version == 1
                and credential.source == "encrypted" and credential.state == "active"
                and credential.ciphertext
                and credential.verified_bot_id == bot.provider_bot_id
            )
            if not valid:
                raise RuntimeError("Synthetic broadcast fixture markers do not match")
            verified.append((bot, operations, receiver))
        # Validation is complete for every selected row before the first write.
        for bot, operations, receiver in verified:
            if bot.status != "paused":
                bot.status = "paused"
                bot.version += 1
            operations.desired_state = "paused"
            if receiver.state != "paused":
                receiver.state = "paused"
                receiver.version += 1
        await db.commit()
        return {
            "result": "cleaned", "paused_synthetic_bots": len(verified),
            "provider_calls": 0, "rows_deleted": 0,
        }


async def _run_with_bots(bots: list[SyntheticBot]) -> dict:
    """Verify bot isolation, native adapters, consent and at-most-once outcomes."""
    assert not config.SHOP_CAMPAIGN_DISPATCH_ENABLED
    assert not config.SHOP_BROADCAST_WORKER_ENABLED
    assert not config.SHOP_BROADCAST_REGISTRY_ENABLED
    assert not config.BALE_BROADCAST_PAID_ENABLED
    assert not config.MULTIBOT_V2_RUNTIME_ENABLED
    fake = FakeConnections(bots)
    normal = []
    user_id = 810_000_000 + uuid4().int % 10_000_000
    # All fake overrides are process-local. The API service continues to see
    # its original disabled environment and cannot send these campaigns.
    with (
        patch.multiple(
            config,
            SHOP_CAMPAIGN_DISPATCH_ENABLED=True,
            SHOP_BROADCAST_WORKER_ENABLED=True,
            SHOP_BROADCAST_REGISTRY_ENABLED=True,
            SHOP_BROADCAST_TELEGRAM_MPS=20,
            SHOP_BROADCAST_BALE_STANDARD_MPS=5,
        ),
        patch("services.shop_multibot_client.provider_client", fake.telegram),
        patch("aiohttp.ClientSession", fake.bale),
    ):
        for bot in bots:
            campaign_id = await approved_campaign(bot, user_id=user_id, label=bot.label)
            await start_campaign(campaign_id)
            normal.append(campaign_id)

        # A process without an explicit Registry factory must leave every
        # approved recipient untouched and never open a provider connection.
        missing_transport = BroadcastWorker()
        assert await missing_transport.process_next() is False
        assert fake.opened == fake.closed == 0
        for bot, campaign_id in zip(bots, normal, strict=True):
            rows = await deliveries(campaign_id)
            assert len(rows) == 1 and rows[0].status == "queued"
            assert rows[0].bot_id == bot.id and rows[0].completed_steps == 0
            assert rows[0].worker_id is None and rows[0].claimed_at is None
            assert fake.message_count(bot) == 0

        await drain([worker(), worker()])
        for bot, campaign_id in zip(bots, normal, strict=True):
            rows = await deliveries(campaign_id)
            assert len(rows) == 1 and rows[0].status == "sent"
            assert rows[0].bot_id == bot.id and rows[0].completed_steps == 1
            assert fake.message_count(bot) == 1
            native = fake.clients[bot.id]
            assert native.messages[0]["chat_id"] == user_id
            assert (
                native.messages[0]["text"] == f"Isolated QA announcement: {bot.label}"
            )
            assert not native.invoices, "Broadcast touched a payment API"

        opted_out = await approved_campaign(
            bots[2], user_id=user_id + 1, label="opt-out"
        )
        async with session_maker() as db:
            identity = await db.scalar(
                select(ShopIdentity).where(
                    ShopIdentity.bot_id == bots[2].id,
                    ShopIdentity.platform_user_id == user_id + 1,
                )
            )
            identity.allow_announcements = False
            await db.commit()
        await start_campaign(opted_out)
        before = fake.message_count(bots[2])
        await drain([worker(), worker()])
        assert fake.message_count(bots[2]) == before
        rows = await deliveries(opted_out)
        assert len(rows) == 1 and rows[0].status == "skipped"
        assert rows[0].completed_steps == 0

        paused = await approved_campaign(
            bots[1],
            user_id=user_id + 5,
            label="pause-during-rate-wait",
        )
        await start_campaign(paused)
        before = fake.message_count(bots[1])

        async def pause_during_slot(**kwargs):
            """Keep real PostgreSQL pacing while modeling an operator pause."""
            await reserve_message_slot(**kwargs)
            async with session_maker() as db:
                operations = await db.get(ShopBotOperations, kwargs["bot_id"])
                operations.desired_state = "paused"
                await db.commit()

        with patch(
            "services.shop_broadcast_worker.reserve_message_slot",
            pause_during_slot,
        ):
            assert await worker().process_next() is True
        rows = await deliveries(paused)
        assert len(rows) == 1 and rows[0].status == "skipped"
        assert fake.message_count(bots[1]) == before
        async with session_maker() as db:
            operations = await db.get(ShopBotOperations, bots[1].id)
            operations.desired_state = "active"
            await db.commit()
        await worker().finalize_campaigns()

        poisoned = await approved_campaign(bots[1], user_id=user_id + 2, label="scope")
        async with session_maker() as db:
            wrong = ShopIdentity(
                bot_id=bots[1].id,
                store_id=bots[0].store_id,
                platform="telegram",
                platform_user_id=user_id + 3,
                allow_announcements=True,
            )
            db.add(wrong)
            await db.flush()
            # Reapprove a fresh draft so the actual INSERT SELECT must exclude
            # the poisoned Store even though its bot_id and consent match.
            scope_campaign = ShopCampaign(
                bot_id=bots[1].id,
                store_id=bots[1].store_id,
                title="Synthetic Store isolation",
                text="Scope validation",
                audience="telegram",
                status="draft",
            )
            db.add(scope_campaign)
            await db.commit()
            assert (
                await ShopCampaignService.approve(
                    db,
                    campaign_id=scope_campaign.id,
                    approver="isolated-beta-qa",
                )
                == 1
            )
            rows = await deliveries(scope_campaign.id)
            assert wrong.id not in {row.identity_id for row in rows}
            # If a corrupt child is inserted after approval, start must reject
            # it rather than trusting the frozen recipient count.
            db.add(
                ShopCampaignDelivery(
                    campaign_id=poisoned,
                    identity_id=wrong.id,
                    bot_id=bots[1].id,
                )
            )
            await db.commit()
            try:
                await BroadcastControl.start(
                    db,
                    campaign_id=poisoned,
                    actor="isolated-beta-qa",
                )
            except CampaignRejected:
                await db.rollback()
            else:
                raise AssertionError("A cross-Store ledger row was allowed to start")

        uncertain = await approved_campaign(
            bots[0],
            user_id=user_id + 4,
            label="ambiguous-outcome",
        )
        await start_campaign(uncertain)
        before = fake.message_count(bots[0])
        fake.clients[bots[0].id].fail_delivery = True
        try:
            assert await worker().process_next() is True
        finally:
            fake.clients[bots[0].id].fail_delivery = False
        rows = await deliveries(uncertain)
        assert len(rows) == 1 and rows[0].status == "unknown"
        assert rows[0].completed_steps == 0
        assert fake.message_count(bots[0]) == before + 1
        assert await worker().process_next() is False
        assert await worker().process_next() is False
        assert fake.message_count(bots[0]) == before + 1

        async with session_maker() as db:
            campaign = await db.get(ShopCampaign, uncertain)
            assert campaign.status == "paused"
            actions = (
                await db.scalars(
                    select(ShopCampaignAudit.action).where(
                        ShopCampaignAudit.campaign_id == uncertain,
                    )
                )
            ).all()
            assert "delivery_uncertain" in actions
            slots = (
                await db.scalars(
                    select(ShopBroadcastRateSlot).where(
                        ShopBroadcastRateSlot.bot_id.in_([bot.id for bot in bots]),
                    )
                )
            ).all()
            assert len(slots) >= 7
            for bot in bots:
                owned = [row for row in slots if row.bot_id == bot.id]
                assert {0, user_id} <= {row.recipient_id for row in owned}
                assert all(row.platform == bot.platform for row in owned)
                assert all(
                    row.bot_fingerprint
                    == hashlib.sha256(
                        bot.token.encode("ascii"),
                    ).hexdigest()
                    for row in owned
                )
    assert fake.opened == fake.closed
    assert not config.SHOP_CAMPAIGN_DISPATCH_ENABLED
    assert not config.SHOP_BROADCAST_WORKER_ENABLED
    assert not config.SHOP_BROADCAST_REGISTRY_ENABLED
    return {
        "result": "passed",
        "providers": "native-fakes-only",
        "simultaneous_workers": 2,
        "missing_registry_transport_left_queue_untouched": True,
        "isolated_bots": len(bots),
        "sent": len(normal),
        "opt_out_skipped": 1,
        "operations_pause_during_rate_wait": True,
        "cross_store_start_rejected": True,
        "unknown_quarantined_without_retry": 1,
        "real_postgresql_rate_slots": len(slots),
        "client_connections_closed": fake.closed,
        "public_runtime_flags_unchanged": True,
    }


async def run() -> dict:
    """Exercise fresh synthetic Bots and pause only their receivers on every exit."""
    assert not config.SHOP_CAMPAIGN_DISPATCH_ENABLED
    assert not config.SHOP_BROADCAST_WORKER_ENABLED
    assert not config.SHOP_BROADCAST_REGISTRY_ENABLED
    assert not config.BALE_BROADCAST_PAID_ENABLED
    assert not config.MULTIBOT_V2_RUNTIME_ENABLED
    bots = await seed()
    try:
        report = await _run_with_bots(bots)
    finally:
        cleanup = await pause_synthetic_bots(bot_ids={bot.id for bot in bots})
    report["synthetic_receivers_paused"] = cleanup["paused_synthetic_bots"]
    return report


async def main() -> None:
    """Write non-secret acceptance evidence and always release the DB pool."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cleanup", action="store_true",
        help="Pause only verified synthetic broadcast fixtures; do not send or delete",
    )
    arguments = parser.parse_args()
    try:
        report = await pause_synthetic_bots() if arguments.cleanup else await run()
        result_path = CLEANUP_RESULT if arguments.cleanup else RESULT
        result_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, sort_keys=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
