"""Exercise Registry initialization/retirement in a dedicated PostgreSQL cluster.

The cluster must advertise the exact acceptance-only marker; this program
refuses ordinary development and production databases before making changes.
No Provider or administration credentials are used or transmitted.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from db import engine
from models.base import Base
from models.shop_admin_control import AdminProfile
from models.shop_content import Product, ShopIdentity, ShopOrder
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot
from models.shop_staff import ShopStaff
from models.shop_store_commerce import ShopStoreCustomer
from models.shop_uom import default_unit_id
from scripts.codespace_bootstrap import bootstrap_schema
from scripts.initialize_registry_database import initialize_registry_schema
from scripts import initialize_registry_database as initializer
from scripts.legacy_schema_cleanup import _load_cleanup_revision, cleanup


async def main() -> None:
    """Verify atomic PostgreSQL DDL and preservation with isolated fake rows."""
    if os.environ.get("SHOP_REGISTRY_RETIREMENT_QA") != "1":
        raise RuntimeError("Dedicated retirement acceptance flag required")
    checks: list[str] = []

    def passed(name: str) -> None:
        checks.append(name)
        print("PASS", name, flush=True)

    try:
        async with engine.begin() as connection:
            marker = await connection.scalar(text("SHOW cluster_name"))
            database = await connection.scalar(text("SELECT current_database()"))
            if marker != "registry_retirement_qa" or database != "shop_codespace":
                raise RuntimeError("Refusing an unmarked database/cluster")
        original_stamp = initializer._stamp_current_head

        def interrupted_stamp(*_args):
            raise RuntimeError("qa_injected_late_failure")

        initializer._stamp_current_head = interrupted_stamp
        try:
            async with engine.begin() as connection:
                await connection.run_sync(initialize_registry_schema)
        except RuntimeError as error:
            assert str(error) == "qa_injected_late_failure"
        else:
            raise AssertionError("Injected late initialization failure was ignored")
        finally:
            initializer._stamp_current_head = original_stamp
        async with engine.connect() as connection:
            assert await connection.run_sync(lambda c: inspect(c).get_table_names()) == []
        passed("Late initialization failure rolls back PostgreSQL DDL, seeds and migration stamp")

        async def initialize_once():
            async with engine.begin() as connection:
                return await connection.run_sync(initialize_registry_schema)

        outcomes = await asyncio.gather(initialize_once(), initialize_once(), return_exceptions=True)
        successes = [value for value in outcomes if isinstance(value, str)]
        rejections = [value for value in outcomes if isinstance(value, RuntimeError)]
        assert len(successes) == len(rejections) == 1, [type(value).__name__ for value in outcomes]
        assert "empty database" in str(rejections[0])
        head = successes[0]
        passed("Concurrent initializers elect one creator; the other refuses without partial reset")
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == head
            assert await connection.scalar(text("SELECT count(*) FROM shop_bots")) == 0
            assert await connection.scalar(text("SELECT count(*) FROM shop_bot_credentials")) == 0
            tables = await connection.run_sync(lambda c: set(inspect(c).get_table_names()))
            assert tables == set(Base.metadata.tables) | {"alembic_version"}
        passed("Fresh PostgreSQL initializes only current schema, Store/UoM and migration head; zero bots/credentials")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(initialize_registry_schema)
        except RuntimeError as error:
            assert "empty database" in str(error)
        else:
            raise AssertionError("Repeated fresh initialization was accepted")
        passed("Nonempty fresh initialization refuses without resetting data")

        # Convert this dedicated disposable fixture to the unversioned
        # Codespaces mode to test its separate idempotent bootstrap contract.
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE alembic_version RESTRICT"))
        await bootstrap_schema()
        await bootstrap_schema()
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM shop_bots")) == 0
            assert await connection.scalar(text("SELECT count(*) FROM shop_uoms")) > 0
        passed("Codespaces bootstrap twice retains Store/UoM and creates zero bots")

        registry_ids = [str(uuid4()), str(uuid4())]
        historical_id = str(uuid4())

        def seed_modern(connection) -> None:
            with Session(bind=connection) as session:
                session.add(ShopStaff(id=9001, username="retirement-owner", password_hash="qa-preserved-hash",
                                      role="superadmin", is_active=True, session_version=7))
                session.flush()
                session.add(AdminProfile(staff_id=9001, mfa_secret="qa-preserved-encrypted-MFA",
                                         last_totp_step=1234, recovery_hashes='["qa-recovery-hash"]'))
                for platform, bot_id in zip(("telegram", "bale"), registry_ids):
                    session.add(ShopBot(id=bot_id, store_id=DEFAULT_STORE_ID, slug=f"qa-{platform}",
                                        name=f"QA {platform}", platform=platform, status="draft",
                                        runtime_owner="registry", version=1))
                session.add(ShopBot(id=historical_id, store_id=DEFAULT_STORE_ID, slug="qa-audit-owner",
                                    name="QA historical order owner", platform="telegram", status="legacy",
                                    runtime_owner="legacy", version=1))
                session.add(ShopStoreCustomer(id=501, store_id=DEFAULT_STORE_ID, display_name="QA customer"))
                session.flush()
                for index, platform in enumerate(("telegram", "bale")):
                    session.add(ShopIdentity(id=801 + index, store_id=DEFAULT_STORE_ID, customer_id=501,
                                             bot_id=registry_ids[index], platform=platform, platform_user_id=77 + index))
                product = Product(store_id=DEFAULT_STORE_ID, uom_id=default_unit_id(DEFAULT_STORE_ID),
                                  name="QA retained product", sku="QA-RETAIN-001",
                                  description="QA retained text", price=7000, stock_quantity=2)
                session.add(product)
                session.flush()
                session.add(ShopOrder(store_id=DEFAULT_STORE_ID, bot_id=historical_id, platform="telegram",
                                     platform_user_id=77, chat_id=77, product_id=product.id,
                                     product_name_snapshot=product.name, quantity=1, unit_price_irr=7000,
                                     total_irr=7000, provider="store_credit", status="pending_review",
                                     invoice_payload="retirement-qa-order"))
                session.flush()

        async with engine.begin() as connection:
            await connection.run_sync(seed_modern)

        async def preserved() -> dict[str, list[str]]:
            result: dict[str, list[str]] = {}
            async with engine.connect() as connection:
                for table in ("shop_staff", "shop_admin_profiles", "shop_stores", "shop_products",
                              "shop_orders", "shop_bots", "shop_store_customers", "shop_identities"):
                    result[table] = list((await connection.scalars(text(
                        f"SELECT to_jsonb(t)::text FROM {table} AS t ORDER BY to_jsonb(t)::text"
                    ))).all())
            return result

        before = await preserved()
        revision = _load_cleanup_revision()
        async with engine.begin() as connection:
            quote = connection.dialect.identifier_preparer.quote
            for name in revision.RETIRED_TABLE_NAMES:
                suffix = ", brand_name text, welcome_message text, faq_text text, support_url text" if name == "shop_settings" else ""
                suffix += ", source_id bigint, target_id bigint" if name == "shop_customer_identity_links" else ""
                await connection.execute(text(f"CREATE TABLE public.{quote(name)} (id integer PRIMARY KEY{suffix})"))
            await connection.execute(text("INSERT INTO users(id) VALUES (1)"))
            await connection.execute(text("ALTER TABLE buys ADD COLUMN user_id integer REFERENCES users(id)"))
            await connection.execute(text('ALTER TABLE "buyItem" ADD COLUMN buy_id integer REFERENCES buys(id)'))
            await connection.execute(text("INSERT INTO shop_settings(id,brand_name,welcome_message) VALUES (1,'QA merchant','QA welcome')"))
            await connection.execute(text("CREATE SCHEMA retirement_external"))
            await connection.execute(text("CREATE TABLE retirement_external.inbound(id integer REFERENCES public.users(id))"))
        try:
            await cleanup(apply=True)
        except RuntimeError as error:
            assert "external foreign keys" in str(error)
        else:
            raise AssertionError("External foreign key did not block retirement")
        assert await preserved() == before
        passed("Cross-schema inbound foreign key aborts PostgreSQL retirement without partial data loss")
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE retirement_external.inbound RESTRICT"))
            await connection.execute(text("DROP SCHEMA retirement_external RESTRICT"))
        names = await cleanup(apply=False)
        assert len(names) == 24 and await preserved() == before
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM shop_store_settings")) == 0
        passed("Dry run finds 24 retired tables and changes neither data nor merchant settings")
        async with engine.begin() as connection:
            await connection.execute(text("INSERT INTO shop_store_settings(store_id,brand_name) VALUES (:id,'QA current')"), {"id": DEFAULT_STORE_ID})
        try:
            await cleanup(apply=True)
        except RuntimeError as error:
            assert "conflict" in str(error)
        else:
            raise AssertionError("Conflicting merchant settings did not block retirement")
        passed("Conflicting merchant text blocks the complete retirement transaction")
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE shop_settings SET brand_name='QA current' WHERE id=1"))
            await connection.execute(text("INSERT INTO shop_customer_identity_links(id,source_id,target_id) VALUES (1,801,999999)"))
        try:
            await cleanup(apply=True)
        except RuntimeError as error:
            assert "Customer ownership" in str(error)
        else:
            raise AssertionError("Unconverted customer link did not block retirement")
        passed("Unconverted customer link blocks retirement")
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE shop_customer_identity_links SET target_id=802 WHERE id=1"))
        removed = await cleanup(apply=True)
        assert len(removed) == 24 and await preserved() == before
        async with engine.connect() as connection:
            assert not await connection.run_sync(revision.existing_original_tables)
            assert await connection.scalar(text("SELECT welcome_message FROM shop_store_settings WHERE store_id=:id"), {"id": DEFAULT_STORE_ID}) == "QA welcome"
        passed("Transactional DROP RESTRICT removes 24 tables while preserving owner/MFA/Store/products/orders/audit bot/customer membership")
        assert await cleanup(apply=True) == []
        passed("Repeated retirement is idempotent")
        output = Path(os.environ.get("REGISTRY_QA_EVIDENCE", "/tmp/registry-retirement-evidence.json"))
        output.write_text(json.dumps({"status": "PASS", "checks": checks}, indent=2))
        print(json.dumps({"status": "PASS", "checks": len(checks)}), flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
