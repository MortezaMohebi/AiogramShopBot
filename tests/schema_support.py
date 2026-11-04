"""Build disposable shared-shop schemas without PostgreSQL-only legacy types.

These helpers never connect to a configured server or activate a provider.
The PostgreSQL acceptance gate separately validates the full application ORM.
"""

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from models.base import Base
from models.shop_multibot import DEFAULT_STORE_ID, LEGACY_BOT_IDS, ShopBot, ShopStore


def create_shop_schema(engine: Engine) -> None:
    """Create every registered shared-shop table in one disposable test DB."""
    Base.metadata.create_all(
        engine,
        tables=[
            table for name, table in Base.metadata.tables.items()
            if name.startswith("shop_")
        ],
    )


def seed_legacy_registry(session: Session) -> None:
    """Provide the trusted legacy Store/Bot records required by old fixtures."""
    if session.get(ShopStore, DEFAULT_STORE_ID) is None:
        session.add(ShopStore(
            id=DEFAULT_STORE_ID, slug="default", name="Test Store", state="active",
        ))
        session.flush()
    for platform, bot_id in LEGACY_BOT_IDS.items():
        if session.get(ShopBot, bot_id) is None:
            session.add(ShopBot(
                id=bot_id, store_id=DEFAULT_STORE_ID, slug=f"legacy-{platform}",
                name=f"Test {platform}", platform=platform,
                status="legacy", runtime_owner="legacy", version=1,
                credential_version=1,
            ))
    session.flush()
    seed_test_units(session)


def seed_test_units(session: Session) -> None:
    """Seed units for explicitly created fixture Stores, without live bots."""
    from services.shop_uom import seed_store_units

    for store_id in session.scalars(select(ShopStore.id)).all():
        seed_store_units(session, store_id)
    session.flush()
