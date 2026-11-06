"""Offline parity tests for store credit, referrals and consented campaigns.

No live Bot API, PostgreSQL, merchant charge or background job is executed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from tests.schema_support import (
    create_shop_schema, seed_registry, TEST_BOT_IDS, test_bot_context,
    allow_test_catalog,
)

from contextlib import asynccontextmanager
from uuid import uuid4
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from channels.contracts import Platform
from models.base import Base
from models.shop_checkout import ShopCoupon, ShopOrderLine
from models.shop_content import Product, ShopCategory, ShopIdentity, ShopOrder
from models.shop_engagement import (
    ShopCampaign, ShopCampaignDelivery, ShopCampaignMedia,
    ShopReferralAttribution, ShopReferralPolicy, ShopReferralProfile,
    ShopReferralReward, ShopWalletAccount, ShopWalletEntry,
)
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
from models.shop_bot_catalog_acl import ShopBotProductRule, ShopBotCategoryRule
from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import (
    DEFAULT_STORE_ID, ShopBot, ShopStore,
)
from models.shop_staff import ShopStaff
from services.shop_campaigns import CampaignRejected, ShopCampaignService
from services.shop_referrals import ReferralRejected, ShopReferralService
from services.shop_refunds import ShopRefundService
from services.shop_wallet import ShopWalletService, StoreCreditRejected


class OfflineDB:
    """Wrap a disposable synchronous SQLite Session for async service tests."""

    def __init__(self, session: Session):
        """Keep this test's own database transaction."""
        self.session = session

    async def scalar(self, statement):
        """Execute a scalar query without external I/O."""
        return self.session.scalar(statement)

    async def scalars(self, statement):
        """Return ORM scalar results for bot-scoped product entitlements."""
        return self.session.scalars(statement)

    async def execute(self, statement):
        """Execute SQLAlchemy ORM/Core statements."""
        return self.session.execute(statement)

    async def get(self, model, key):
        """Load one model by primary key."""
        return self.session.get(model, key)

    async def commit(self):
        """Commit only the temporary in-memory transaction."""
        self.session.commit()

    async def rollback(self):
        """Roll back the temporary test transaction."""
        self.session.rollback()

    async def flush(self):
        """Flush pending SQLAlchemy objects."""
        self.session.flush()

    async def refresh(self, obj):
        """Reload one ORM record from this session."""
        self.session.refresh(obj)

    def add(self, obj):
        """Add a record to the temporary database."""
        self.session.add(obj)

    @asynccontextmanager
    async def begin_nested(self):
        """Expose a savepoint for first-wallet uniqueness races."""
        with self.session.begin_nested():
            yield


