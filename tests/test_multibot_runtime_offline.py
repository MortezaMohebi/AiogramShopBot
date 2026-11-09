"""Offline acceptance contracts for bot-scoped runtime and commerce.

These tests deliberately use disposable SQLite data and no Telegram, Bale,
Redis, PostgreSQL server, payment provider, or background worker. The live
migration, shared lease, and real provider scenarios require later E2E QA.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import config
from channels.contracts import Platform
from models.base import Base
from models.shop_checkout import ShopCart, ShopCoupon, ShopShippingMethod
from models.shop_content import ShopIdentity
from models.shop_delivery import ShopInboundUpdate
from models.shop_engagement import ShopCampaign
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot, ShopStore
from models.shop_multibot_receiver import ShopBotReceiver
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services.shop_bot_context import resolve_bot_context
from services.shop_broadcast_control import BroadcastControl
from services.shop_campaigns import CampaignRejected
from services.shop_multibot_receiver_control import receiver_snapshot
from services.shop_multibot_webhook import webhook_url

BOT_A = str(uuid4())
BOT_B = str(uuid4())
BOT_BALE = str(uuid4())


class AsyncReadOnlyDb:
    """Adapt local synchronous SQLAlchemy reads to async service contracts."""

    def __init__(self, session: Session) -> None:
        """Retain only a disposable read-only test session."""
        self.session = session

    async def get(self, model, key):
        """Return a locally created row without network access."""
        return self.session.get(model, key)

    async def scalar(self, query):
        """Execute a local SELECT in the disposable test transaction."""
        return self.session.scalar(query)


@pytest.fixture
def db() -> Iterator[Session]:
    """Create separate logical bots and commerce identities in private memory."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    # Keep the chosen schema small: one store and three independent bots.
    Base.metadata.create_all(
        engine,
        tables=[
            ShopStaff.__table__,
            ShopStore.__table__,
            ShopBot.__table__,
            ShopIdentity.__table__,
            ShopShippingMethod.__table__,
            ShopCoupon.__table__,
            ShopCart.__table__,
            ShopInboundUpdate.__table__,
            ShopBotReceiver.__table__,
        ],
    )
    with Session(engine) as session:
        session.add(
            ShopStore(
                id=DEFAULT_STORE_ID,
                slug="default",
                name="Fixture Shop",
                state="active",
            )
        )
        for bot_id, slug, platform, provider_id in (
            (BOT_A, "tg-alpha", "telegram", 101),
            (BOT_B, "tg-beta", "telegram", 102),
            (BOT_BALE, "bale-alpha", "bale", 103),
        ):
            session.add(
                ShopBot(
                    id=bot_id,
                    store_id=DEFAULT_STORE_ID,
                    slug=slug,
                    name=slug,
                    platform=platform,
                    provider_bot_id=provider_id,
                    runtime_owner="registry",
                    status="active",
                    credential_version=1,
                    version=1,
                )
            )
        session.commit()
        yield session
    engine.dispose()


