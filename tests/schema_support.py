"""Build isolated modern Store/Bot-owned schemas and explicit test fixtures.

These helpers never connect to a configured server or activate a provider.
Catalog access is granted explicitly after a test creates its products.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from channels.contracts import Platform
from models.base import Base
from models.shop_bot_catalog_acl import ShopBotProductRule
from models.shop_content import Product, ShopIdentity
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot, ShopStore
from models.shop_store_commerce import ShopBotCommercePolicy, ShopStoreCustomer

TEST_BOT_IDS = {
    "telegram": "00000000-0000-4000-8000-000000000101",
    "bale": "00000000-0000-4000-8000-000000000102",
}


def create_shop_schema(engine: Engine) -> None:
    """Create the complete registered application schema in a disposable DB."""
    Base.metadata.create_all(engine)


def seed_registry(session: Session) -> None:
    """Create explicitly active registry fixtures without provider credentials."""
    if session.get(ShopStore, DEFAULT_STORE_ID) is None:
        session.add(ShopStore(
            id=DEFAULT_STORE_ID, slug="default", name="Test Store", state="active",
        ))
        session.flush()
    for platform, bot_id in TEST_BOT_IDS.items():
        if session.get(ShopBot, bot_id) is None:
            session.add(ShopBot(
                id=bot_id, store_id=DEFAULT_STORE_ID,
                slug=f"test-{platform}", name=f"Test {platform}",
                platform=platform, status="active", runtime_owner="registry",
                version=1, credential_version=1,
            ))
            session.flush()
        if session.get(ShopBotCommercePolicy, bot_id) is None:
            session.add(ShopBotCommercePolicy(
                bot_id=bot_id, cart_enabled=True, credit_enabled=True,
                credit_label="Test credit", version=1,
            ))
    session.flush()
    seed_test_units(session)


def allow_test_catalog(
    session: Session, bot_ids: Iterable[str] = TEST_BOT_IDS.values(),
) -> None:
    """Allow existing same-Store products without overriding explicit denies."""
    session.flush()
    for bot_id in bot_ids:
        bot = session.get(ShopBot, bot_id)
        if bot is None:
            raise ValueError("Create the test registry bot before catalog grants")
        products = session.scalars(
            select(Product.id).where(Product.store_id == bot.store_id)
        )
        for product_id in products:
            if session.get(ShopBotProductRule, (bot_id, product_id)) is None:
                session.add(ShopBotProductRule(
                    bot_id=bot_id, product_id=product_id, effect="allow",
                ))
    session.flush()


def seed_customer(
    session: Session, platform: Platform | str, user_id: int,
    *, consent: bool = False, blocked: bool = False,
) -> ShopIdentity:
    """Enroll one fixture identity with an explicit bot and Store Customer."""
    provider = Platform(platform)
    bot_id = TEST_BOT_IDS[provider.value]
    bot = session.get(ShopBot, bot_id)
    if bot is None:
        raise ValueError("Create the test registry bot before customer enrollment")
    identity = session.scalar(select(ShopIdentity).where(
        ShopIdentity.bot_id == bot_id,
        ShopIdentity.platform_user_id == user_id,
    ))
    if identity is None:
        identity = ShopIdentity(
            store_id=bot.store_id, bot_id=bot_id, platform=provider.value,
            platform_user_id=user_id, allow_announcements=consent,
            is_blocked=blocked,
        )
        session.add(identity)
    if identity.customer_id is None:
        customer = ShopStoreCustomer(store_id=bot.store_id)
        session.add(customer)
        session.flush()
        identity.customer_id = customer.id
    session.flush()
    return identity


def test_bot_context(platform: Platform | str):
    """Return an explicit test authentication context for one fixture bot."""
    from services.shop_bot_context import BotContext

    provider = Platform(platform)
    return BotContext(
        bot_id=TEST_BOT_IDS[provider.value], store_id=DEFAULT_STORE_ID,
        platform=provider, provider_bot_id=None, status="active",
        runtime_owner="registry", credential_version=1, registry_version=1,
    )


# This factory is imported by test modules but is not itself a pytest test.
test_bot_context.__test__ = False


def seed_test_units(session: Session) -> None:
    """Seed units for explicitly created fixture Stores, without live bots."""
    from services.shop_uom import seed_store_units

    for store_id in session.scalars(select(ShopStore.id)).all():
        seed_store_units(session, store_id)
    session.flush()
