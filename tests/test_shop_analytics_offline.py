"""Offline reporting tests: avoid mixing provider minor units, IRR and XTR."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models.base import Base
from models.shop_content import Product, ShopCategory, ShopIdentity, ShopOrder
from models.shop_checkout import ShopOrderLine
from models.shop_engagement import (
    ShopCampaign, ShopCampaignDelivery, ShopWalletAccount, ShopWalletEntry,
)
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
from services.shop_analytics import build_shop_analytics


class AsyncSessionAdapter:
    """Expose the async query signatures over an isolated synchronous SQLite DB."""

    def __init__(self, session: Session) -> None:
        """Remember the transaction-scoped SQLAlchemy session."""
        self.session = session

    async def scalar(self, query):
        """Read one scalar without contacting PostgreSQL."""
        return self.session.scalar(query)

    async def execute(self, query):
        """Run a real, in-memory SQL aggregate query."""
        return self.session.execute(query)


@pytest.fixture
def database():
    """Initialize all tables needed by the isolated analytics queries."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ShopCategory.__table__,
            Product.__table__,
            ShopIdentity.__table__,
            ShopOrder.__table__,
            ShopOrderLine.__table__,
            ShopPaymentAttempt.__table__,
            ShopRefundCase.__table__,
            ShopWalletAccount.__table__,
            ShopWalletEntry.__table__,
            ShopCampaign.__table__,
            ShopCampaignDelivery.__table__,
        ],
    )
    with Session(engine) as session:
        yield AsyncSessionAdapter(session)
    engine.dispose()


def paid_order(database, *, platform, provider, total_irr, amount, currency):
    """Insert a provider-confirmed order with a uniquely identified attempt."""
    session = database.session
    product = session.query(Product).first()
    order = ShopOrder(
        platform=platform,
        platform_user_id=100 if platform == "telegram" else 200,
        chat_id=100 if platform == "telegram" else 200,
        product_id=product.id,
        product_name_snapshot=product.name,
        quantity=1,
        unit_price_irr=total_irr,
        total_irr=total_irr,
        provider=provider,
        status="paid",
        invoice_payload=uuid4().hex,
        paid_at=datetime.now(timezone.utc),
    )
    session.add(order)
    session.flush()
    session.add(
        ShopOrderLine(
            order_id=order.id,
            product_id=product.id,
            product_name_snapshot=product.name,
            sku_snapshot=product.sku,
            quantity=1,
            unit_price_irr=total_irr,
            total_irr=total_irr,
        )
    )
    session.add(
        ShopPaymentAttempt(
            order_id=order.id,
            platform=platform,
            provider=provider,
            currency=currency,
            amount=amount,
            payload=order.invoice_payload,
            status="paid",
        )
    )
    session.commit()


@pytest.mark.asyncio
async def test_report_keeps_rials_store_credit_and_stars_separate(database):
    """Do not display Telegram minor units as rials or multiply XTR by IRR."""
    db = database.session
    db.add(Product(
        sku="REPORT", name="کالای نمونه", description="توضیح",
        price=1500, stock_quantity=20, is_published=True,
    ))
    db.add_all([
        ShopIdentity(platform="bale", platform_user_id=200,
                     allow_announcements=True, is_blocked=False),
        ShopIdentity(platform="telegram", platform_user_id=100,
                     allow_announcements=False, is_blocked=False),
    ])
    db.commit()

    # One IRR can be 100 provider minor units; reports use nominal IRR
    # only for verified paid Telegram fiat orders, never raw API amount.
    paid_order(
        database, platform="telegram", provider="telegram_fiat",
        total_irr=1500, amount=150000, currency="IRR",
    )
    paid_order(
        database, platform="bale", provider="bale_wallet",
        total_irr=2300, amount=2300, currency="IRR",
    )
    paid_order(
        database, platform="telegram", provider="telegram_stars",
        total_irr=1500, amount=42, currency="XTR",
    )
    paid_order(
        database, platform="bale", provider="store_credit",
        total_irr=700, amount=700, currency="IRR",
    )

    report = await build_shop_analytics(database, days=0)
    channels = {row.platform: row for row in report.channels}

    assert channels["telegram"].gross_paid_irr == 1500
    assert channels["telegram"].telegram_stars_xtr == 42
    assert channels["telegram"].store_credit_irr == 0
    assert channels["bale"].gross_paid_irr == 2300
    assert channels["bale"].store_credit_irr == 700
    assert channels["bale"].telegram_stars_xtr == 0
    assert channels["bale"].opted_in == 1
    assert channels["telegram"].opted_in == 0


@pytest.mark.asyncio
async def test_empty_analytics_has_no_fabricated_results(database):
    """Return true zero figures for a never-used store."""
    report = await build_shop_analytics(database, days=0)
    assert report.open_refund_cases == 0
    assert report.top_products == ()
    assert all(channel.orders == 0 for channel in report.channels)


@pytest.mark.asyncio
async def test_reporting_rejects_unbounded_arbitrary_period(database):
    """Accept only documented reporting periods."""
    with pytest.raises(ValueError):
        await build_shop_analytics(database, days=123456)
