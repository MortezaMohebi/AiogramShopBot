"""Offline acceptance for per-bot product/category ACL and commerce gates.

Real SQLAlchemy constraints and the production policy expression are used.
No Telegram/Bale credential, real payment, file upload or network is needed.
"""

from __future__ import annotations

from tests.schema_support import create_shop_schema, seed_test_units

from contextlib import asynccontextmanager

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from channels.contracts import InboundEvent, Platform
from models.base import Base
from models.shop_admin_control import AdminEvent
from models.shop_bot_catalog_acl import (
    ShopBotProductRule, ShopBotCategoryRule, ShopBotCatalogAudit,
)
from models.shop_bot_operations import ShopBotOperations
from models.shop_channel_features import ShopChannelFeature
from models.shop_checkout import (
    ShopCart, ShopCartItem, ShopCoupon, ShopOrderLine, ShopShippingMethod,
)
from models.shop_content import (
    Product, ProductMedia, ShopCategory, ShopOrder, ShopSettings, Testimonial,
)
from models.shop_multibot import (
    DEFAULT_STORE_ID, LEGACY_BOT_IDS, ShopBot, ShopBotRegistryEvent, ShopStore,
)
from models.shop_payment import ShopPaymentAttempt
from models.shop_product_visibility import ShopProductVisibility
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_bot_catalog_acl as acl
from services.shop_cart import ShopCartFlow
from services.shop_channel_catalog import CatalogFlow
from services.shop_payments import PaymentRejected, ShopPaymentService


class AsyncDb:
    """Adapt an isolated Session to the async methods used by production."""

    def __init__(self, session: Session) -> None:
        """Retain a disposable SQLite session without provider connections."""
        self.session = session

    async def get(self, model, key, **kwargs):
        """Load one model with SQLAlchemy identity-map semantics."""
        return self.session.get(model, key, **kwargs)

    async def scalar(self, stmt):
        """Execute a scalar SQL statement."""
        return self.session.scalar(stmt)

    async def scalars(self, stmt):
        """Execute an ORM scalar statement."""
        return self.session.scalars(stmt)

    async def execute(self, stmt):
        """Return a full ORM result."""
        return self.session.execute(stmt)

    async def flush(self):
        """Flush new records before a scenario assertion."""
        self.session.flush()

    async def commit(self):
        """Commit the current test transaction."""
        self.session.commit()

    async def rollback(self):
        """Rollback after an intentional test validation error."""
        self.session.rollback()

    def add(self, item):
        """Attach a new row to the test transaction."""
        self.session.add(item)

    async def delete(self, item):
        """Remove a managed ORM object."""
        self.session.delete(item)

    @asynccontextmanager
    async def begin_nested(self):
        """Expose a real SQLAlchemy savepoint to the shared customer flow."""
        with self.session.begin_nested():
            yield


