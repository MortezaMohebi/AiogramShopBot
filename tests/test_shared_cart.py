"""Offline regression scenarios for the shared Telegram/Bale shopping cart.

No platform tokens, network, real payments or production DB are involved.
"""

from tests.schema_support import (
    create_shop_schema, seed_test_units, seed_registry, TEST_BOT_IDS,
    test_bot_context, allow_test_catalog, seed_customer,
)

import re

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from channels.contracts import InboundEvent, Platform
from models.base import Base
from models.shop_checkout import (
    ShopCart, ShopCartItem, ShopCoupon, ShopOrderLine, ShopShippingMethod,
)
from models.shop_content import Product, ShopCategory, ShopOrder
from models.shop_content import ShopIdentity
from models.shop_customer_account_data import ShopCustomerAddress
from models.shop_bot_catalog_acl import ShopBotProductRule, ShopBotCategoryRule
from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import (
    DEFAULT_STORE_ID, ShopBot, ShopStore,
)
from models.shop_staff import ShopStaff
from services.shop_cart import ShopCartFlow, validate_coupon
from services.shop_customer_account import CustomerAccountFlow
from services.shop_orders import ShopOrdersFlow


class AsyncDatabase:
    """Adapt the disposable SQLite session to the async repository contract."""

    def __init__(self, session: Session) -> None:
        """Keep the SQLAlchemy session inside the test."""
        self.session = session

    async def execute(self, statement):
        """Execute a SQL statement against in-memory SQLite."""
        return self.session.execute(statement)

    async def scalar(self, statement):
        """Read a single value."""
        return self.session.scalar(statement)

    async def scalars(self, statement):
        """Return scalar query results for ACL predicates."""
        return self.session.scalars(statement)

    def add(self, record):
        """Add a new cart or order row to this isolated session."""
        self.session.add(record)

    async def get(self, model, key):
        """Load a model by its primary key."""
        return self.session.get(model, key)

    async def flush(self):
        """Assign generated primary keys."""
        self.session.flush()

    async def commit(self):
        """Commit the isolated test transaction."""
        self.session.commit()

    async def rollback(self):
        """Roll back a failed isolated transaction."""
        self.session.rollback()

    async def delete(self, record):
        """Remove one managed object."""
        self.session.delete(record)

    @asynccontextmanager
    async def begin_nested(self):
        """Expose a real SQLAlchemy savepoint to the shared customer flow."""
        with self.session.begin_nested():
            yield


