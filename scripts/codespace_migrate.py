"""Run real Alembic migrations and provision the one Codespaces administrator.

This helper refuses non-Codespaces databases and never prints/stores the
plaintext password in logs or Git. Existing accounts are not overwritten.
"""

from __future__ import annotations

import asyncio
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import select

REQUIRED = {
    "POSTGRES_DB": "shop_codespace",
    "DB_NAME": "shop_codespace",
    "DB_HOST": "postgres",
    "POSTGRES_USER": "shop_codespace",
    "SHOP_CAMPAIGN_DISPATCH_ENABLED": "false",
    "BALE_BROADCAST_PAID_ENABLED": "false",
    "TELEGRAM_STARS_REFUNDS_ENABLED": "false",
}


def safe_configuration() -> None:
    """Refuse startup on a non-isolated database or unsafe paid settings."""
    for key, expected in REQUIRED.items():
        if os.environ.get(key) != expected:
            raise RuntimeError(f"Unsafe Codespace migration setting: {key}")
    if len(os.environ.get("LIVE_ADMIN_PASSWORD", "")) < 16:
        raise RuntimeError("No strong admin bootstrap password was provided.")


async def create_admin() -> None:
    """Create only the first superadmin, without rotating existing accounts."""
    from db import session_maker
    from models.shop_staff import ShopStaff
    from utils.utils import hash_password

    async with session_maker() as session:
        account = await session.scalar(
            select(ShopStaff).where(ShopStaff.username == "shopadmin")
        )
        if account is None:
            session.add(
                ShopStaff(
                    username="shopadmin",
                    password_hash=hash_password(
                        os.environ["LIVE_ADMIN_PASSWORD"]
                    ),
                    role="superadmin",
                    is_active=True,
                    session_version=1,
                )
            )
            await session.commit()
            print("Codespace admin created: shopadmin (password kept private).")
        else:
            print("Existing admin preserved; password was not overwritten.")


def main() -> None:
    """Upgrade the dedicated Codespace database before the real bot starts."""
    safe_configuration()
    configuration = Config("alembic.ini")
    command.upgrade(configuration, "head")
    asyncio.run(create_admin())


if __name__ == "__main__":
    main()
