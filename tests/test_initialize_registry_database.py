"""Verify empty-database initialization without replaying historical revisions."""

from __future__ import annotations

import pytest
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, func, inspect, select, text

from models.base import Base
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot, ShopBotCredential, ShopStore
from models.shop_uom import ShopUom
from scripts import initialize_registry_database as initializer


def test_fresh_initialization_seeds_store_and_units_without_bots():
    """One atomic initialization creates modern schema and the current stamp."""
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.connect() as connection:
            # SQLite requires explicit BEGIN for transactional DDL. Production
            # uses PostgreSQL engine.begin(), which provides this guarantee.
            connection.exec_driver_sql("BEGIN")
            head = initializer.initialize_registry_schema(connection)
            connection.commit()
            assert set(inspect(connection).get_table_names()) == (
                set(Base.metadata.tables) | {"alembic_version"}
            )
            assert MigrationContext.configure(connection).get_current_heads() == (head,)
            assert connection.scalar(select(ShopStore.id)) == DEFAULT_STORE_ID
            assert connection.scalar(select(func.count()).select_from(ShopUom)) > 0
            assert connection.scalar(select(func.count()).select_from(ShopBot)) == 0
            assert connection.scalar(select(func.count()).select_from(ShopBotCredential)) == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("existing", ["users", "alembic_version", "custom_table"])
def test_initialization_refuses_every_existing_table(existing):
    """Initialized, historical and unrelated data all prevent fresh creation."""
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE TABLE "{existing}" (id INTEGER)'))
            connection.execute(text(f'INSERT INTO "{existing}" VALUES (7)'))
        with engine.begin() as connection:
            with pytest.raises(RuntimeError, match="completely empty"):
                initializer.initialize_registry_schema(connection)
            assert set(inspect(connection).get_table_names()) == {existing}
            assert connection.scalar(text(f'SELECT id FROM "{existing}"')) == 7
    finally:
        engine.dispose()


def test_initialization_rolls_back_schema_units_and_stamp_on_failure(monkeypatch):
    """A late failure cannot leave a partly initialized deployment behind."""
    def fail_stamp(*args, **kwargs):
        """Interrupt after modern schema and seed records have been written."""
        raise RuntimeError("injected stamp failure")

    monkeypatch.setattr(initializer, "_stamp_current_head", fail_stamp)
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            with pytest.raises(RuntimeError, match="injected stamp failure"):
                initializer.initialize_registry_schema(connection)
            connection.rollback()
            assert inspect(connection).get_table_names() == []
    finally:
        engine.dispose()