def test_same_numeric_user_has_independent_bot_accounts(db: Session) -> None:
    """Never merge equal IDs even for two bots on the same platform."""
    db.add_all(
        ShopIdentity(
            platform=platform, bot_id=bot_id,
            platform_user_id=321, username="fixture",
        )
        for bot_id, platform in (
            (BOT_A, "telegram"),
            (BOT_B, "telegram"),
            (BOT_BALE, "bale"),
        )
    )
    db.commit()
    rows = db.scalars(
        select(ShopIdentity).where(ShopIdentity.platform_user_id == 321)
    ).all()
    assert {row.bot_id for row in rows} == {BOT_A, BOT_B, BOT_BALE}

    # An additional identity under the same bot and user must fail.
    db.add(
        ShopIdentity(
            platform="telegram", bot_id=BOT_A, platform_user_id=321,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_same_numeric_user_has_independent_cart_states(db: Session) -> None:
    """Cart and waiting-input state may vary between matching user IDs."""
    db.add_all([
        ShopCart(
            platform="telegram", bot_id=BOT_A,
            platform_user_id=321, chat_id=321, awaiting_input="address",
        ),
        ShopCart(
            platform="telegram", bot_id=BOT_B,
            platform_user_id=321, chat_id=321, awaiting_input="coupon",
        ),
    ])
    db.commit()
    carts = db.scalars(select(ShopCart).order_by(ShopCart.bot_id)).all()
    assert len(carts) == 2
    assert {cart.awaiting_input for cart in carts} == {"address", "coupon"}
    assert carts[0].bot_id != carts[1].bot_id

    db.add(
        ShopCart(
            platform="telegram", bot_id=BOT_A,
            platform_user_id=321, chat_id=321,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_receipt_idempotency_survives_rotation_and_receiver_offsets(
    db: Session,
) -> None:
    """Update IDs and polling offsets belong to one bot, not one token."""
    secret = "A" * 43
    digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
    for bot_id in (BOT_A, BOT_B):
        db.add(
            ShopBotReceiver(
                bot_id=bot_id,
                binding_id=str(uuid4()),
                mode="polling",
                state="active",
                webhook_secret_ciphertext="encrypted-fixture-only",
                webhook_secret_digest=digest,
                credential_version=1,
                next_update_id=0,
            )
        )
        db.add(
            ShopInboundUpdate(
                bot_id=bot_id,
                platform="telegram",
                bot_fingerprint="F" * 64,
                update_id=987,
                status="processed",
            )
        )
    db.commit()
    assert db.scalar(select(ShopInboundUpdate).where(
        ShopInboundUpdate.bot_id == BOT_A,
        ShopInboundUpdate.update_id == 987,
    )) is not None

    # Updating A never changes B's durable polling offset.
    db.get(ShopBotReceiver, BOT_A).next_update_id = 988
    db.commit()
    assert db.get(ShopBotReceiver, BOT_B).next_update_id == 0

    # Rotating a token changes the fingerprint, but not the receipt owner.
    db.add(
        ShopInboundUpdate(
            bot_id=BOT_A,
            platform="telegram",
            bot_fingerprint="G" * 64,
            update_id=987,
            status="processing",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_bot_context_enforces_identity_and_paid_receipt_exception(
    db: Session,
) -> None:
    """Paused bots can settle past payments but cannot start new shopping."""
    reader = AsyncReadOnlyDb(db)
    verified = asyncio.run(
        resolve_bot_context(
            reader,
            authenticated_bot_id=BOT_A,
            authenticated_platform=Platform.TELEGRAM,
            authenticated_provider_bot_id=101,
        )
    )
    assert verified.owner_key(321) == (BOT_A, 321)
    assert verified.bot_id != BOT_B

    with pytest.raises(security.SecurityRejected) as error:
        asyncio.run(
            resolve_bot_context(
                reader,
                authenticated_bot_id=BOT_A,
                authenticated_platform=Platform.BALE,
            )
        )
    assert error.value.code == "bot_identity_mismatch"

    db.get(ShopBot, BOT_A).status = "paused"
    db.commit()
    with pytest.raises(security.SecurityRejected) as error:
        asyncio.run(
            resolve_bot_context(
                reader,
                authenticated_bot_id=BOT_A,
                authenticated_platform=Platform.TELEGRAM,
            )
        )
    assert error.value.code == "bot_not_active"

    prior_receipt = asyncio.run(
        resolve_bot_context(
            reader,
            authenticated_bot_id=BOT_A,
            authenticated_platform=Platform.TELEGRAM,
            allow_settlement=True,
        )
    )
    assert prior_receipt.status == "paused"


def test_receiver_snapshot_never_exposes_secret(db: Session) -> None:
    """Only operational metadata may leave the server-side receiver registry."""
    fake_ciphertext = "encrypted-secret-fixture"
    db.add(
        ShopBotReceiver(
            bot_id=BOT_A, binding_id=str(uuid4()),
            mode="webhook", state="staged",
            webhook_secret_ciphertext=fake_ciphertext,
            webhook_secret_digest="a" * 64,
            credential_version=1,
        )
    )
    db.commit()
    snapshot = asyncio.run(receiver_snapshot(AsyncReadOnlyDb(db), BOT_A))
    assert snapshot["configured"] is True
    assert snapshot["state"] == "staged"
    assert snapshot["mode"] == "webhook"
    assert "webhook_secret_ciphertext" not in snapshot
    assert "webhook_secret_digest" not in snapshot
    assert "binding_id" not in snapshot
    assert fake_ciphertext not in repr(snapshot)


def test_webhook_url_rejects_private_or_insecure_origin(monkeypatch) -> None:
    """Derive authenticated URLs only from approved public HTTPS origins."""
    binding_id = str(uuid4())
    secret = "Z" * 43
    monkeypatch.setenv("MULTIBOT_WEBHOOK_BASE_URL", "https://hooks.example.org")
    address = webhook_url(binding_id, secret)
    assert address == (
        f"https://hooks.example.org/webhooks/v2/{binding_id}/{secret}"
    )

    for forbidden in (
        "http://hooks.example.org", "https://127.0.0.1",
        "https://10.0.0.1", "https://169.254.169.254",
        "https://[::1]", "https://[fd00::1]",
    ):
        monkeypatch.setenv("MULTIBOT_WEBHOOK_BASE_URL", forbidden)
        with pytest.raises(security.SecurityRejected):
            webhook_url(binding_id, secret)

    monkeypatch.setenv("MULTIBOT_WEBHOOK_BASE_URL", "https://hooks.example.org")
    with pytest.raises(security.SecurityRejected):
        webhook_url(binding_id, "short")


def test_webhook_origin_override_is_scoped_to_one_binding(monkeypatch) -> None:
    """A tunnel for one receiver leaves the shared origin for other bots."""
    selected, other = str(uuid4()), str(uuid4())
    secret = "Z" * 43
    monkeypatch.setenv("MULTIBOT_WEBHOOK_BASE_URL", "https://hooks.example.org")
    monkeypatch.setenv("MULTIBOT_WEBHOOK_BINDING_ID", selected)
    monkeypatch.setenv("MULTIBOT_WEBHOOK_BINDING_BASE_URL", "https://bale.example.org")

    assert webhook_url(selected, secret) == (
        f"https://bale.example.org/webhooks/v2/{selected}/{secret}"
    )
    assert webhook_url(other, secret) == (
        f"https://hooks.example.org/webhooks/v2/{other}/{secret}"
    )
    monkeypatch.setenv("MULTIBOT_WEBHOOK_BINDING_BASE_URL", "https://127.0.0.1")
    with pytest.raises(security.SecurityRejected):
        webhook_url(selected, secret)


def test_registry_broadcast_requires_explicit_deployment_permission(monkeypatch) -> None:
    """An unapproved Registry broadcast cannot claim recipients or contact providers."""
    monkeypatch.setattr(config, "SHOP_CAMPAIGN_DISPATCH_ENABLED", True)
    monkeypatch.setattr(config, "SHOP_BROADCAST_WORKER_ENABLED", True)
    monkeypatch.setattr(config, "SHOP_BROADCAST_REGISTRY_ENABLED", False, raising=False)
    campaign = ShopCampaign(
        id=101,
        bot_id=BOT_A,
        title="Offline Contract",
        text="This test does not send messages.",
        audience="telegram",
        status="approved",
    )

    class FakeDb:
        """Stop the operation before any delivery or provider access."""

        async def scalar(self, _query):
            """Return the registry campaign to the policy gate."""
            return campaign

    with pytest.raises(CampaignRejected, match="هنوز فعال نشده"):
        # The gate must precede any recipient lookup or transport creation.
        asyncio.run(
            BroadcastControl.start(
                FakeDb(), campaign_id=101, actor="offline-test",
            )
        )
