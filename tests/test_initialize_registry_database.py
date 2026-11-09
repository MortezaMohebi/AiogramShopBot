"""Verify empty-database initialization without replaying historical revisions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, func, inspect, select, text

from models.base import Base
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot, ShopBotCredential, ShopStore
from models.shop_uom import ShopUom
from scripts import initialize_registry_database as initializer


def _postgres_upgrade(*, stamp=False, current=(), destination="head"):
    scripts, head = initializer._current_migration_head()
    step = SimpleNamespace(
        source_revision_ids=(), destination_revision_ids=(head,),
        is_migration=not stamp, is_upgrade=True,
    )
    return SimpleNamespace(
        connection=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        as_sql=False,
        script=scripts,
        opts={
            "destination_rev": destination,
            "fn": lambda *_: [SimpleNamespace(info=step)],
        },
        get_current_heads=lambda: current,
    )


def test_online_postgresql_upgrade_to_head_uses_registry_initializer(monkeypatch):
    migration = _postgres_upgrade()
    initialized = []
    monkeypatch.setattr(initializer, "initialize_registry_schema", initialized.append)
    assert initializer.initialize_postgresql_upgrade(migration)
    assert initialized == [migration.connection]


@pytest.mark.parametrize("options", [
    {"stamp": True},
    {"current": ("20261108v001",)},
    {"destination": "20261108v001"},
    {"destination": None},
])
def test_other_alembic_operations_keep_their_migration_plan(monkeypatch, options):
    def unexpected_initializer(_):
        pytest.fail("This operation must not initialize the database")

    monkeypatch.setattr(initializer, "initialize_registry_schema", unexpected_initializer)
    assert not initializer.initialize_postgresql_upgrade(_postgres_upgrade(**options))


def test_unversioned_nonempty_database_still_refuses_to_initialize(monkeypatch):
    def refuse(_):
        raise initializer.RegistryDatabaseNotEmpty("existing tables")

    monkeypatch.setattr(initializer, "initialize_registry_schema", refuse)
    with pytest.raises(initializer.RegistryDatabaseNotEmpty, match="existing tables"):
        initializer.initialize_postgresql_upgrade(_postgres_upgrade())


def test_concurrent_initializer_leaves_the_second_upgrade_on_normal_path(monkeypatch):
    migration = _postgres_upgrade()
    _, head = initializer._current_migration_head()
    snapshots = iter([(), (head,)])
    migration.get_current_heads = lambda: next(snapshots)

    def completed_while_waiting(_):
        raise initializer.RegistryDatabaseNotEmpty("existing tables")

    monkeypatch.setattr(initializer, "initialize_registry_schema", completed_while_waiting)
    assert not initializer.initialize_postgresql_upgrade(migration)


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
