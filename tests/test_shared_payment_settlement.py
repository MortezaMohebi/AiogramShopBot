"""Offline settlement tests for Telegram, Stars and Bale across two products.

These tests do not start a bot, make a payment, contact a provider, or migrate
a live database. Real provider callbacks are covered only by later live QA.
"""

from __future__ import annotations

from tests.schema_support import create_shop_schema, seed_test_units

from contextlib import asynccontextmanager
from uuid import uuid4
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from models.shop_digital_delivery import ShopDigitalLicense
from services.shop_digital_crypto import seal_license

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from channels.contracts import Platform
from models.base import Base
from models.shop_checkout import ShopCoupon, ShopOrderLine
from models.shop_content import Product, ShopCategory, ShopOrder
from models.shop_bot_catalog_acl import ShopBotProductRule, ShopBotCategoryRule
from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import (
    DEFAULT_STORE_ID, LEGACY_BOT_IDS, ShopBot, ShopStore,
)
from models.shop_staff import ShopStaff
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
from services.shop_payments import PaymentRejected, ShopPaymentService
from services.shop_refunds import ShopRefundService


class OfflineDB:
    """Run real SQLAlchemy queries in an isolated in-memory SQLite database."""

    def __init__(self, session: Session) -> None:
        """Hold one test-scoped SQLAlchemy session."""
        self.session = session

    async def execute(self, statement):
        """Execute an ORM statement with no network access."""
        return self.session.execute(statement)

    async def scalar(self, statement):
        """Read one scalar value."""
        return self.session.scalar(statement)

    async def scalars(self, statement):
        """Read ACL product-ID results with the test SQLite connection."""
        return self.session.scalars(statement)

    async def get(self, model, key):
        """Load a model by its primary key."""
        return self.session.get(model, key)

    async def commit(self):
        """Commit the test transaction."""
        self.session.commit()

    async def flush(self):
        """Flush pending rows."""
        self.session.flush()

    async def refresh(self, obj):
        """Reload a record after an invoice is committed."""
        self.session.refresh(obj)

    def add(self, obj):
        """Stage a new record."""
        self.session.add(obj)

    @asynccontextmanager
    async def begin_nested(self):
        """Reserve digital supply within a real isolated SQLAlchemy savepoint."""
        with self.session.begin_nested():
            yield


