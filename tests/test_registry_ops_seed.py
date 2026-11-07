"""Exercise isolated operational fixtures with real ORM foreign keys, offline."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from scripts.beta_qa_environment import prepare_environment

ROOT = Path(__file__).resolve().parents[1]


def test_lab_and_demo_seed_explicit_credential_free_registry_bots(tmp_path):
    """Reruns preserve scoped identities and never manufacture provider secrets."""
    target = prepare_environment(tmp_path / "qa.env")
    environment = dict(line.split("=", 1) for line in target.read_text().splitlines())
    environment.update({
        f"LAB_{role}_PASSWORD": "Synthetic-fixture-password-123!"
        for role in ("ADMIN", "CONTENT", "SALES", "MARKETING", "FINANCE", "VIEWER")
    })
    result = subprocess.run(
        [sys.executable, "-c", r'''
import asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from db import Base
from models.shop_multibot import ShopBot, ShopBotCredential
from models.shop_content import ShopIdentity, ShopOrder
from models.shop_staff_store import ShopStaffStoreAccess
from scripts import test_lab_seed, codespace_demo

async def verify():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    test_lab_seed.session_maker = sessions
    codespace_demo.session_maker = sessions
    for _repeat in range(2):
        await test_lab_seed.seed()
        await codespace_demo.seed_demo()
    async with sessions() as db:
        bots = (await db.scalars(select(ShopBot))).all()
        assert len(bots) == 4
        assert all(bot.status == "draft" and bot.runtime_owner == "registry" for bot in bots)
        assert all(bot.credential_version is None for bot in bots)
        assert await db.scalar(select(func.count()).select_from(ShopBotCredential)) == 0
        identities = (await db.scalars(select(ShopIdentity))).all()
        assert len(identities) == 2
        assert len({row.bot_id for row in identities}) == 2
        assert len({row.customer_id for row in identities}) == 2
        assert all(row.store_id and row.bot_id and row.customer_id for row in identities)
        order = (await db.scalars(select(ShopOrder))).one()
        assert order.bot_id == test_lab_seed.LAB_BOT_IDS["bale"]
        assert order.customer_id in {row.customer_id for row in identities}
        assert await db.scalar(select(func.count()).select_from(ShopStaffStoreAccess)) == 6
    await engine.dispose()
asyncio.run(verify())
'''],
        cwd=ROOT, env={**os.environ, **environment}, capture_output=True,
        text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