@pytest.fixture
def db():
    """Provide complete new checkout tables in disposable SQLite memory."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_shop_schema(engine)
    with Session(engine) as session:
        session.add(ShopStore(
            id=DEFAULT_STORE_ID, slug="default",
            name="Existing Store", state="active",
        ))
        seed_registry(session)
        session.commit()
        from models.shop_checkout_policy import ShopStoreCheckoutPolicy
        session.add(ShopStoreCheckoutPolicy(
            store_id=DEFAULT_STORE_ID, mode="manual", terms_version="fixture-v1",
            terms_text="شرایط فروش آزمایشی؛ سفارش تنها پس از تأیید و پرداخت انجام می‌شود.",
        ))
        session.commit()
        seed_test_units(session)
        seed_customer(session, Platform.TELEGRAM, 101)
        seed_customer(session, Platform.BALE, 101)
        session.commit()
        yield AsyncDatabase(session)
    engine.dispose()


def event(platform, callback=None, text=None, uid=101):
    """Represent the same user interaction on both messaging platforms."""
    return InboundEvent(
        platform=platform, chat_id=uid, user_id=uid,
        callback_data=callback, text=text,
        callback_query_id="cb" if callback else None,
    )


def seed(db):
    """Create two products, an optional discount, and one shipping method."""
    first = Product(
        sku="SKU-A", name="محصول اول", description="توضیح", price=1000,
        stock_quantity=5, is_published=True, requires_shipping=True,
    )
    second = Product(
        sku="SKU-B", name="محصول دوم", description="توضیح", price=2500,
        stock_quantity=7, is_published=True, requires_shipping=True,
    )
    db.session.add_all([
        first, second,
        ShopShippingMethod(name="پست", price_irr=500, is_active=True),
        ShopCoupon(
            code="SAVE10", discount_type="percent", value=10,
            minimum_subtotal_irr=0, is_active=True,
        ),
    ])
    allow_test_catalog(db.session)
    db.session.commit()
    return first, second


async def select_saved_address(db, platform):
    """Select an account address through the real checkout callback."""
    identity = db.session.scalar(select(ShopIdentity).where(
        ShopIdentity.bot_id == TEST_BOT_IDS[platform.value],
        ShopIdentity.platform_user_id == 101,
    ))
    address = ShopCustomerAddress(
        store_id=DEFAULT_STORE_ID, customer_id=identity.customer_id,
        label="خانه", recipient="مشتری آزمایشی", phone="09123456789",
        province="تهران", city="تهران",
        full_address="خیابان نمونه، پلاک ۱۲", is_default=True,
    )
    db.add(address)
    await db.commit()
    result = await CustomerAccountFlow(
        bot_context=test_bot_context(platform),
    ).reply(event(platform, callback=f"ux:address:choose:{address.id}"), db)
    assert "نشانی انتخاب شد" in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_cart_quote_shipping_coupon_and_order_are_common(db, platform):
    """Verify the same price, line snapshots and callback semantics for both."""
    first, second = seed(db)
    flow = ShopCartFlow(bot_context=test_bot_context(platform))
    await flow.reply(event(platform, callback=f"shop:add:{first.id}"), db)
    await flow.reply(event(platform, callback=f"shop:add:{first.id}"), db)
    await flow.reply(event(platform, callback=f"shop:add:{second.id}"), db)

    prompt = await flow.reply(event(platform, callback="shop:address"), db)
    assert "نشانی" in prompt.text
    await select_saved_address(db, platform)
    await flow.reply(event(platform, callback="shop:ship:1"), db)
    await flow.reply(event(platform, callback="shop:coupon"), db)
    await flow.reply(event(platform, text="save10"), db)

    cart_page = await flow.reply(event(platform, callback="shop:cart"), db)
    assert "4,500 ریال" in cart_page.text
    assert "450 ریال" in cart_page.text
    assert "500 ریال" in cart_page.text
    assert "4,550 ریال" in cart_page.text

    review = await flow.reply(event(platform, callback="shop:checkout"), db)
    match = re.search(r"shop:place:(\d+):(\d+):([a-f0-9]{12})", str(review.rows))
    assert match is not None
    action = match.group(0)
    confirmation = await flow.reply(event(platform, callback=action), db)
    assert "ثبت شد" in confirmation.text
    order = db.session.scalars(select(ShopOrder)).one()
    lines = db.session.scalars(select(ShopOrderLine)).all()
    assert order.status == "pending_review"
    assert order.provider == "manual_review"
    assert order.subtotal_irr == 4500
    assert order.discount_irr == 450
    assert order.shipping_irr == 500
    assert order.total_irr == 4550
    assert len(lines) == 2
    assert sorted(line.quantity for line in lines) == [1, 2]
    assert first.stock_quantity == 5  # No paid sale or stock reservation.
    assert order.telegram_payment_charge_id is None

    repeated = await flow.reply(event(platform, callback=action), db)
    assert "قبلاً ثبت شده" in repeated.text
    assert len(db.session.scalars(select(ShopOrder)).all()) == 1


@pytest.mark.asyncio
async def test_platform_identifiers_do_not_share_a_cart(db):
    """The same integer ID in Telegram and Bale is not one customer."""
    first, _ = seed(db)
    flow = ShopCartFlow(bot_context=test_bot_context(Platform.BALE))
    await flow.reply(event(Platform.BALE, callback=f"shop:add:{first.id}"), db)
    telegram = await ShopCartFlow(
        bot_context=test_bot_context(Platform.TELEGRAM),
    ).reply(event(Platform.TELEGRAM, callback="shop:cart"), db)
    assert telegram.text == "سبد خرید خالی است."
    assert len(db.session.scalars(select(ShopCart)).all()) == 1


@pytest.mark.asyncio
async def test_out_of_stock_can_still_be_removed(db):
    """Stale stock must not make a customer's cart impossible to repair."""
    first, _ = seed(db)
    flow = ShopCartFlow(bot_context=test_bot_context(Platform.BALE))
    await flow.reply(event(Platform.BALE, callback=f"shop:add:{first.id}"), db)
    first.stock_quantity = 0
    db.session.commit()
    broken = await flow.reply(event(Platform.BALE, callback="shop:cart"), db)
    assert "🗑" in str(broken.rows)
    fixed = await flow.reply(
        event(Platform.BALE, callback=f"shop:remove:{first.id}"), db
    )
    assert "خالی" in fixed.text


