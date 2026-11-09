"""Contract and catalog tests without a real Telegram or Bale token."""

from tests.schema_support import (
    create_shop_schema, seed_test_units, seed_registry, TEST_BOT_IDS,
    test_bot_context, allow_test_catalog,
)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from channels.contracts import InboundEvent, Platform, normalize_update
from models.base import Base
from models.shop_content import (
    Product, ProductMedia, ShopCategory, Testimonial,
)
from models.shop_bot_catalog_acl import ShopBotProductRule, ShopBotCategoryRule
from models.shop_bot_operations import ShopBotOperations
from models.shop_product_visibility import ShopProductVisibility
from models.shop_multibot import (
    DEFAULT_STORE_ID, ShopBot, ShopStore,
)
from models.shop_store_commerce import ShopStoreSettings
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

    def add(self, record):
        self.session.add(record)

    async def flush(self):
        self.session.flush()


@pytest.fixture
def session():
    """Provide isolated catalog rows and clean up after every test."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_shop_schema(engine)
    with Session(engine) as db:
        db.add(ShopStore(
            id=DEFAULT_STORE_ID, slug="default",
            name="Existing catalog", state="active",
        ))
        seed_registry(db)
        db.commit()
        seed_test_units(db)
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
async def test_default_catalog_reaches_nine_products_without_sending_cards(session, platform):
    """The shopper can page the compact list and opt into photos separately."""
    groups = [ShopCategory(name=f"دسته {index}", is_published=True) for index in range(2)]
    session.add_all(groups)
    session.flush()
    products = [
        Product(
            sku=f"COMPACT-{index}", name=f"محصول {index}", description="توضیح",
            price=200, stock_quantity=2, is_published=True, position=index,
            category_id=groups[index % 2].id if index < 8 else None,
        )
        for index in range(9)
    ]
    session.add_all(products)
    allow_test_catalog(session)
    session.add(ProductMedia(
        product_id=products[0].id, kind="photo",
        storage_key="a" * 32 + ".png", original_filename="cover.png",
        mime_type="image/png", size_bytes=20, is_published=True,
    ))
    session.commit()
    catalog = CatalogFlow(bot_context=test_bot_context(platform))
    proxy = AsyncSessionProxy(session)
    reply = await catalog.reply(event(platform, text="/catalog"), proxy)
    seen = []
    for page, count in enumerate((4, 4, 1)):
        assert not reply.cards and reply.preview is None
        assert f"صفحه {page + 1} از 3" in reply.text
        controls = [button for row in reply.rows for button in row]
        items = [button for button in controls if button.callback_data.startswith("shop:item:")]
        assert len(items) == count
        seen.extend(button.label for button in items)
        if page == 0:
            action = next(button.callback_data for button in controls
                          if button.callback_data.startswith("shop:gallery:"))
            gallery = await catalog.reply(event(platform, callback=action), proxy)
            assert len(gallery.cards) == 4 and gallery.cards[0].preview is not None
        if page < 2:
            action = next(button.callback_data for button in controls
                          if button.callback_data == f"shop:list:{page + 1}")
            reply = await catalog.reply(event(platform, callback=action), proxy)
        else:
            product = await catalog.reply(event(platform, callback=items[0].callback_data), proxy)
            assert product.rows[-1][0].callback_data == "shop:list:2"
    assert seen == [product.name for product in products]


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
    allow_test_catalog(session)
    session.commit()
    flow = CatalogFlow(bot_context=test_bot_context(platform))
    reply = await flow.reply(
        event(platform, text="/catalog"), AsyncSessionProxy(session)
    )
    assert reply is not None
    assert not reply.cards
    assert "کرم" in reply.text
    assert reply.rows[0][0].callback_data == "shop:item:1"
    assert "پنهان" not in reply.text
    detail = await flow.reply(
        event(platform, callback="shop:item:1"), AsyncSessionProxy(session)
    )
    assert "توضیح" in detail.text
    assert "250" in detail.text
    assert "ریال" in detail.text


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_home_return_uses_store_title_instead_of_welcome(session, platform):
    """The configured welcome is shown at entry, not on every return Home."""
    session.add(ShopStoreSettings(
        store_id=DEFAULT_STORE_ID, brand_name="فروشگاه آزمون",
        welcome_message="به منوی اصلی برگشتید.",
    ))
    session.commit()
    flow = CatalogFlow(bot_context=test_bot_context(platform))
    proxy = AsyncSessionProxy(session)
    entry = await flow.reply(event(platform, text="/start"), proxy)
    returned = await flow.reply(event(platform, callback="shop:home"), proxy)
    assert entry.text == "به منوی اصلی برگشتید."
    assert returned.text == "🛍 فروشگاه آزمون"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_stock_eye_hides_number_but_not_availability(session, platform):
    """The product dashboard policy hides quantity across both providers."""
    product = Product(
        sku="STOCK-1", name="محصول آزمون", description="", price=250,
        stock_quantity=12, is_published=True,
    )
    session.add(product)
    session.flush()
    session.add(ShopProductVisibility(product_id=product.id, show_stock=False))
    allow_test_catalog(session)
    session.commit()
    flow = CatalogFlow(bot_context=test_bot_context(platform))
    proxy = AsyncSessionProxy(session)
    hidden = await flow.reply(
        event(platform, callback=f"shop:item:{product.id}"), proxy,
    )
    assert "موجودی: 12" not in hidden.text
    assert "افزودن به سبد" in str(hidden.rows)
    product.stock_quantity = 0
    session.commit()
    unavailable = await flow.reply(
        event(platform, callback=f"shop:item:{product.id}"), proxy,
    )
    assert "ناموجود" in unavailable.text


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_gallery_shows_four_permitted_cards_and_restores_category_page(
    session, platform,
):
    """Browse four photo or text cards and return to the same category page."""
    category = ShopCategory(name="دسته آزمون", is_published=True, position=1)
    session.add(category)
    session.flush()
    products = [
        Product(
            sku=f"G-{index}", name=f"کالا {index}", description="توضیح بلند",
            price=index * 100, stock_quantity=10,
            category_id=category.id, position=index, is_published=index != 6,
        )
        for index in range(1, 8)
    ]
    session.add_all(products)
    session.flush()
    session.add_all([
        ProductMedia(
            product_id=products[0].id, kind="photo",
            storage_key="a" * 32 + ".png", original_filename="cover.png",
            mime_type="image/png", size_bytes=20, is_published=True,
        ),
        ProductMedia(
            product_id=products[2].id, kind="photo",
            storage_key="b" * 32 + ".png", original_filename="hidden.png",
            mime_type="image/png", size_bytes=20, is_published=False,
        ),
        ShopProductVisibility(
            product_id=products[1].id, show_stock=False, show_media=False,
        ),
        ShopBotProductRule(
            bot_id=TEST_BOT_IDS[platform.value], product_id=products[4].id,
            effect="deny",
        ),
    ])
    allow_test_catalog(session)
    session.commit()
    flow = CatalogFlow(bot_context=test_bot_context(platform))
    proxy = AsyncSessionProxy(session)
    prefix = f"shop:gallery:{category.id}:"

    first = await flow.reply(event(platform, callback=prefix + "0"), proxy)
    assert len(first.cards) == 4
    assert [product.name for product in products[:4]] == [
        card.text.splitlines()[0] for card in first.cards
    ]
    assert first.cards[0].preview is not None
    assert first.cards[1].preview is None
    assert "موجودی: 10" not in first.cards[1].text
    assert first.cards[2].preview is None
    assert all("توضیح بلند" not in card.text for card in first.cards)
    assert first.rows[0][0].callback_data == prefix + "1"

    second = await flow.reply(event(platform, callback=prefix + "1"), proxy)
    assert len(second.cards) == 1
    assert second.cards[0].text.startswith("کالا 7")
    assert second.rows[0][0].callback_data == prefix + "0"
    chosen = second.cards[0].rows[0][0].callback_data
    detail = await flow.reply(event(platform, callback=chosen), proxy)
    assert detail.rows[-1][0].callback_data == prefix + "1"
    expanded = await flow.reply(
        event(platform, callback=f"d:{products[6].id}:{category.id}:1"), proxy,
    )
    assert "توضیح بلند" in expanded.text
    assert expanded.rows[0][0].callback_data == chosen
    denied = await flow.reply(
        event(platform, callback=f"g:{products[4].id}:{category.id}:0"), proxy,
    )
    assert "کالا 5" not in denied.text


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_gallery_bounds_out_of_range_page(session, platform):
    """A stale page cursor resolves to the last available page."""
    for number in range(5):
        session.add(Product(
            sku=f"B-{number}", name=f"کالا {number}", description="",
            price=100, stock_quantity=1, position=number,
            is_published=True,
        ))
    allow_test_catalog(session)
    session.commit()
    reply = await CatalogFlow(bot_context=test_bot_context(platform)).reply(
        event(platform, callback="shop:gallery:0:999"), AsyncSessionProxy(session),
    )
    assert len(reply.cards) == 1
    assert reply.cards[0].text.startswith("کالا 4")
    assert reply.rows[0][0].callback_data == "shop:gallery:0:0"


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
    allow_test_catalog(session)
    session.commit()
    response = await CatalogFlow(bot_context=test_bot_context(platform)).reply(
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
    allow_test_catalog(session)
    session.commit()
    flow = CatalogFlow(bot_context=test_bot_context(platform))
    proxy = AsyncSessionProxy(session)
    start = await flow.reply(event(platform, text="/catalog"), proxy)
    assert "محصول" in start.text and not start.cards
    assert not start.attachments
    categories = await flow.reply(event(platform, callback="shop:categories"), proxy)
    assert categories.rows[0][0].label == "محصولات مراقبتی"
    category_page = await flow.reply(
        event(platform, callback=f"shop:category:{category.id}:0"),
        proxy,
    )
    assert "محصول" in category_page.text and not category_page.cards
    listing = await flow.reply(
        event(platform, callback=f"shop:files:{product.id}:0"), proxy
    )
    assert not listing.attachments
    media_id = session.query(ProductMedia).filter_by(is_published=True).one().id
    assert listing.rows[0][0].callback_data == f"shop:file:{media_id}"
    attachment = await flow.reply(
        event(platform, callback=f"shop:file:{media_id}"), proxy,
    )
    assert len(attachment.attachments) == 1
    assert attachment.attachments[0].mime_type == "application/pdf"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_published_category_tree_reaches_products_without_exposing_hidden_parents(session, platform):
    root = ShopCategory(name="مراقبت", is_published=True)
    hidden = ShopCategory(name="والد خصوصی", is_published=False)
    session.add_all([root, hidden])
    session.flush()
    child = ShopCategory(name="مو", parent_id=root.id, is_published=True)
    promoted = ShopCategory(name="قابل مشاهده", parent_id=hidden.id, is_published=True)
    session.add_all([child, promoted])
    session.flush()
    session.add_all([
        Product(name="شامپو", sku="TREE-1", description="", category_id=child.id, price=500, is_published=True),
        Product(name="صابون", sku="TREE-2", description="", category_id=promoted.id, price=500, is_published=True),
    ])
    allow_test_catalog(session)
    session.commit()

    flow = CatalogFlow(bot_context=test_bot_context(platform))
    db = AsyncSessionProxy(session)
    roots = await flow.reply(event(platform, callback="shop:categories"), db)
    assert [row[0].label for row in roots.rows] == ["مراقبت", "قابل مشاهده", "همه محصولات"]
    nested = await flow.reply(event(platform, callback=f"shop:category:{root.id}:0"), db)
    assert nested.rows[0][0].callback_data == f"shop:category:{child.id}:0"
    items = await flow.reply(event(platform, callback=nested.rows[0][0].callback_data), db)
    assert "شامپو" in items.text
    unavailable = await flow.reply(event(platform, callback=f"shop:subcategories:{hidden.id}:0"), db)
    assert "والد خصوصی" not in unavailable.text
    assert unavailable.rows[0][0].callback_data == "shop:categories"
