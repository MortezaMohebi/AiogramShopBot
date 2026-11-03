"""Contract and catalog tests without a real Telegram or Bale token."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from channels.contracts import InboundEvent, Platform, normalize_update
from models.base import Base
from models.shop_content import (
    Product, ProductMedia, ShopCategory, ShopSettings, Testimonial,
)
from models.shop_bot_catalog_acl import ShopBotProductRule, ShopBotCategoryRule
from models.shop_bot_operations import ShopBotOperations
from models.shop_channel_features import ShopChannelFeature
from models.shop_product_visibility import ShopProductVisibility
from models.shop_multibot import (
    DEFAULT_STORE_ID, LEGACY_BOT_IDS, ShopBot, ShopStore,
)
from models.shop_staff import ShopStaff
from services.shop_channel_catalog import CatalogFlow


class AsyncSessionProxy:
    """Turn synchronous SQLite queries into awaited session calls for tests."""

    def __init__(self, session: Session) -> None:
        """Keep a SQLAlchemy session with an in-memory database."""
        self.session = session

    async def execute(self, statement):
        """Execute a real SQL statement without external PostgreSQL."""
        return self.session.execute(statement)

    async def scalar(self, statement):
        """Return one scalar from the disposable database."""
        return self.session.scalar(statement)

    async def scalars(self, statement):
        """Return ORM scalar results from disposable SQLite."""
        return self.session.scalars(statement)

    async def get(self, model, key):
        """Read one record by primary key without network requests."""
        return self.session.get(model, key)


@pytest.fixture
def session():
    """Provide isolated catalog rows and clean up after every test."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine, tables=[
            ShopStaff.__table__, ShopStore.__table__, ShopBot.__table__,
            ShopCategory.__table__, Product.__table__,
            ProductMedia.__table__, Testimonial.__table__,
            ShopSettings.__table__, ShopProductVisibility.__table__,
            ShopChannelFeature.__table__, ShopBotOperations.__table__,
            ShopBotProductRule.__table__, ShopBotCategoryRule.__table__,
        ]
    )
    with Session(engine) as db:
        db.add(ShopStore(
            id=DEFAULT_STORE_ID, slug="default",
            name="Existing catalog", state="active",
        ))
        db.add_all([
            ShopBot(
                id=bot_id, store_id=DEFAULT_STORE_ID,
                slug=f"legacy-{platform}", name=f"Legacy {platform}",
                platform=platform, status="legacy", runtime_owner="legacy",
                version=1, credential_version=1,
            ) for platform, bot_id in LEGACY_BOT_IDS.items()
        ])
        db.commit()
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
                sku="P-1", name="کرم", description="توضیح", price=250,
                stock_quantity=2, is_published=True,
            ),
            Product(
                sku="P-2", name="پنهان", description="مخفی", price=8,
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
    assert len(reply.rows) == 2
    assert reply.rows[0][0].label == "کرم"
    assert "پنهان" not in reply.text
    detail = await flow.reply(
        event(platform, callback="shop:item:1"), AsyncSessionProxy(session)
    )
    assert "توضیح" in detail.text
    assert "250" in detail.text
    assert "ریال" in detail.text


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_only_approved_testimonials_render(session, platform):
    """Hide unapproved customer testimonials across both channels."""
    product = Product(
        sku="P-3", name="محصول", description="توضیح", price=20,
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


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_dynamic_category_and_unpublished_media(session, platform):
    """Keep categories and files in the database for both message adapters."""
    category = ShopCategory(
        name="محصولات مراقبتی", is_published=True, position=1,
    )
    session.add(category)
    session.flush()
    product = Product(
        category_id=category.id,
        name="محصول", sku="DATA-1", description="توضیح", price=500,
        stock_quantity=5, is_published=True,
    )
    session.add(product)
    session.flush()
    session.add_all(
        [
            ProductMedia(
                product_id=product.id, kind="document",
                storage_key="0" * 32 + ".pdf", original_filename="guide.pdf",
                mime_type="application/pdf", size_bytes=25,
                is_published=True, position=1,
            ),
            ProductMedia(
                product_id=product.id, kind="photo",
                storage_key="1" * 32 + ".png", original_filename="secret.png",
                mime_type="image/png", size_bytes=20,
                is_published=False, position=2,
            ),
        ]
    )
    session.commit()
    flow = CatalogFlow()
    proxy = AsyncSessionProxy(session)
    start = await flow.reply(event(platform, text="/catalog"), proxy)
    assert start.rows[0][0].label == "محصولات مراقبتی"
    category_page = await flow.reply(
        event(platform, callback=f"shop:category:{category.id}:0"),
        proxy,
    )
    assert category_page.rows[0][0].label == "محصول"
    attachments = await flow.reply(
        event(platform, callback=f"shop:files:{product.id}:0"), proxy
    )
    assert len(attachments.attachments) == 1
    assert attachments.attachments[0].mime_type == "application/pdf"
