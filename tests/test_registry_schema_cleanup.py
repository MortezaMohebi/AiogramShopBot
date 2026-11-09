"""Verify registry-only schema initialization and bounded legacy retirement."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text

from models.base import Base
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot, ShopBotCredential, ShopStore
from tests.schema_support import create_shop_schema

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_TABLES = frozenset({
    "users", "categories", "subcategories", "items", "carts", "cart_items",
    "buys", "buyItem", "deposits", "buttons_media", "payments", "coupons",
    "shipping_options", "reviews", "referral_bonus",
    "shop_bot_profiles", "shop_payment_rails", "shop_channel_features",
    "shop_telegram_transport", "shop_telegram_transport_changes",
    "shop_connection_configs", "shop_connection_changes", "shop_settings",
    "shop_customer_identity_links",
})


def test_deployed_models_exclude_original_tables_and_resolve_foreign_keys():
    """Legacy table removal must leave the modern FK graph complete."""
    assert not ORIGINAL_TABLES.intersection(Base.metadata.tables)
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.name in Base.metadata.tables


def test_modern_models_have_no_sqladmin_or_implicit_bot_owner():
    """Imports must work without retired UI packages or fabricated ownership."""
    for path in (ROOT / "models").glob("*.py"):
        tree = ast.parse(path.read_text())
        assert not any(
            isinstance(node, ast.ImportFrom) and node.module == "sqladmin"
            for node in ast.walk(tree)
        ), path.name
    for table in Base.metadata.tables.values():
        if "bot_id" in table.c:
            assert table.c.bot_id.default is None, table.name


def test_store_initialization_is_idempotent_without_creating_bots():
    """Creating the first Store must not register environment-owned bots."""
    from services.shop_multibot_bootstrap import _ensure_default_store

    engine = create_engine("sqlite:///:memory:")
    create_shop_schema(engine)
    try:
        with engine.begin() as connection:
            _ensure_default_store(connection)
            _ensure_default_store(connection)
            assert connection.scalar(select(ShopStore.id)) == DEFAULT_STORE_ID
            assert connection.execute(select(ShopBot.id)).all() == []
            assert connection.execute(select(ShopBotCredential.id)).all() == []
    finally:
        engine.dispose()


def _cleanup_module():
    """Load the standalone revision without a configured deployment engine."""
    path = ROOT / "migrations/versions/20261107z001_retire_original_schema.py"
    specification = importlib.util.spec_from_file_location("cleanup_revision", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_cleanup_preserves_modern_business_and_security_rows():
    """Only the original schema is dropped, including on repeated execution."""
    cleanup = _cleanup_module()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO users VALUES (7)"))
        for table in ("shop_staff", "shop_admin_profiles", "shop_products", "shop_orders"):
            connection.execute(text(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, value TEXT)'))
            connection.execute(text(f'INSERT INTO "{table}" VALUES (1, :value)'), {"value": table})
        assert cleanup.drop_original_tables(connection) == ["users"]
        assert cleanup.drop_original_tables(connection) == []
        for table in ("shop_staff", "shop_admin_profiles", "shop_products", "shop_orders"):
            assert connection.scalar(text(f'SELECT value FROM "{table}"')) == table
    engine.dispose()


def test_cleanup_rejects_external_foreign_keys_before_dropping_any_table():
    """Unknown dependencies abort the whole cleanup instead of cascading."""
    cleanup = _cleanup_module()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE categories (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE custom_orders (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id))"))
        with pytest.raises(RuntimeError, match="external foreign keys"):
            cleanup.drop_original_tables(connection)
        assert {"users", "categories", "custom_orders"} <= set(inspect(connection).get_table_names())
    engine.dispose()


def test_cleanup_never_deletes_modern_bot_owned_data():
    """Old bot ownership remains valid even when modern orders reference it."""
    cleanup = _cleanup_module()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("CREATE TABLE shop_bots (id TEXT PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE shop_orders (id INTEGER PRIMARY KEY, bot_id TEXT REFERENCES shop_bots(id))"))
        connection.execute(text("INSERT INTO shop_bots VALUES ('historical-owner')"))
        connection.execute(text("INSERT INTO shop_orders VALUES (1, 'historical-owner')"))
        cleanup.drop_original_tables(connection)
        assert connection.scalar(text("SELECT bot_id FROM shop_orders")) == "historical-owner"
        assert connection.scalar(text("SELECT id FROM shop_bots")) == "historical-owner"
    engine.dispose()


def test_historical_revisions_do_not_import_runtime_or_provider_modules():
    """Upgrade history must survive deletion of original app modules."""
    for path in (ROOT / "migrations/versions").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("models", "utils", "services", "enums")), path.name


def test_original_table_retirement_requires_explicit_migration_flag(monkeypatch):
    """An ordinary upgrade cannot silently drop populated original tables."""
    cleanup = _cleanup_module()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO users VALUES (7)"))
        monkeypatch.setattr(cleanup.op, "get_bind", lambda: connection)
        monkeypatch.setattr(
            cleanup.context, "get_x_argument", lambda **kwargs: {},
        )
        with pytest.raises(RuntimeError, match="retire_original_schema=true"):
            cleanup.upgrade()
        assert connection.scalar(text("SELECT id FROM users")) == 7
    engine.dispose()


def test_modern_identity_cannot_invent_a_bot_owner():
    """Omitted bot ownership fails at the database write boundary."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from models.shop_content import ShopIdentity
    from tests.schema_support import seed_registry

    engine = create_engine("sqlite:///:memory:")
    create_shop_schema(engine)
    try:
        with Session(engine) as session:
            seed_registry(session)
            session.commit()
            session.add(ShopIdentity(
                store_id=DEFAULT_STORE_ID, platform="telegram",
                platform_user_id=77,
            ))
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
            assert session.scalars(select(ShopIdentity)).all() == []
    finally:
        engine.dispose()


