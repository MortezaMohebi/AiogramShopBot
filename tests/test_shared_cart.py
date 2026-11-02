"""Offline regression scenarios for the shared Telegram/Bale shopping cart.

No platform tokens, network, real payments or production DB are involved.
"""

import re

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from channels.contracts import InboundEvent, Platform
from models.base import Base
from models.shop_checkout import (
    ShopCart, ShopCartItem, ShopCoupon, ShopOrderLine, ShopShippingMethod,
)
from models.shop_content import Product, ShopCategory, ShopOrder
from services.shop_cart import ShopCartFlow, validate_coupon


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


@pytest.fixture
def db():
    """Provide complete new checkout tables in disposable SQLite memory."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [
        ShopCategory.__table__,
        Product.__table__,
        ShopShippingMethod.__table__,
        ShopCoupon.__table__,
        ShopCart.__table__,
        ShopCartItem.__table__,
        ShopOrder.__table__,
        ShopOrderLine.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine) as session:
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
    db.session.commit()
    return first, second


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_cart_quote_shipping_coupon_and_order_are_common(db, platform):
    """Verify the same price, line snapshots and callback semantics for both."""
    first, second = seed(db)
    flow = ShopCartFlow()
    await flow.reply(event(platform, callback=f"shop:add:{first.id}"), db)
    await flow.reply(event(platform, callback=f"shop:add:{first.id}"), db)
    await flow.reply(event(platform, callback=f"shop:add:{second.id}"), db)

    prompt = await flow.reply(event(platform, callback="shop:address"), db)
    assert "نشانی" in prompt.text
    await flow.reply(event(platform, text="تهران خیابان نمونه پلاک ۱۲"), db)
    await flow.reply(event(platform, callback="shop:ship:1"), db)
    await flow.reply(event(platform, callback="shop:coupon"), db)
    await flow.reply(event(platform, text="save10"), db)

    cart_page = await flow.reply(event(platform, callback="shop:cart"), db)
    assert "4,500 ریال" in cart_page.text
    assert "450 ریال" in cart_page.text
    assert "500 ریال" in cart_page.text
    assert "4,550 ریال" in cart_page.text

    review = await flow.reply(event(platform, callback="shop:checkout"), db)
    match = re.search(r"shop:place:(\d+):(\d+)", str(review.rows))
    assert match is not None
    action = f"shop:place:{match.group(1)}:{match.group(2)}"
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
    flow = ShopCartFlow()
    await flow.reply(event(Platform.BALE, callback=f"shop:add:{first.id}"), db)
    telegram = await flow.reply(event(Platform.TELEGRAM, callback="shop:cart"), db)
    assert telegram.text == "سبد خرید خالی است."
    assert len(db.session.scalars(select(ShopCart)).all()) == 1


@pytest.mark.asyncio
async def test_out_of_stock_can_still_be_removed(db):
    """Stale stock must not make a customer's cart impossible to repair."""
    first, _ = seed(db)
    flow = ShopCartFlow()
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
    flow = ShopCartFlow()
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