@pytest.fixture
def db():
    """Create actual ACL, catalog, cart and payment tables in private memory."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_shop_schema(engine)
    with Session(engine) as session:
        session.add(ShopStaff(
            id=1, username="admin", password_hash="unused-test-only",
            role="superadmin", is_active=True, session_version=1,
        ))
        session.add(ShopStore(
            id=DEFAULT_STORE_ID, slug="default",
            name="Existing store", state="active",
        ))
        session.add_all([
            ShopBot(
                id=bot_id, store_id=DEFAULT_STORE_ID,
                slug=f"legacy-{platform}", name=f"Legacy {platform}",
                platform=platform, status="legacy",
                runtime_owner="legacy", credential_version=1, version=1,
            ) for platform, bot_id in LEGACY_BOT_IDS.items()
        ])
        session.add(ShopBot(
            id=str(uuid4()), store_id=DEFAULT_STORE_ID,
            slug="new-bale-storefront", name="New Bale Storefront",
            platform="bale", status="draft", runtime_owner="registry",
            version=1, credential_version=None,
        ))
        session.add_all([
            ShopCategory(id=10, name="Category A", is_published=True),
            ShopCategory(id=20, name="Category B", is_published=True),
            Product(
                id=100, sku="TEST-100", name="Product Alpha",
                description="Details Alpha", category_id=10,
                price=1000, stock_quantity=10, is_published=True,
            ),
            Product(
                id=101, sku="TEST-101", name="Product Beta",
                description="Details Beta", category_id=10,
                price=2000, stock_quantity=10, is_published=True,
            ),
            Product(
                id=200, sku="TEST-200", name="Product Gamma",
                description="Details Gamma", category_id=20,
                price=3000, stock_quantity=10, is_published=True,
            ),
            Product(
                id=201, sku="TEST-201", name="Hidden Product",
                description="Unpublished", category_id=20,
                price=9000, stock_quantity=10, is_published=False,
            ),
        ])
        session.commit()
        seed_test_units(session)
        yield session
    engine.dispose()


async def preview(db: Session, bot_id: str) -> set[int]:
    """Evaluate preview visibility through the exact production SQL predicate."""
    wrapper = AsyncDb(db)
    scope = await acl.resolve_scope(wrapper, bot_id=bot_id, preview=True)
    return await acl.visible_product_ids(
        wrapper, scope, {100, 101, 200, 201},
    )


def new_bot(db: Session) -> ShopBot:
    """Return the only registry-owned draft bot."""
    return db.scalar(select(ShopBot).where(
        ShopBot.runtime_owner == "registry",
    ))


def test_existing_legacy_catalog_preserved_new_bots_default_deny(db):
    """Published products remain visible to old bots; drafts inherit DENY."""
    for bot_id in LEGACY_BOT_IDS.values():
        assert asyncio.run(preview(db, bot_id)) == {100, 101, 200}
    draft = new_bot(db)
    assert asyncio.run(preview(db, draft.id)) == set()
    actual_scope = asyncio.run(
        acl.resolve_scope(AsyncDb(db), bot_id=draft.id),
    )
    assert not actual_scope.available


def test_product_deny_stronger_than_category_allow(db):
    """Explicit Product Deny wins against an otherwise permitted category."""
    bot_id = new_bot(db).id
    acl.update_bot_rules(
        db, bot_id=bot_id, actor_id=1, expected_version=1,
        object_type="category", target_ids=[10],
        effect="allow",
    )
    acl.update_bot_rules(
        db, bot_id=bot_id, actor_id=1, expected_version=2,
        object_type="product", target_ids=[101],
        effect="deny",
    )
    db.commit()
    assert asyncio.run(preview(db, bot_id)) == {100}
    assert db.get(ShopBot, bot_id).version == 3


def test_product_allow_overrides_category_deny_but_not_unpublished(db):
    """One explicit product permission overrides category restrictions."""
    bot_id = new_bot(db).id
    acl.update_bot_rules(
        db, bot_id=bot_id, actor_id=1, expected_version=1,
        object_type="category", target_ids=[20],
        effect="deny",
    )
    acl.update_bot_rules(
        db, bot_id=bot_id, actor_id=1, expected_version=2,
        object_type="product", target_ids=[200, 201],
        effect="allow",
    )
    db.commit()
    assert asyncio.run(preview(db, bot_id)) == {200}


def test_legacy_denials_are_provider_specific_and_inherit_restores(db):
    """A Telegram Deny cannot hide Bale product; Inherit restores legacy."""
    telegram = LEGACY_BOT_IDS["telegram"]
    bale = LEGACY_BOT_IDS["bale"]
    acl.update_bot_rules(
        db, bot_id=telegram, actor_id=1, expected_version=1,
        object_type="product", target_ids=[100],
        effect="deny",
    )
    db.commit()
    assert 100 not in asyncio.run(preview(db, telegram))
    assert 100 in asyncio.run(preview(db, bale))
    acl.update_bot_rules(
        db, bot_id=telegram, actor_id=1, expected_version=2,
        object_type="product", target_ids=[100],
        effect="inherit",
    )
    db.commit()
    assert 100 in asyncio.run(preview(db, telegram))
    events = db.scalars(select(ShopBotCatalogAudit).where(
        ShopBotCatalogAudit.bot_id == telegram,
    )).all()
    assert [(entry.old_effect, entry.new_effect) for entry in events] == [
        ("inherit", "deny"), ("deny", "inherit"),
    ]


def test_atomic_product_many2many_and_stale_version_rejected(db):
    """One product can be denied by Telegram but allowed by a new Bale bot."""
    assignments = [
        (LEGACY_BOT_IDS["telegram"], "deny", 1),
        (new_bot(db).id, "allow", 1),
    ]
    changed = acl.update_product_bot_rules(
        db, product_id=200, actor_id=1,
        assignments=assignments,
    )
    db.commit()
    assert changed == 2
    assert 200 not in asyncio.run(preview(db, LEGACY_BOT_IDS["telegram"]))
    assert 200 in asyncio.run(preview(db, new_bot(db).id))
    with pytest.raises(security.SecurityRejected) as refused:
        acl.update_bot_rules(
            db, bot_id=LEGACY_BOT_IDS["telegram"],
            actor_id=1, expected_version=1,
            object_type="product", target_ids=[100],
            effect="allow",
        )
    assert refused.value.code == "configuration_changed"


def test_paused_bot_and_unavailable_other_store_fail_closed(db):
    """Neither a paused bot nor a nonisolated store can sell shared products."""
    legacy_id = LEGACY_BOT_IDS["telegram"]
    db.add(ShopBotOperations(
        bot_id=legacy_id, desired_state="paused",
        environment="staging",
    ))
    other = ShopStore(
        id=str(uuid4()), slug="second-store", name="Unready", state="paused",
    )
    db.add(other)
    other_bot = ShopBot(
        id=str(uuid4()), store_id=other.id, slug="other-bot",
        name="Other", platform="telegram", status="draft",
        runtime_owner="registry", version=1,
    )
    db.add(other_bot)
    db.commit()
    assert not asyncio.run(
        acl.resolve_legacy_scope(AsyncDb(db), "telegram"),
    ).available
    assert asyncio.run(preview(db, other_bot.id)) == set()
    with pytest.raises(security.SecurityRejected) as refused:
        acl.update_bot_rules(
            db, bot_id=other_bot.id, actor_id=1, expected_version=1,
            object_type="product", target_ids=[100], effect="allow",
        )
    assert refused.value.code == "store_not_active"


def test_old_product_and_media_callbacks_are_denied(db):
    """A copied product/media/review callback cannot reveal a denied item."""
    acl.update_bot_rules(
        db, bot_id=LEGACY_BOT_IDS["telegram"],
        actor_id=1, expected_version=1, object_type="product",
        target_ids=[100], effect="deny",
    )
    db.commit()
    wrapper = AsyncDb(db)
    flow = CatalogFlow()
    for callback in ("shop:item:100", "shop:files:100:0", "shop:reviews:100:0"):
        reply = asyncio.run(flow.reply(InboundEvent(
            platform=Platform.TELEGRAM, user_id=123, chat_id=123,
            callback_data=callback, callback_query_id="cb",
        ), wrapper))
        assert reply is not None
        assert "Details Alpha" not in reply.text
        assert reply.attachments == ()
    bale = asyncio.run(flow.reply(InboundEvent(
        platform=Platform.BALE, user_id=123, chat_id=123,
        callback_data="shop:item:100", callback_query_id="cb",
    ), wrapper))
    assert "Details Alpha" in bale.text


def test_cart_rechecks_acl_before_new_checkout(db):
    """A hidden product cannot be bought using an old add/cart/place button."""
    wrapper = AsyncDb(db)
    flow = ShopCartFlow()
    user = 889
    add = InboundEvent(
        platform=Platform.TELEGRAM, user_id=user, chat_id=user,
        callback_data="shop:add:100", callback_query_id="cb",
    )
    added = asyncio.run(flow.reply(add, wrapper))
    assert "Product Alpha" in added.text
    acl.update_bot_rules(
        db, bot_id=LEGACY_BOT_IDS["telegram"], actor_id=1,
        expected_version=1, object_type="product",
        target_ids=[100], effect="deny",
    )
    db.commit()
    preview_reply = asyncio.run(flow.reply(InboundEvent(
        platform=Platform.TELEGRAM, user_id=user, chat_id=user,
        callback_data="shop:checkout", callback_query_id="cb",
    ), wrapper))
    assert "مجاز نیستند" in preview_reply.text
    assert db.scalars(select(ShopOrder)).all() == []
    cleanup = asyncio.run(flow.reply(InboundEvent(
        platform=Platform.TELEGRAM, user_id=user, chat_id=user,
        callback_data="shop:cart", callback_query_id="cb",
    ), wrapper))
    assert "Product Alpha" not in cleanup.text
    assert "Product Alpha" not in str(cleanup.rows)


def test_new_invoice_blocked_after_access_revocation(db):
    """New provider invoices are denied, while old paid receipts are unaffected."""
    order = ShopOrder(
        platform="bale", platform_user_id=123,
        chat_id=123, product_id=100,
        product_name_snapshot="Product Alpha",
        quantity=1, unit_price_irr=1000, total_irr=1000,
        provider="manual_review", status="approved_unpaid",
        invoice_payload="test-invoice-payload",
        subtotal_irr=1000, discount_irr=0, shipping_irr=0,
        shipping_address="Test address", shipping_method_snapshot="Courier",
    )
    db.add(order)
    db.flush()
    db.add(ShopOrderLine(
        order_id=order.id, product_id=100,
        product_name_snapshot="Product Alpha", sku_snapshot="TEST-100",
        unit_price_irr=1000, quantity=1, total_irr=1000,
    ))
    db.commit()
    acl.update_bot_rules(
        db, bot_id=LEGACY_BOT_IDS["bale"], actor_id=1,
        expected_version=1, object_type="product",
        target_ids=[100], effect="deny",
    )
    db.commit()

    async def try_begin():
        """Attempt a real service invoice without any provider network call."""
        return await ShopPaymentService.begin(
            AsyncDb(db), platform=Platform.BALE,
            platform_user_id=123, order_id=order.id,
            bale_enabled=True, telegram_fiat_enabled=False,
            telegram_stars_enabled=False, telegram_minor_multiplier=1,
        )

    with pytest.raises(PaymentRejected):
        asyncio.run(try_begin())
    assert db.scalars(select(ShopPaymentAttempt)).all() == []


def test_category_listing_hides_unauthorized_categories(db):
    """Category pages and stale category callbacks respect the same ACL."""
    acl.update_bot_rules(
        db, bot_id=LEGACY_BOT_IDS["telegram"],
        actor_id=1, expected_version=1,
        object_type="category", target_ids=[10], effect="deny",
    )
    db.commit()
    flow = CatalogFlow()
    adapter = AsyncDb(db)
    listing = asyncio.run(flow.reply(InboundEvent(
        platform=Platform.TELEGRAM, chat_id=456, user_id=456,
        text="/catalog",
    ), adapter))
    labels = [action.label for row in listing.rows for action in row]
    assert "Category A" not in labels
    assert "Category B" in labels
    stale = asyncio.run(flow.reply(InboundEvent(
        platform=Platform.TELEGRAM, chat_id=456, user_id=456,
        callback_data="shop:category:10:0", callback_query_id="cb",
    ), adapter))
    assert "Product Alpha" not in str(stale.rows)
    assert "Product Beta" not in str(stale.rows)


def test_product_catalog_write_is_not_granted_to_content_role():
    """Content editors cannot mutate cross-bot access through the API."""
    assert security.has_permission("superadmin", "bots.configure")
    assert not security.has_permission("content", "bots.configure")
    assert not security.has_permission("viewer", "bots.read")


def test_product_many2many_stale_version_is_rejected(db):
    """Product-side multi-bot edits cannot overwrite a newer bot policy."""
    telegram = LEGACY_BOT_IDS["telegram"]
    acl.update_bot_rules(
        db, bot_id=telegram, actor_id=1, expected_version=1,
        object_type="product", target_ids=[100], effect="deny",
    )
    db.commit()
    with pytest.raises(security.SecurityRejected) as failed:
        acl.update_product_bot_rules(
            db, product_id=101, actor_id=1,
            assignments=[(telegram, "allow", 1)],
        )
    assert failed.value.code == "configuration_changed"
    assert db.get(ShopBotProductRule, (telegram, 101)) is None