def test_retirement_revision_keeps_one_connected_historical_head():
    """Historical upgrade dependencies must remain resolvable after cleanup."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    configuration = Config(str(ROOT / "alembic.ini"))
    configuration.set_main_option("script_location", str(ROOT / "migrations"))
    revisions = ScriptDirectory.from_config(configuration)
    assert revisions.get_heads() == ["20261109w005"]
    assert revisions.get_revision("20261109w004").down_revision == "20261109w003"
    assert revisions.get_revision("20261109w003").down_revision == "20261109w002"
    assert revisions.get_revision("20261109w002").down_revision == "20261109w001"
    assert revisions.get_revision("20261109w001").down_revision == "20261108v001"
    assert revisions.get_revision("20261108v001").down_revision == "20261107u004"
    assert list(revisions.walk_revisions())[-1].revision == "1555220764ee"


def _settings_schema(connection):
    """Create only the minimum real tables needed for singleton migration."""
    connection.execute(text("CREATE TABLE shop_stores (id TEXT PRIMARY KEY)"))
    connection.execute(
        text("INSERT INTO shop_stores VALUES (:id)"), {"id": DEFAULT_STORE_ID},
    )
    connection.execute(text(
        "CREATE TABLE shop_store_settings (store_id TEXT PRIMARY KEY "
        "REFERENCES shop_stores(id), brand_name TEXT, welcome_message TEXT, "
        "faq_text TEXT, support_url TEXT)"
    ))
    connection.execute(text(
        "CREATE TABLE shop_settings (id INTEGER PRIMARY KEY, brand_name TEXT, "
        "welcome_message TEXT, faq_text TEXT, support_url TEXT)"
    ))
    connection.execute(text(
        "INSERT INTO shop_settings VALUES "
        "(1, 'Saved brand', 'Saved welcome', 'Saved FAQ', 'https://example.test')"
    ))


def test_cleanup_moves_singleton_content_to_store_settings():
    """Retiring the singleton must preserve all merchant-facing content."""
    cleanup = _cleanup_module()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _settings_schema(connection)
        cleanup.drop_original_tables(connection)
        row = connection.execute(text("SELECT * FROM shop_store_settings")).mappings().one()
        assert row["store_id"] == DEFAULT_STORE_ID
        assert row["brand_name"] == "Saved brand"
        assert row["welcome_message"] == "Saved welcome"
        assert row["faq_text"] == "Saved FAQ"
        assert row["support_url"] == "https://example.test"
        assert "shop_settings" not in inspect(connection).get_table_names()
    engine.dispose()


def test_settings_conflict_aborts_before_retiring_any_table():
    """An existing Store setting cannot be overwritten by old singleton text."""
    cleanup = _cleanup_module()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _settings_schema(connection)
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(
            text("INSERT INTO shop_store_settings (store_id,brand_name) VALUES (:id,'New brand')"),
            {"id": DEFAULT_STORE_ID},
        )
        with pytest.raises(RuntimeError, match="settings conflict"):
            cleanup.drop_original_tables(connection)
        assert {"users", "shop_settings"} <= set(inspect(connection).get_table_names())
        assert connection.scalar(text("SELECT brand_name FROM shop_store_settings")) == "New brand"
    engine.dispose()


def test_settings_dry_run_performs_no_writes():
    """Inspecting a proposed transfer must leave the merchant record intact."""
    cleanup = _cleanup_module()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _settings_schema(connection)
        cleanup.transfer_singleton_settings(connection)
        assert connection.execute(text("SELECT * FROM shop_store_settings")).all() == []
        assert connection.scalar(text("SELECT brand_name FROM shop_settings")) == "Saved brand"
    engine.dispose()


def test_retired_link_cleanup_preserves_modern_customer_membership():
    """A redundant link row may retire while both modern identities survive."""
    cleanup = _cleanup_module()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE shop_identities (id INTEGER PRIMARY KEY, "
            "store_id TEXT, customer_id INTEGER)"
        ))
        connection.execute(text(
            "INSERT INTO shop_identities VALUES (1,'store',9),(2,'store',9)"
        ))
        connection.execute(text(
            "CREATE TABLE shop_customer_identity_links (source_id INTEGER "
            "REFERENCES shop_identities(id), target_id INTEGER "
            "REFERENCES shop_identities(id))"
        ))
        connection.execute(text("INSERT INTO shop_customer_identity_links VALUES (1,2)"))
        cleanup.drop_original_tables(connection)
        assert connection.execute(text(
            "SELECT id, customer_id FROM shop_identities ORDER BY id"
        )).all() == [(1, 9), (2, 9)]
        assert "shop_customer_identity_links" not in inspect(connection).get_table_names()
    engine.dispose()


def test_unrepresented_historical_links_abort_before_any_table_drops():
    """Retirement must not lose a link missing from modern Customer records."""
    cleanup = _cleanup_module()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(text(
            "CREATE TABLE shop_identities (id INTEGER PRIMARY KEY, "
            "store_id TEXT, customer_id INTEGER)"
        ))
        connection.execute(text(
            "INSERT INTO shop_identities VALUES (1,'store',9),(2,'store',10)"
        ))
        connection.execute(text(
            "CREATE TABLE shop_customer_identity_links "
            "(source_id INTEGER, target_id INTEGER)"
        ))
        connection.execute(text("INSERT INTO shop_customer_identity_links VALUES (1,2)"))
        with pytest.raises(RuntimeError, match="shared Customer ownership"):
            cleanup.drop_original_tables(connection)
        assert {"users", "shop_customer_identity_links"} <= set(inspect(connection).get_table_names())
    engine.dispose()


def test_cleanup_disables_bridge_bindings_and_normalizes_fallback_without_deleting_runs():
    """Historical Runtime records stay referentially valid and cannot reenter."""
    cleanup = _cleanup_module()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE shop_workflow_bindings (id TEXT PRIMARY KEY, "
            "kind TEXT, fallback TEXT, enabled BOOLEAN)"
        ))
        connection.execute(text(
            "CREATE TABLE shop_workflow_runs (id TEXT PRIMARY KEY, "
            "binding_id TEXT REFERENCES shop_workflow_bindings(id))"
        ))
        connection.execute(text(
            "INSERT INTO shop_workflow_bindings VALUES "
            "('old','legacy_bridge','legacy',true), "
            "('modern','command','ignore',true)"
        ))
        connection.execute(text("INSERT INTO shop_workflow_runs VALUES ('run','old')"))
        cleanup.drop_original_tables(connection)
        assert connection.execute(text(
            "SELECT kind,fallback,enabled FROM shop_workflow_bindings WHERE id='old'"
        )).one() == ("legacy_bridge", "ignore", 0)
        assert connection.scalar(text(
            "SELECT enabled FROM shop_workflow_bindings WHERE id='modern'"
        )) == 1
        assert connection.scalar(text("SELECT binding_id FROM shop_workflow_runs")) == "old"
    engine.dispose()
