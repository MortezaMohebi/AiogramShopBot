"""Offline parity tests for store credit, referrals and consented campaigns.

No live Bot API, PostgreSQL, merchant charge or background job is executed.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from channels.contracts import Platform
from dashboard.permissions import secure_model_view
from models.base import Base
from models.shop_checkout import ShopCoupon, ShopOrderLine
from models.shop_content import Product, ShopCategory, ShopIdentity, ShopOrder
from models.shop_engagement import (
    ShopCampaign, ShopCampaignDelivery,
    ShopReferralAttribution, ShopReferralPolicy, ShopReferralProfile,
    ShopReferralReward, ShopWalletAccount, ShopWalletEntry,
)
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
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
    tables = [
        ShopCategory.__table__, Product.__table__,
        ShopIdentity.__table__, ShopCoupon.__table__,
        ShopOrder.__table__, ShopOrderLine.__table__,
        ShopPaymentAttempt.__table__, ShopRefundCase.__table__,
        ShopWalletAccount.__table__, ShopWalletEntry.__table__,
        ShopReferralProfile.__table__, ShopReferralAttribution.__table__,
        ShopReferralPolicy.__table__, ShopReferralReward.__table__,
        ShopCampaign.__table__, ShopCampaignDelivery.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine, expire_on_commit=False) as session:
        yield OfflineDB(session)
    engine.dispose()


def identity(db, platform, user_id, consent=False, blocked=False):
    """Seed a platform-scoped account without implicit marketing consent."""
    owner = ShopIdentity(
        platform=platform.value,
        platform_user_id=user_id,
        allow_announcements=consent,
        is_blocked=blocked,
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
        platform=platform.value, platform_user_id=user_id,
        chat_id=user_id, product_id=product.id,
        product_name_snapshot=product.name,
        quantity=1, unit_price_irr=1000, total_irr=1000,
        subtotal_irr=1000, discount_irr=0, shipping_irr=0,
        status=status,
        provider="manual_review",
        invoice_payload=uuid4().hex,
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
    assert await ShopWalletService.balance(db, Platform.TELEGRAM, 101) == 4000
    assert await ShopWalletService.balance(db, Platform.BALE, 101) == 0
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
        db, platform=Platform.BALE, user_id=202, order_id=order.id
    )
    assert changed and paid.status == "paid"
    assert product.stock_quantity == 4
    assert await ShopWalletService.balance(db, Platform.BALE, 202) == 2000
    duplicate, changed = await ShopWalletService.pay_order(
        db, platform=Platform.BALE, user_id=202, order_id=order.id
    )
    assert duplicate.id == paid.id and not changed
    assert product.stock_quantity == 4

    case = await ShopRefundService.request(
        db, platform=Platform.BALE, payer_id=202,
        order_id=order.id, reason="درخواست برگشت اعتبار",
    )
    refunded = await ShopWalletService.refund_order(
        db, case_id=case.id, actor="staff:1"
    )
    assert refunded.status == "confirmed"
    assert order.status == "refunded"
    assert await ShopWalletService.balance(db, Platform.BALE, 202) == 3000
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
    code = await ShopReferralService.code(db, Platform.TELEGRAM, 301)
    assert code.startswith("R-")
    response = await ShopReferralService.claim(
        db, platform=Platform.TELEGRAM, user_id=302, code=code
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
        )
    )
    db.session.commit()
    assert await ShopReferralService.award_for_paid_order(db, order.id) == 100
    assert await ShopReferralService.award_for_paid_order(db, order.id) == 0
    assert await ShopWalletService.balance(db, Platform.TELEGRAM, 301) == 100
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
    code = await ShopReferralService.code(db, Platform.TELEGRAM, 401)
    with pytest.raises(ReferralRejected):
        await ShopReferralService.claim(
            db, platform=Platform.BALE, user_id=401, code=code
        )


@pytest.mark.asyncio
async def test_consent_campaign_sends_only_to_opted_in_accounts(db):
    """Both channels use the same opt-in campaign outbox and no duplicate send."""
    identity(db, Platform.TELEGRAM, 501, consent=True)
    identity(db, Platform.BALE, 502, consent=True)
    identity(db, Platform.TELEGRAM, 503, consent=False)
    identity(db, Platform.BALE, 504, consent=True, blocked=True)
    campaign = ShopCampaign(
        title="اطلاعیه آزمایشی", text="متن تست بدون اطلاعات واقعی",
        audience="all", status="draft",
    )
    db.add(campaign)
    db.session.commit()

    assert await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:1"
    ) == 2
    calls = []

    async def send(platform, user_id, text):
        """Store calls in memory instead of contacting a Bot API."""
        calls.append((platform, user_id, text))

    sent, skipped = await ShopCampaignService.dispatch_batch(
        db, campaign_id=campaign.id, send=send
    )
    assert sent == 2 and skipped == 0
    assert {item[0] for item in calls} == {
        Platform.TELEGRAM, Platform.BALE
    }
    assert len(calls) == 2
    assert campaign.status == "completed"
    with pytest.raises(CampaignRejected):
        await ShopCampaignService.dispatch_batch(
            db, campaign_id=campaign.id, send=send
        )


@pytest.mark.asyncio
async def test_unsubscribed_recipient_is_skipped_after_campaign_approval(db):
    """An opt-out after approval must prevent an already-queued delivery."""
    person = identity(db, Platform.TELEGRAM, 601, consent=True)
    campaign = ShopCampaign(
        title="اطلاعیه", text="متن اطلاعیه تست", audience="telegram"
    )
    db.add(campaign)
    db.session.commit()
    await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:1"
    )
    person.allow_announcements = False
    db.session.commit()
    calls = []

    async def send(platform, user_id, text):
        """Record any unexpected marketing dispatch."""
        calls.append(user_id)

    sent, skipped = await ShopCampaignService.dispatch_batch(
        db, campaign_id=campaign.id, send=send
    )
    assert sent == 0 and skipped == 1
    assert calls == []


def test_role_access_is_default_deny_for_finance_views():
    """An authenticated content editor cannot change merchant credit."""
    class FinanceView:
        category = "مالی"

    secure_model_view(FinanceView)
    viewer = SimpleNamespace(
        state=SimpleNamespace(shop_role="content")
    )
    accountant = SimpleNamespace(
        state=SimpleNamespace(shop_role="finance")
    )
    assert not FinanceView().is_accessible(viewer)
    assert FinanceView().is_accessible(accountant)


@pytest.mark.asyncio
async def test_unknown_campaign_delivery_is_not_retried_blindly(db):
    """A timeout must never create a second unverified marketing delivery."""
    identity(db, Platform.TELEGRAM, 701, consent=True)
    campaign = ShopCampaign(
        title="آزمون خطای ارتباط", text="متن ارسال تست", audience="telegram"
    )
    db.add(campaign)
    db.session.commit()
    await ShopCampaignService.approve(
        db, campaign_id=campaign.id, approver="staff:1"
    )
    attempts = []

    async def uncertain_delivery(platform, user_id, text):
        """Simulate a timeout after a request might have been accepted."""
        attempts.append((platform, user_id))
        raise TimeoutError("Ambiguous delivery")

    sent, skipped = await ShopCampaignService.dispatch_batch(
        db, campaign_id=campaign.id, send=uncertain_delivery
    )
    assert sent == 0 and skipped == 0
    delivery = db.session.scalar(select(ShopCampaignDelivery))
    assert delivery.status == "unknown"
    assert campaign.status == "sending"
    # A second explicit batch only searches for queued deliveries, and
    # does not replay unknown/sending records.
    await ShopCampaignService.dispatch_batch(
        db, campaign_id=campaign.id, send=uncertain_delivery
    )
    assert len(attempts) == 1


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
    assert await ShopWalletService.balance(db, Platform.BALE, 801) == 0