@pytest.fixture
def db(monkeypatch):
    """Create only payment-related tables, leaving all data disposable."""
    monkeypatch.setenv("SHOP_SECURITY_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_shop_schema(engine)
    with Session(engine) as session:
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
        session.commit()
        seed_test_units(session)
        yield OfflineDB(session)
    engine.dispose()


def make_order(db, platform: Platform, *, digital=False, coupon=False):
    """Create one reviewed order and its immutable product-line snapshot."""
    product = Product(
        sku=f"TEST-{uuid4().hex[:12]}",
        name="کالای نمونه",
        description="توضیح نمونه",
        price=1000,
        stock_quantity=3,
        product_type="digital" if digital else "physical",
        requires_shipping=not digital,
        price_stars=25 if digital else None,
        is_published=True,
    )
    db.add(product)
    db.session.flush()
    discount = None
    if coupon:
        discount = ShopCoupon(
            code=f"C{uuid4().hex[:7]}".upper(),
            discount_type="percent",
            value=10,
            minimum_subtotal_irr=0,
            used_count=0,
            is_active=True,
        )
        db.add(discount)
        db.session.flush()
    stars = digital and platform == Platform.TELEGRAM
    if digital:
        product.digital_delivery_mode = "license"
        for index in range(3):
            ciphertext, fingerprint = seal_license(
                store_id=product.store_id, product_id=product.id,
                code=f"FIXTURE-{product.id}-LICENSE-{index}",
            )
            db.add(ShopDigitalLicense(
                id=str(uuid4()), store_id=product.store_id, product_id=product.id,
                ciphertext=ciphertext, code_fingerprint=fingerprint,
            ))
    subtotal = 0 if stars else 2000
    discounted = 200 if discount is not None else 0
    shipping = 0 if digital else 500
    order = ShopOrder(
        platform=platform.value,
        platform_user_id=101,
        chat_id=101,
        product_id=product.id,
        product_name_snapshot=product.name,
        quantity=2,
        unit_price_irr=0 if stars else 1000,
        total_stars_snapshot=50 if stars else None,
        terms_version_snapshot="fixture-v1",
        terms_accepted_at=datetime.now(timezone.utc),
        total_irr=subtotal - discounted + shipping,
        provider="manual_review",
        status="approved_unpaid",
        invoice_payload=uuid4().hex,
        subtotal_irr=subtotal,
        discount_irr=discounted,
        shipping_irr=shipping,
        shipping_address=None if digital else "تهران، خیابان نمونه پلاک ۱۲",
        shipping_method_snapshot=None if digital else "پست",
        coupon_id=discount.id if discount else None,
        coupon_code_snapshot=discount.code if discount else None,
    )
    db.add(order)
    db.session.flush()
    db.add(
        ShopOrderLine(
            order_id=order.id,
            product_id=product.id,
            product_name_snapshot=product.name,
            sku_snapshot=product.sku,
            unit_price_irr=0 if stars else 1000,
            unit_price_stars_snapshot=25 if stars else None,
            quantity=2,
            total_irr=subtotal,
        )
    )
    db.session.commit()
    return order, product, discount


async def begin(db, platform: Platform, order):
    """Construct a provider invoice plan with fixed test-only switches."""
    return await ShopPaymentService.begin(
        db,
        platform=platform,
        platform_user_id=101,
        order_id=order.id,
        bale_enabled=True,
        telegram_fiat_enabled=True,
        telegram_stars_enabled=True,
        telegram_minor_multiplier=100,
    )


@pytest.mark.asyncio
async def test_bale_rial_payment_and_double_receipt_are_idempotent(db):
    """One paid invoice decrements each product and coupon counter once."""
    order, product, coupon = make_order(db, Platform.BALE, coupon=True)
    plan = await begin(db, Platform.BALE, order)
    assert plan.currency == "IRR"
    assert plan.amount == 2300
    assert plan.provider == "bale_wallet"
    await ShopPaymentService.mark_invoice_dispatch(db, plan.attempt_id, sent=True)
    ok, reason = await ShopPaymentService.precheckout(
        db,
        platform=Platform.BALE,
        payer_id=101,
        payload=plan.payload,
        currency="IRR",
        amount=plan.amount,
    )
    assert ok and reason is None
    assert not (await ShopPaymentService.precheckout(
        db, platform=Platform.BALE, payer_id=102,
        payload=plan.payload, currency="IRR", amount=plan.amount,
    ))[0]

    attrs = {
        "platform": Platform.BALE,
        "payer_id": 101,
        "chat_id": 101,
        "payload": plan.payload,
        "currency": plan.currency,
        "amount": plan.amount,
        "charge_id": "tx-native-101",
        "provider_charge_id": "bale-ref-001",
    }
    stored, changed = await ShopPaymentService.settle(db, **attrs)
    assert changed is True
    assert stored.status == "paid"
    assert product.stock_quantity == 1
    assert coupon.used_count == 1

    repeated, changed = await ShopPaymentService.settle(db, **attrs)
    assert repeated.id == stored.id and changed is False
    assert product.stock_quantity == 1
    assert coupon.used_count == 1
    with pytest.raises(PaymentRejected):
        await ShopPaymentService.settle(
            db, **{**attrs, "charge_id": "different-charge"}
        )


@pytest.mark.asyncio
async def test_unavailable_inventory_creates_refund_review_not_partial_sale(db):
    """Real money is accounted for even when stock disappears after checkout."""
    order, product, coupon = make_order(db, Platform.BALE, coupon=True)
    plan = await begin(db, Platform.BALE, order)
    product.stock_quantity = 1
    db.session.commit()
    stored, changed = await ShopPaymentService.settle(
        db,
        platform=Platform.BALE, payer_id=101, chat_id=101,
        payload=plan.payload, currency="IRR", amount=plan.amount,
        charge_id="tx-paid-but-out-of-stock",
        provider_charge_id="reference",
    )
    assert changed and stored.status == "paid_unfulfilled"
    assert product.stock_quantity == 1
    assert coupon.used_count == 0
    case = db.session.scalar(select(ShopRefundCase))
    assert case is not None and case.status == "requested"


@pytest.mark.asyncio
async def test_telegram_stars_requires_independent_product_price(db):
    """A digital purchase uses XTR rather than converting the rial price."""
    order, product, _ = make_order(
        db, Platform.TELEGRAM, digital=True
    )
    plan = await begin(db, Platform.TELEGRAM, order)
    assert plan.provider == "telegram_stars"
    assert plan.currency == "XTR"
    assert plan.amount == 50
    assert order.total_irr == 0
    assert order.total_stars_snapshot == 50
    with pytest.raises(PaymentRejected):
        await begin(db, Platform.TELEGRAM, order)


@pytest.mark.asyncio
async def test_telegram_physical_invoice_uses_confirmed_minor_factor(db):
    """The provider's configured minor factor is not a toman conversion."""
    order, _, _ = make_order(db, Platform.TELEGRAM)
    with pytest.raises(PaymentRejected):
        await ShopPaymentService.begin(
            db, platform=Platform.TELEGRAM, platform_user_id=101,
            order_id=order.id, bale_enabled=False,
            telegram_fiat_enabled=True, telegram_stars_enabled=False,
            telegram_minor_multiplier=0,
        )
    plan = await begin(db, Platform.TELEGRAM, order)
    assert plan.currency == "IRR"
    assert plan.amount == 2500 * 100


@pytest.mark.asyncio
async def test_manual_refund_records_proof_without_automatic_restock(db):
    """Only provider evidence closes a Bale refund case in the ledger."""
    order, product, _ = make_order(db, Platform.BALE)
    plan = await begin(db, Platform.BALE, order)
    await ShopPaymentService.settle(
        db, platform=Platform.BALE, payer_id=101, chat_id=101,
        payload=plan.payload, currency="IRR", amount=plan.amount,
        charge_id="bale-transaction", provider_charge_id="bale-receipt",
    )
    case = await ShopRefundService.request(
        db, platform=Platform.BALE, payer_id=101, order_id=order.id,
        reason="درخواست مشتری",
    )
    assert case.status == "requested"
    with pytest.raises(PaymentRejected):
        await ShopRefundService.confirm_manual(
            db, case_id=case.id, provider_reference="x", reviewer="admin"
        )
    complete = await ShopRefundService.confirm_manual(
        db, case_id=case.id,
        provider_reference="verified-bank-transaction",
        reviewer="admin",
    )
    assert complete.status == "confirmed"
    assert order.status == "refunded"
    assert product.stock_quantity == 1


class FakeStarsBot:
    """Explicit opt-in test double for Telegram's official Stars refund API."""

    def __init__(self):
        """Track calls with no Internet."""
        self.calls = []

    async def refund_star_payment(self, **kwargs):
        """Simulate an acknowledged provider refund."""
        self.calls.append(kwargs)
        return True


@pytest.mark.asyncio
async def test_stars_refund_calls_provider_only_once(db):
    """Do not re-send a potentially successful refund after a callback retry."""
    order, _, _ = make_order(db, Platform.TELEGRAM, digital=True)
    plan = await begin(db, Platform.TELEGRAM, order)
    await ShopPaymentService.settle(
        db,
        platform=Platform.TELEGRAM, payer_id=101, chat_id=101,
        payload=plan.payload, currency="XTR", amount=plan.amount,
        charge_id="stars-receipt-001", provider_charge_id=None,
    )
    case = await ShopRefundService.request(
        db, platform=Platform.TELEGRAM, payer_id=101,
        order_id=order.id, reason="درخواست مشتری",
    )
    bot = FakeStarsBot()
    with pytest.raises(PaymentRejected):
        await ShopRefundService.refund_stars(
            db, case_id=case.id, bot=bot, enabled=False, reviewer="admin",
        )
    assert bot.calls == []
    result = await ShopRefundService.refund_stars(
        db, case_id=case.id, bot=bot, enabled=True, reviewer="admin",
    )
    assert result.status == "confirmed"
    assert len(bot.calls) == 1
    assert bot.calls[0]["user_id"] == 101
    with pytest.raises(PaymentRejected):
        await ShopRefundService.refund_stars(
            db, case_id=case.id, bot=bot, enabled=True, reviewer="admin",
        )
    assert len(bot.calls) == 1