@pytest.fixture
def db():
    """Create only the related shop tables in isolated SQLite memory."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_shop_schema(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(ShopStore(
            id=DEFAULT_STORE_ID, slug="default",
            name="Existing shop", state="active",
        ))
        seed_registry(session)
        session.commit()
        yield OfflineDB(session)
    engine.dispose()


def identity(db, platform, user_id, consent=False, blocked=False):
    """Seed a platform-scoped account without implicit marketing consent."""
    owner = ShopIdentity(
        platform=platform.value,
        platform_user_id=user_id,
        allow_announcements=consent,
        is_blocked=blocked,
        bot_id=TEST_BOT_IDS[platform.value],
    )
    db.add(owner)
    db.session.flush()
    return owner


def product_and_order(db, platform, user_id, *, status="approved_unpaid"):
    """Create an approved order with an immutable line and stock."""
    product = Product(
        sku="SKU-" + uuid4().hex[:8],
        name="محصول نمونه", description="توضیح",
        price=1000, stock_quantity=5,
        requires_shipping=False, is_published=True,
    )
    db.add(product)
    db.session.flush()
    order = ShopOrder(
        platform=platform.value,
        platform_user_id=user_id,
        chat_id=user_id,
        product_id=product.id,
        product_name_snapshot=product.name,
        quantity=1,
        unit_price_irr=1000,
        total_irr=1000,
        subtotal_irr=1000,
        discount_irr=0,
        shipping_irr=0,
        terms_version_snapshot="fixture-v1",
        terms_accepted_at=datetime.now(timezone.utc),
        status=status,
        provider="manual_review",
        invoice_payload=uuid4().hex,
        bot_id=TEST_BOT_IDS[platform.value],
    )
    db.add(order)
    db.session.flush()
    db.add(
        ShopOrderLine(
            order_id=order.id, product_id=product.id,
            product_name_snapshot=product.name,
            sku_snapshot=product.sku,
            unit_price_irr=1000, quantity=1, total_irr=1000,
        )
    )
    allow_test_catalog(db.session)
    db.session.commit()
    return product, order


@pytest.mark.asyncio
async def test_merchant_wallet_is_scoped_and_idempotent(db):
    """Same numeric Telegram/Bale IDs must never mix fiat balances."""
    telegram_user = identity(db, Platform.TELEGRAM, 101)
    identity(db, Platform.BALE, 101)
    db.session.commit()

    first, changed = await ShopWalletService.apply(
        db, identity_id=telegram_user.id,
        delta_irr=4000,
        operation_key="unit-test-credit:unique-1",
        reason="Explicit test-only grant",
        actor="staff:1",
    )
    await db.commit()
    assert changed is True
    again, changed = await ShopWalletService.apply(
        db, identity_id=telegram_user.id,
        delta_irr=4000,
        operation_key="unit-test-credit:unique-1",
        reason="Explicit test-only grant",
        actor="staff:1",
    )
    assert not changed and again.id == first.id
    assert (
        await ShopWalletService.balance(
            db, Platform.TELEGRAM, 101, bot_id=TEST_BOT_IDS[(Platform.TELEGRAM).value]
        )
        == 4000
    )
    assert (
        await ShopWalletService.balance(
            db, Platform.BALE, 101, bot_id=TEST_BOT_IDS[(Platform.BALE).value]
        )
        == 0
    )
    with pytest.raises(StoreCreditRejected):
        await ShopWalletService.apply(
            db, identity_id=telegram_user.id,
            delta_irr=-9000, operation_key="unit-test-debit:unique-2",
            reason="Exceeds merchant balance", actor="staff:1",
        )


@pytest.mark.asyncio
async def test_store_credit_order_and_refund_do_not_restock(db):
    """One purchase uses one balance debit; refund reverses the wallet only."""
    user = identity(db, Platform.BALE, 202)
    db.session.commit()
    product, order = product_and_order(db, Platform.BALE, 202)
    await ShopWalletService.apply(
        db, identity_id=user.id,
        delta_irr=3000, operation_key="test-wallet-seed:202",
        reason="Test-only existing credit", actor="staff:1",
    )
    await db.commit()
    paid, changed = await ShopWalletService.pay_order(
        db,
        platform=Platform.BALE,
        user_id=202,
        order_id=order.id,
        bot_id=TEST_BOT_IDS[(Platform.BALE).value],
    )
    assert changed and paid.status == "paid"
    assert product.stock_quantity == 4
    assert (
        await ShopWalletService.balance(
            db, Platform.BALE, 202, bot_id=TEST_BOT_IDS[(Platform.BALE).value]
        )
        == 2000
    )
    duplicate, changed = await ShopWalletService.pay_order(
        db,
        platform=Platform.BALE,
        user_id=202,
        order_id=order.id,
        bot_id=TEST_BOT_IDS[(Platform.BALE).value],
    )
    assert duplicate.id == paid.id and not changed
    assert product.stock_quantity == 4

    case = await ShopRefundService.request(
        db,
        platform=Platform.BALE,
        payer_id=202,
        order_id=order.id,
        reason="درخواست برگشت اعتبار",
        bot_id=TEST_BOT_IDS[(Platform.BALE).value],
    )
    refunded = await ShopWalletService.refund_order(
        db, case_id=case.id, actor="staff:1"
    )
    assert refunded.status == "confirmed"
    assert order.status == "refunded"
    assert (
        await ShopWalletService.balance(
            db, Platform.BALE, 202, bot_id=TEST_BOT_IDS[(Platform.BALE).value]
        )
        == 3000
    )
    assert product.stock_quantity == 4
    assert len(db.session.scalars(select(ShopWalletEntry)).all()) == 3


@pytest.mark.asyncio
async def test_referral_award_requires_first_verified_irr_purchase(db):
    """Merchant-funded reward must not be granted from Stars or draft carts."""
    sponsor = identity(db, Platform.TELEGRAM, 301)
    identity(db, Platform.TELEGRAM, 302)
    db.add(
        ShopReferralPolicy(
            id=1, is_enabled=True, percent=10,
            min_order_irr=500, max_bonus_irr=300,
        )
    )
    db.session.commit()
    code = await ShopReferralService.code(
        db, Platform.TELEGRAM, 301, bot_id=TEST_BOT_IDS[(Platform.TELEGRAM).value]
    )
    assert code.startswith("R-")
    response = await ShopReferralService.claim(
        db,
        platform=Platform.TELEGRAM,
        user_id=302,
        code=code,
        bot_id=TEST_BOT_IDS[(Platform.TELEGRAM).value],
    )
    assert "ثبت شد" in response

    _, order = product_and_order(db, Platform.TELEGRAM, 302, status="paid")
    order.provider = "telegram_fiat"
    order.payment_currency = "IRR"
    db.add(
        ShopPaymentAttempt(
            order_id=order.id,
            platform="telegram",
            provider="telegram_fiat",
            currency="IRR",
            amount=1000,
            payload=order.invoice_payload,
            status="paid",
            bot_id=TEST_BOT_IDS["telegram"],
        )
    )
    db.session.commit()
    assert await ShopReferralService.award_for_paid_order(db, order.id) == 100
    assert await ShopReferralService.award_for_paid_order(db, order.id) == 0
    assert (
        await ShopWalletService.balance(
            db, Platform.TELEGRAM, 301, bot_id=TEST_BOT_IDS[(Platform.TELEGRAM).value]
        )
        == 100
    )
    assert len(db.session.scalars(select(ShopReferralReward)).all()) == 1


@pytest.mark.asyncio
async def test_referral_rejects_cross_platform_self_invitation(db):
    """Do not accept invitations from an unlinked alternate app identity."""
    identity(db, Platform.TELEGRAM, 401)
    identity(db, Platform.BALE, 401)
    db.add(
        ShopReferralPolicy(
            id=1, is_enabled=True, percent=10,
            min_order_irr=0, max_bonus_irr=100,
        )
    )
    db.session.commit()
    code = await ShopReferralService.code(
        db, Platform.TELEGRAM, 401, bot_id=TEST_BOT_IDS[(Platform.TELEGRAM).value]
    )
    with pytest.raises(ReferralRejected):
        await ShopReferralService.claim(
            db,
            platform=Platform.BALE,
            user_id=401,
            code=code,
            bot_id=TEST_BOT_IDS[(Platform.BALE).value],
        )


@pytest.mark.asyncio
async def test_consent_campaign_snapshots_only_opted_in_accounts(db):
    """Approval captures consenting users without sending any message."""
    identity(db, Platform.TELEGRAM, 501, consent=True)
    identity(db, Platform.BALE, 502, consent=True)
    identity(db, Platform.TELEGRAM, 503, consent=False)
    identity(db, Platform.BALE, 504, consent=True, blocked=True)
    campaigns = [
        ShopCampaign(
            title="اطلاعیه آزمایشی", text="متن تست",
            audience=platform, status="draft", bot_id=bot_id,
        )
        for platform, bot_id in TEST_BOT_IDS.items()
    ]
    db.session.add_all(campaigns)
    db.session.commit()
    counts = [
        await ShopCampaignService.approve(
            db, campaign_id=campaign.id, approver="staff:1",
        )
        for campaign in campaigns
    ]
    assert counts == [1, 1]
    assert all(campaign.status == "approved" for campaign in campaigns)
    assert len(db.session.scalars(select(ShopCampaignDelivery)).all()) == 2


@pytest.mark.asyncio
async def test_unsubscribe_after_approval_remains_effective(db):
    """An already queued recipient still has the right to unsubscribe."""
    person = identity(db, Platform.TELEGRAM, 601, consent=True)
    campaign = ShopCampaign(
        title="اطلاعیه",
        text="متن",
        audience="telegram",
        bot_id=TEST_BOT_IDS["telegram"],
        status="draft",
    )
    db.add(campaign)
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


@pytest.mark.asyncio
async def test_marketing_snapshot_is_approved_only_once(db):
    """Approval cannot recreate recipients on a repeated request."""
    identity(db, Platform.TELEGRAM, 701, consent=True)
    campaign = ShopCampaign(
        title="یکبار",
        text="متن",
        audience="telegram",
        bot_id=TEST_BOT_IDS["telegram"],
        status="draft",
    )
    db.add(campaign)
    db.session.commit()
    await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:1"
    )
    with pytest.raises(CampaignRejected):
        await ShopCampaignService.approve(
            db, campaign_id=campaign.id, approver="staff:1"
        )
    assert len(db.session.scalars(select(ShopCampaignDelivery)).all()) == 1


@pytest.mark.asyncio
async def test_referral_policy_off_disables_new_codes(db):
    """Marketing must not silently promise payouts without finance approval."""
    identity(db, Platform.BALE, 801)
    db.add(
        ShopReferralPolicy(
            id=1, is_enabled=False, percent=20,
            min_order_irr=0, max_bonus_irr=1000,
        )
    )
    db.session.commit()
    _, order = product_and_order(db, Platform.BALE, 801, status="paid")
    order.provider = "bale_wallet"
    order.payment_currency = "IRR"
    db.session.commit()
    assert await ShopReferralService.award_for_paid_order(db, order.id) == 0
    assert (
        await ShopWalletService.balance(
            db, Platform.BALE, 801, bot_id=TEST_BOT_IDS[(Platform.BALE).value]
        )
        == 0
    )
