"""Offline merchant-credit and referral tests for both Bot API identities.

Use isolated SQLite only. These tests never read Bale wallet balances,
run a Telegram crypto operation or contact a real payment provider.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from channels.contracts import Platform
from models.base import Base
from models.shop_content import Product, ShopCategory, ShopIdentity, ShopOrder
from models.shop_checkout import ShopCoupon, ShopOrderLine
from models.shop_engagement import (
    ShopReferralAttribution,
    ShopReferralPolicy,
    ShopReferralProfile,
    ShopReferralReward,
    ShopWalletAccount,
    ShopWalletEntry,
)
from models.shop_payment import ShopPaymentAttempt
from models.shop_channel_features import ShopChannelFeature
from models.shop_payment_rail import ShopPaymentRail
from services.shop_referrals import ShopReferralService
from services.shop_wallet import ShopWalletService, StoreCreditRejected


class AsyncNested:
    """Use SQLAlchemy's synchronous nested transaction with async with."""

    def __init__(self, transaction) -> None:
        """Keep the disposable SAVEPOINT for the context manager."""
        self.transaction = transaction

    async def __aenter__(self):
        """Open the test SAVEPOINT."""
        self.transaction.__enter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Commit or roll back the test SAVEPOINT."""
        return self.transaction.__exit__(exc_type, exc, tb)


class AsyncDB:
    """Adapt synchronous SQLite to the async methods used by shop services."""

    def __init__(self, session: Session) -> None:
        """Hold a single transaction-scoped database session."""
        self.session = session

    async def scalar(self, statement):
        """Return one ORM scalar."""
        return self.session.scalar(statement)

    async def scalars(self, statement):
        """Read scalar results from the isolated database."""
        return self.session.scalars(statement)

    async def execute(self, statement):
        """Execute a SQLAlchemy statement."""
        return self.session.execute(statement)

    async def get(self, model, key):
        """Load a row by primary key."""
        return self.session.get(model, key)

    async def flush(self):
        """Synchronize inserted rows with SQLite."""
        self.session.flush()

    async def commit(self):
        """Commit the in-memory transaction."""
        self.session.commit()

    def add(self, record):
        """Add a record to the current transaction."""
        self.session.add(record)

    def begin_nested(self):
        """Return an awaitable context for a synchronous SAVEPOINT."""
        return AsyncNested(self.session.begin_nested())


@pytest.fixture
def db():
    """Provision only required, isolated test tables in dependency order."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ShopChannelFeature.__table__, ShopPaymentRail.__table__,
            ShopCategory.__table__,
            Product.__table__,
            ShopIdentity.__table__,
            ShopOrder.__table__,
            ShopCoupon.__table__,
            ShopOrderLine.__table__,
            ShopPaymentAttempt.__table__,
            ShopWalletAccount.__table__,
            ShopWalletEntry.__table__,
            ShopReferralProfile.__table__,
            ShopReferralAttribution.__table__,
            ShopReferralPolicy.__table__,
            ShopReferralReward.__table__,
        ],
    )
    with Session(engine) as session:
        yield AsyncDB(session)
    engine.dispose()


@pytest.mark.asyncio
async def test_wallet_idempotency_and_platform_isolation(db):
    """Never debit another platform's user with the same numeric ID."""
    telegram = ShopIdentity(platform="telegram", platform_user_id=101)
    bale = ShopIdentity(platform="bale", platform_user_id=101)
    db.session.add_all([telegram, bale])
    db.session.commit()

    first, changed = await ShopWalletService.apply(
        db, identity_id=telegram.id, delta_irr=500,
        operation_key="case-credit-telegram-101",
        reason="Test credit adjustment", actor="staff:1",
    )
    await db.commit()
    repeated, changed_again = await ShopWalletService.apply(
        db, identity_id=telegram.id, delta_irr=500,
        operation_key="case-credit-telegram-101",
        reason="Test credit adjustment", actor="staff:1",
    )
    assert changed is True
    assert changed_again is False
    assert first.id == repeated.id
    assert await ShopWalletService.balance(db, Platform.TELEGRAM, 101) == 500
    assert await ShopWalletService.balance(db, Platform.BALE, 101) == 0
    assert len(db.session.scalars(select(ShopWalletEntry)).all()) == 1

    with pytest.raises(StoreCreditRejected):
        await ShopWalletService.apply(
            db, identity_id=bale.id, delta_irr=500,
            operation_key="case-credit-telegram-101",
            reason="Wrong beneficiary", actor="staff:1",
        )
    with pytest.raises(StoreCreditRejected):
        await ShopWalletService.apply(
            db, identity_id=telegram.id, delta_irr=-501,
            operation_key="case-debit-telegram-101",
            reason="Insufficient balance", actor="staff:1",
        )


@pytest.mark.asyncio
async def test_first_purchase_referral_reward_requires_provider_receipt(db):
    """Award a sponsor only once after a matching verified IRR payment."""
    inviter = ShopIdentity(platform="bale", platform_user_id=501)
    referee = ShopIdentity(platform="bale", platform_user_id=502)
    product = Product(
        sku="REWARD", name="محصول تست", description="توضیح",
        price=1000, stock_quantity=5, is_published=True,
    )
    db.session.add_all([inviter, referee, product])
    db.session.add(
        ShopReferralPolicy(
            id=1, is_enabled=True, percent=10,
            min_order_irr=0, max_bonus_irr=200,
        )
    )
    db.session.commit()

    code = await ShopReferralService.code(db, Platform.BALE, 501)
    assert await ShopReferralService.claim(
        db, platform=Platform.BALE, user_id=502, code=code
    ) == "✅ کد معرفی برای اولین خرید شما ثبت شد."

    payload = uuid4().hex
    order = ShopOrder(
        platform="bale",
        platform_user_id=502,
        chat_id=502,
        product_id=product.id,
        product_name_snapshot=product.name,
        quantity=1,
        unit_price_irr=1000,
        total_irr=1000,
        provider="bale_wallet",
        status="paid",
        invoice_payload=payload,
        payment_currency="IRR",
        payment_amount=1000,
        paid_at=datetime.now(timezone.utc),
    )
    db.add(order)
    await db.commit()

    # An order's mutable paid status is not sufficient evidence.
    assert await ShopReferralService.award_for_paid_order(db, order.id) == 0
    assert await ShopWalletService.balance(db, Platform.BALE, 501) == 0

    db.add(
        ShopPaymentAttempt(
            order_id=order.id, platform="bale", provider="bale_wallet",
            currency="IRR", amount=1000, payload=payload,
            status="paid",
        )
    )
    await db.commit()
    assert await ShopReferralService.award_for_paid_order(db, order.id) == 100
    assert await ShopReferralService.award_for_paid_order(db, order.id) == 0
    assert await ShopWalletService.balance(db, Platform.BALE, 501) == 100
    rewards = db.session.scalars(select(ShopReferralReward)).all()
    assert len(rewards) == 1
    assert rewards[0].bonus_irr == 100
