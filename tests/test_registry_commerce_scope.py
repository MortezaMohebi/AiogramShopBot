"""Registry commerce rejects unauthenticated or inconsistent bot ownership."""

import pytest

from channels.contracts import InboundEvent, Platform
from services.shop_channel_catalog import CatalogFlow
from services.shop_identity import register_customer
from services.shop_channel_features import get_features
from services.shop_payment_rails import rail_enabled


@pytest.mark.asyncio
async def test_identity_requires_explicit_authenticated_bot():
    """A provider name alone must never choose an identity owner."""
    with pytest.raises(ValueError, match="bot"):
        await register_customer(
            None,
            platform=Platform.TELEGRAM,
            platform_user_id=101,
        )


@pytest.mark.asyncio
async def test_catalog_requires_authenticated_context():
    """Missing context fails before any catalog or settings query."""
    event = InboundEvent(
        platform=Platform.TELEGRAM,
        user_id=101,
        chat_id=101,
        callback_data="shop:list:0",
    )
    with pytest.raises(ValueError, match="bot"):
        await CatalogFlow().reply(event, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("service", ["features", "rails"])
async def test_commerce_policy_requires_explicit_bot(service):
    """Global provider settings cannot select or authorize a bot."""
    with pytest.raises(ValueError, match="bot"):
        if service == "features":
            await get_features(None, "telegram")
        else:
            await rail_enabled(None, "telegram", "store_credit")


@pytest.mark.asyncio
@pytest.mark.parametrize("service", ["updates", "media", "wallet", "refund"])
async def test_transport_and_money_operations_require_explicit_owner(service):
    """No receipt, asset cache or financial lookup infers a bot by platform."""
    from services.shop_media_delivery import cached_file_id
    from services.shop_refunds import ShopRefundService
    from services.shop_updates import claim_update
    from services.shop_wallet import ShopWalletService

    with pytest.raises(ValueError, match="bot"):
        if service == "updates":
            await claim_update(
                platform=Platform.TELEGRAM,
                token="test-token-long-enough",
                update_id=1,
            )
        elif service == "media":
            await cached_file_id(
                platform="telegram",
                bot_key="test-namespace",
                storage_key="private-key",
                kind="document",
            )
        elif service == "wallet":
            await ShopWalletService.balance(None, Platform.TELEGRAM, 101)
        else:
            await ShopRefundService.request(
                None,
                platform=Platform.TELEGRAM,
                payer_id=101,
                order_id=1,
                reason="Customer requested refund",
            )


@pytest.mark.asyncio
async def test_registry_bot_platform_mismatch_cannot_register_identity():
    """An explicit Telegram Bot ID cannot acquire a Bale customer identity."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from models.shop_content import ShopIdentity
    from tests.schema_support import TEST_BOT_IDS, create_shop_schema, seed_registry
    from tests.test_shared_cart import AsyncDatabase

    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_shop_schema(engine)
    try:
        with Session(engine) as session:
            seed_registry(session)
            with pytest.raises(ValueError, match="bot"):
                await register_customer(
                    AsyncDatabase(session),
                    platform=Platform.BALE,
                    platform_user_id=101,
                    bot_id=TEST_BOT_IDS["telegram"],
                )
            assert session.scalars(select(ShopIdentity)).all() == []
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_registry_features_do_not_inherit_another_bots_policy():
    """A second bot remains denied when its peer enables Cart and Credit."""
    from uuid import uuid4

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from models.shop_multibot import DEFAULT_STORE_ID, ShopBot
    from tests.schema_support import create_shop_schema, seed_registry
    from tests.test_shared_cart import AsyncDatabase

    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_shop_schema(engine)
    try:
        with Session(engine) as session:
            seed_registry(session)
            bot = ShopBot(
                id=str(uuid4()),
                store_id=DEFAULT_STORE_ID,
                slug="separate-bot",
                name="Separate Bot",
                platform="telegram",
                status="active",
                runtime_owner="registry",
                credential_version=1,
                version=1,
            )
            session.add(bot)
            session.flush()
            features = await get_features(
                AsyncDatabase(session),
                "telegram",
                bot_id=bot.id,
            )
            assert features.cart_enabled is False
            assert features.store_credit_enabled is False
            assert (
                await rail_enabled(
                    AsyncDatabase(session),
                    "telegram",
                    "store_credit",
                    bot_id=bot.id,
                )
                is False
            )
    finally:
        engine.dispose()
