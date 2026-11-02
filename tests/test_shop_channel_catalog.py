"""Contract and catalog tests without a real Telegram or Bale token."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from channels.contracts import InboundEvent, Platform, normalize_update
from models.base import Base
from models.shop_content import Product, Testimonial
from services.shop_channel_catalog import CatalogFlow


class AsyncSessionProxy:
    """Turn synchronous SQLite queries into awaited session calls for tests."""

    def __init__(self, session: Session) -> None:
        """Keep a SQLAlchemy session with an in-memory database."""
        self.session = session

    async def execute(self, statement):
        """Execute a real SQL statement without external PostgreSQL."""
        return self.session.execute(statement)


@pytest.fixture
def session():
    """Provide isolated catalog rows and clean up after every test."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine, tables=[Product.__table__, Testimonial.__table__]
    )
    with Session(engine) as db:
        yield db
    engine.dispose()


def event(platform, callback=None, text=None):
    """Construct matching events for both adapters."""
    return InboundEvent(
        platform=platform,
        chat_id=101,
        user_id=101,
        text=text,
        callback_data=callback,
        callback_query_id="55" if callback else None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_catalog_uses_database_without_hardcoded_products(session, platform):
    """Only published products appear, regardless of messaging platform."""
    session.add_all(
        [
            Product(
                sku="P-1", name="کرم", description="توضیح", price=Decimal("250"),
                stock_quantity=2, is_published=True,
            ),
            Product(
                sku="P-2", name="پنهان", description="مخفی", price=Decimal("8"),
                stock_quantity=1, is_published=False,
            ),
        ]
    )
    session.commit()
    flow = CatalogFlow()
    reply = await flow.reply(
        event(platform, text="/catalog"), AsyncSessionProxy(session)
    )
    assert reply is not None
    assert len(reply.rows) == 1
    assert reply.rows[0][0].label == "کرم"
    assert "پنهان" not in reply.text
    detail = await flow.reply(
        event(platform, callback="shop:item:1"), AsyncSessionProxy(session)
    )
    assert "توضیح" in detail.text
    assert "250" in detail.text


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_only_approved_testimonials_render(session, platform):
    """Hide unapproved customer testimonials across both channels."""
    product = Product(
        sku="P-3", name="محصول", description="توضیح", price=Decimal("20"),
        stock_quantity=10, is_published=True,
    )
    session.add(product)
    session.flush()
    session.add_all([
        Testimonial(product_id=product.id, text="واقعی", is_approved=True),
        Testimonial(product_id=product.id, text="مخفی", is_approved=False),
    ])
    session.commit()
    response = await CatalogFlow().reply(
        event(platform, callback=f"shop:reviews:{product.id}:0"),
        AsyncSessionProxy(session),
    )
    assert "واقعی" in response.text
    assert "مخفی" not in response.text


@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
def test_equivalent_update_normalization(platform):
    """Both Bot APIs produce the same normalized callback event."""
    payload = {
        "update_id": 10,
        "callback_query": {
            "id": "55",
            "from": {"id": 101},
            "message": {"chat": {"id": 101, "type": "private"}},
            "data": "shop:item:42",
        },
    }
    result = normalize_update(platform, payload)
    assert result is not None
    assert result.platform == platform
    assert result.chat_id == 101
    assert result.callback_data == "shop:item:42"
    assert normalize_update(
        platform,
        {
            "message": {
                "from": {"id": 101},
                "chat": {"id": -1, "type": "group"},
                "text": "/catalog",
            }
        },
    ) is None
