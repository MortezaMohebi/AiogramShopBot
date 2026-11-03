from contextlib import asynccontextmanager
from pathlib import Path
import os

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from typing import Any

from sqlalchemy import text, Result, CursorResult
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection, AsyncSession, create_async_engine,
)
from sqlalchemy.orm import sessionmaker, Session

import config
from models.base import Base
from models.shop_staff import ShopStaff
from models.shop_staff_security import (
    ShopPasswordPolicy, ShopStaffInvitation, ShopStaffPasswordReset,
)
from models.shop_channel_features import ShopChannelFeature
from models.shop_customer_crm import (
    ShopCustomerProfile, ShopCustomerNote, ShopCustomerConsentEvent,
    ShopCustomerAudit, ShopCustomerRetentionPolicy,
)
from models.shop_staff_preferences import ShopStaffPreferences
from models.shop_bot_profile import ShopBotProfile
from models.shop_payment_rail import ShopPaymentRail
from models.shop_customer_links import ShopCustomerLinkRequest, ShopCustomerIdentityLink
from models.shop_staff_state import ShopStaffState
from models.shop_multibot import (
    ShopStore, ShopBot, ShopBotCredential, ShopBotRegistryEvent,
)
from models.shop_bot_operations import ShopBotOperations, ShopBotOperationsEvent
from models.shop_telegram_transport import (
    ShopTelegramTransport, ShopTelegramTransportChange,
)
from models.shop_product_visibility import ShopProductVisibility
from models.shop_delivery import ShopRemoteFile, ShopInboundUpdate
from models.shop_engagement import (
    ShopWalletAccount, ShopWalletEntry, ShopReferralProfile,
    ShopReferralAttribution, ShopReferralPolicy, ShopReferralReward,
    ShopCampaign, ShopCampaignDelivery, ShopCampaignMedia,
    ShopBroadcastRateSlot, ShopCampaignAudit,
    ShopBroadcastWorkerHeartbeat,
)

"""
Imports of these models are needed to correctly create tables in the database.
For more information see https://stackoverflow.com/questions/7478403/sqlalchemy-classes-across-files
"""
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
from models.shop_checkout import (
    ShopCart, ShopCartItem, ShopShippingMethod, ShopCoupon, ShopOrderLine,
    ShopOrderReviewAudit,
)
from models.shop_content import Product, ProductMedia, ShopCategory, ShopIdentity, ShopOrder, ShopSettings, Testimonial
from models.item import Item
from models.cart import Cart
from models.cartItem import CartItem
from models.user import User
from models.buy import Buy
from models.buyItem import BuyItem
from models.category import Category
from models.subcategory import Subcategory
from models.deposit import Deposit
from models.button_media import ButtonMedia
from models.payment import Payment
from models.coupon import Coupon
from models.shipping_option import ShippingOption
from models.review import Review
from models.referral import ReferralBonus

url = f"postgresql+asyncpg://{config.DB_USER}:{config.DB_PASS}@{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}"
# Do not log SQL parameters containing orders and private customer data.
engine = create_async_engine(url, echo=config.DB_SQL_ECHO)
session_maker = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def get_db_session() -> AsyncSession | Session:
    session = None
    try:
        async with session_maker() as async_session:
            session = async_session
            yield session
    finally:
        if isinstance(session, AsyncSession):
            await session.close()
        elif isinstance(session, Session):
            session.close()


async def session_execute(stmt, session: AsyncSession | Session) -> Result[Any] | CursorResult[Any]:
    if isinstance(session, AsyncSession):
        query_result = await session.execute(stmt)
        return query_result
    else:
        query_result = session.execute(stmt)
        return query_result


async def session_flush(session: AsyncSession | Session) -> None:
    if isinstance(session, AsyncSession):
        await session.flush()
    else:
        session.flush()


async def session_commit(session: AsyncSession | Session) -> None:
    if isinstance(session, AsyncSession):
        await session.commit()
    else:
        session.commit()


async def check_all_tables_exist(session: AsyncSession | Session, schema: str = "public"):
    for table in Base.metadata.tables.values():
        sql_query = text("""
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = :schema
              AND table_name = :table_name
            LIMIT 1;
        """)

        params = {
            "schema": schema,
            "table_name": table.name,
        }

        if isinstance(session, AsyncSession):
            result = await session.execute(sql_query, params)
            if result.scalar() is None:
                return False
        else:
            result = session.execute(sql_query, params)
            if result.scalar() is None:
                return False

    return True


async def verify_codespace_schema(connection: AsyncConnection) -> None:
    """Require all ORM tables/columns in the isolated Codespaces PostgreSQL.

    This checks read-only catalog metadata; it never creates, alters, drops,
    stamps or migrates any table. A newer model with missing columns fails
    closed rather than silently modifying a database containing data.
    """
    actual_database = await connection.scalar(
        text("SELECT current_database()")
    )
    if actual_database != "shop_codespace":
        raise RuntimeError(
            "Refusing schema verification outside the Codespaces database."
        )

    result = await connection.execute(
        text(
            "SELECT table_name, column_name "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        )
    )
    actual = {(table, column) for table, column in result.all()}
    expected = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
    }
    if not expected:
        raise RuntimeError("SQLAlchemy model metadata is empty.")

    missing = expected - actual
    if missing:
        # Omit customer values and SQL metadata in the error response.
        raise RuntimeError(
            "Codespaces schema is incomplete or outdated: "
            f"{len(missing)} expected columns are missing. "
            "Inspect database state before an explicit reset."
        )


async def create_db_and_tables() -> None:
    """Verify the installed schema using its exact deployment policy.

    The disposable Codespaces stack uses an ORM-created fresh schema without
    historical revisions. Production retains its strict Alembic-head checks.
    Neither path mutates schemas during normal bot startup.
    """
    if os.environ.get("CODESPACE_FRESH_SCHEMA") == "true":
        # A flag alone cannot bypass Production migration protection.
        required = {
            "POSTGRES_DB": "shop_codespace",
            "POSTGRES_USER": "shop_codespace",
            "DB_HOST": "postgres",
            "SHOP_CAMPAIGN_DISPATCH_ENABLED": "false",
            "BALE_BROADCAST_PAID_ENABLED": "false",
        }
        if any(
            os.environ.get(name) != expected
            for name, expected in required.items()
        ):
            raise RuntimeError(
                "Codespaces fresh-schema mode refused: unsafe environment."
            )
        async with engine.connect() as connection:
            await verify_codespace_schema(connection)
        return

    root = Path(__file__).resolve().parent
    configuration = AlembicConfig(str(root / "alembic.ini"))
    configuration.set_main_option("script_location", str(root / "migrations"))
    expected = set(ScriptDirectory.from_config(configuration).get_heads())
    if not expected:
        raise RuntimeError("Alembic revision scripts are missing.")

    try:
        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT version_num FROM alembic_version")
            )
            current = set(result.scalars().all())
            if current != expected:
                raise RuntimeError(
                    "Database migrations are pending. "
                    "Back up the database and run: alembic upgrade head."
                )
            if not await check_all_tables_exist(session):
                raise RuntimeError(
                    "Database schema is incomplete despite an Alembic head. "
                    "Inspect the database before starting the bot."
                )
    except DBAPIError:
        raise RuntimeError(
            "Database is unreachable or Alembic is not initialized. "
            "Provision/migrate it before bot startup."
        ) from None
