"""Create the first dashboard owner from a private terminal exactly once."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hmac
import re
import time

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from models.shop_multibot import DEFAULT_STORE_ID, ShopStore
from models.shop_staff import ShopStaff
from models.shop_staff_store import (
    ShopStaffStoreAccess, ShopStaffStorePreference,
)
from services.shop_staff_lifecycle import USERNAME_RE, validate_password
from utils.utils import hash_password

SETUP_CODE_TTL = 15 * 60
SETUP_CODE_PATTERN = re.compile(r"([0-9]{10})\.([a-f0-9]{64})")


def issue_browser_code(secret: str, *, now: int | None = None) -> str:
    """Sign a short-lived setup code using the installation's private key."""
    if len(secret) < 32:
        raise ValueError("Configure the dashboard bridge before browser setup.")
    timestamp = str(int(time.time()) if now is None else now)
    signature = hmac.digest(
        secret.encode(), f"shop-first-owner-v1\n{timestamp}".encode(), "sha256",
    ).hex()
    return f"{timestamp}.{signature}"


def verify_browser_code(secret: str, code: str, *, now: int | None = None) -> bool:
    """Reject malformed, expired, future and cross-installation setup codes."""
    match = SETUP_CODE_PATTERN.fullmatch(code)
    if not match or len(secret) < 32:
        return False
    issued = int(match[1])
    current = int(time.time()) if now is None else now
    return (
        0 <= current - issued < SETUP_CODE_TTL
        and hmac.compare_digest(code, issue_browser_code(secret, now=issued))
    )


async def lock_owner_setup(db: AsyncSession) -> None:
    """Serialize first owner creation with the PostgreSQL schema bootstrap."""
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(90211003)"))


async def print_browser_code() -> None:
    """Issue the browser code only on the private host of an empty installation."""
    import config
    from db import session_maker

    async with session_maker() as db:
        if await db.scalar(select(ShopStaff.id).limit(1)) is not None:
            raise ValueError("Staff is already initialized. Sign in to the dashboard.")
    print("First owner setup code (valid for 15 minutes):")
    print(issue_browser_code(config.NEXT_ADMIN_BRIDGE_SECRET))


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
        await lock_owner_setup(db)
        await db.run_sync(lambda sync: create_first_owner(sync, username, password))
        await db.commit()
    print("First owner created. Continue in the private dashboard.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-code", action="store_true")
    options = parser.parse_args()
    asyncio.run(print_browser_code() if options.browser_code else main())
