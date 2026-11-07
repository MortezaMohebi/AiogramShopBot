"""Create the first dashboard owner from a private terminal exactly once."""

from __future__ import annotations

import asyncio
import getpass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from models.shop_multibot import DEFAULT_STORE_ID, ShopStore
from models.shop_staff import ShopStaff
from models.shop_staff_store import (
    ShopStaffStoreAccess, ShopStaffStorePreference,
)
from services.shop_staff_lifecycle import USERNAME_RE, validate_password
from utils.utils import hash_password


def create_first_owner(db: Session, username: str, password: str) -> ShopStaff:
    """Provision only on an empty staff register inside the caller's lock."""
    normalized = username.strip().casefold()
    if not USERNAME_RE.fullmatch(normalized):
        raise ValueError("Username must be 3–80 lowercase ASCII characters.")
    validate_password(db, password)
    if db.scalar(select(ShopStaff.id).limit(1)) is not None:
        raise ValueError("Staff is already initialized; invite users from the dashboard.")
    if db.get(ShopStore, DEFAULT_STORE_ID) is None:
        raise ValueError("Initialize the Store schema before owner setup.")
    owner = ShopStaff(
        username=normalized, password_hash=hash_password(password),
        role="superadmin", is_active=True,
    )
    db.add(owner)
    db.flush()
    db.add(ShopStaffStoreAccess(
        staff_id=owner.id, store_id=DEFAULT_STORE_ID,
        access_level="manager", is_active=True, changed_by=owner.id,
    ))
    db.add(ShopStaffStorePreference(
        staff_id=owner.id, default_store_id=DEFAULT_STORE_ID, version=1,
    ))
    db.flush()
    return owner


async def main() -> None:
    """Ask the owner for credentials without passing them in argv or env."""
    from db import session_maker

    username = input("First owner username: ").strip()
    password = getpass.getpass("First owner password: ")
    if password != getpass.getpass("Confirm password: "):
        raise ValueError("Password confirmation does not match.")
    async with session_maker() as db:
        # A transaction-scoped PostgreSQL lock serializes two simultaneous
        # setup attempts even when the staff table is initially empty.
        if db.bind.dialect.name == "postgresql":
            await db.execute(text("SELECT pg_advisory_xact_lock(90211003)"))
        await db.run_sync(lambda sync: create_first_owner(sync, username, password))
        await db.commit()
    print("First owner created. Continue in the private dashboard.")


if __name__ == "__main__":
    asyncio.run(main())