@pytest.mark.asyncio
async def test_address_and_shipping_are_required_for_physical_goods(db):
    """Never silently omit physical delivery information from order requests."""
    first, _ = seed(db)
    flow = ShopCartFlow(bot_context=test_bot_context(Platform.TELEGRAM))
    await flow.reply(event(Platform.TELEGRAM, callback=f"shop:add:{first.id}"), db)
    result = await flow.reply(
        event(Platform.TELEGRAM, callback="shop:checkout"), db
    )
    assert "نشانی و روش ارسال" in result.text
    assert len(db.session.scalars(select(ShopOrder)).all()) == 0


def test_percent_coupon_never_creates_zero_rial_invoice(db):
    """Coupon calculations are integer-only and cannot make a free invoice."""
    coupon = ShopCoupon(
        code="ALL", discount_type="percent", value=100,
        minimum_subtotal_irr=0, is_active=True, used_count=0,
    )
    assert validate_coupon(coupon, subtotal=1000) == 999


@pytest.mark.asyncio
async def test_order_history_and_cancellation_require_matching_platform(db):
    """Only the original Bale user can cancel an unpaid Bale request."""
    first, _ = seed(db)
    flow = ShopCartFlow(bot_context=test_bot_context(Platform.BALE))
    await flow.reply(event(Platform.BALE, callback=f"shop:add:{first.id}"), db)
    await flow.reply(event(Platform.BALE, callback="shop:address"), db)
    await select_saved_address(db, Platform.BALE)
    await flow.reply(event(Platform.BALE, callback="shop:ship:1"), db)
    confirmation = await flow.reply(
        event(Platform.BALE, callback="shop:checkout"), db
    )
    place_callback = confirmation.rows[0][0].callback_data
    await flow.reply(event(Platform.BALE, callback=place_callback), db)
    order = db.session.scalars(select(ShopOrder)).one()
    history = ShopOrdersFlow(bot_context=test_bot_context(Platform.BALE))
    response = await history.reply(event(Platform.BALE, callback="shop:orders"), db)
    assert "1 کالا" in response.text
    assert "در انتظار بررسی" in response.text
    cancellation = f"shop:cancelorder:{order.id}"
    rejected = await ShopOrdersFlow(
        bot_context=test_bot_context(Platform.TELEGRAM),
    ).reply(event(Platform.TELEGRAM, callback=cancellation), db)
    assert "یافت نشد" in rejected.text
    allowed = await history.reply(
        event(Platform.BALE, callback=cancellation), db
    )
    assert "لغو شد" in allowed.text
    assert order.status == "cancelled"
    again = await history.reply(
        event(Platform.BALE, callback=cancellation), db
    )
    assert "امکان‌پذیر نیست" in again.text
    # Cancellation never decrements stock or creates payment receipts.
    assert first.stock_quantity == 5
    assert order.telegram_payment_charge_id is None


@pytest.mark.asyncio
async def test_coupon_expiry_has_recovery_action(db):
    """An invalidated coupon must remain removable without a developer."""
    first, _ = seed(db)
    flow = ShopCartFlow(bot_context=test_bot_context(Platform.TELEGRAM))
    await flow.reply(event(Platform.TELEGRAM, callback=f"shop:add:{first.id}"), db)
    await flow.reply(event(Platform.TELEGRAM, callback="shop:coupon"), db)
    await flow.reply(event(Platform.TELEGRAM, text="SAVE10"), db)
    coupon = db.session.scalar(select(ShopCoupon))
    coupon.is_active = False
    db.session.commit()
    reply = await flow.reply(
        event(Platform.TELEGRAM, callback="shop:cart"), db
    )
    assert any(
        action.callback_data == "shop:clear_coupon"
        for row in reply.rows for action in row
    )
    restored = await flow.reply(
        event(Platform.TELEGRAM, callback="shop:clear_coupon"), db
    )
    assert "1,000 ریال" in restored.text
