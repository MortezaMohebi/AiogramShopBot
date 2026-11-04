"""Ensure unit fixtures include all Store/Bot-owned backend dependencies."""

from sqlalchemy import create_engine, inspect

from models.base import Base


def test_shared_shop_fixture_builds_the_complete_registered_schema():
    """Old fixture table allowlists must not omit new commerce policies."""
    from tests.schema_support import create_shop_schema

    engine = create_engine("sqlite:///:memory:")
    try:
        create_shop_schema(engine)
        expected = {
            name for name in Base.metadata.tables if name.startswith("shop_")
        }
        assert set(inspect(engine).get_table_names()) == expected
    finally:
        engine.dispose()
