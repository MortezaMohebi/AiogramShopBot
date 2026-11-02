"""Create, disable or rotate a dashboard staff account securely.

Run only on the private application host after Alembic migrations. Passwords
are always read from a hidden prompt, never command-line arguments or logs.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import re

from sqlalchemy import func, select

from db import session_maker
from models.shop_staff import ShopStaff
from utils.utils import hash_password

VALID_ROLES = (
    "superadmin", "sales", "content", "finance", "marketing", "viewer"
)
USER_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{2,79}\Z")


async def manage_user(action: str, username: str, role: str) -> None:
    """Perform an explicit account operation using one DB transaction."""
    username = username.strip().casefold()
    if not USER_RE.fullmatch(username):
        raise ValueError("Username must be 3–80 lowercase ASCII characters.")
    if role not in VALID_ROLES:
        raise ValueError("Invalid staff role.")
    password = None
    if action in ("add", "reset-password"):
        password = getpass.getpass("New dashboard password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation or len(password) < 14:
            raise ValueError("Password confirmation failed or is too short.")
    async with session_maker() as session:
        user = await session.scalar(
            select(ShopStaff).where(ShopStaff.username == username)
            .with_for_update()
        )
        if action == "add":
            if user is not None:
                raise ValueError("The staff account already exists.")
            user = ShopStaff(
                username=username,
                role=role,
                password_hash=hash_password(password),
                is_active=True,
            )
            session.add(user)
        elif user is None:
            raise ValueError("The staff account does not exist.")
        elif action == "reset-password":
            user.password_hash = hash_password(password)
            user.session_version += 1
        elif action == "disable":
            if user.role == "superadmin" and user.is_active:
                count = await session.scalar(
                    select(func.count()).select_from(ShopStaff).where(
                        ShopStaff.role == "superadmin",
                        ShopStaff.is_active.is_(True),
                    )
                )
                if count <= 1:
                    raise ValueError("Cannot disable the last active superadmin.")
            user.is_active = False
            user.session_version += 1
        elif action == "set-role":
            if user.role == "superadmin" and role != "superadmin":
                count = await session.scalar(
                    select(func.count()).select_from(ShopStaff).where(
                        ShopStaff.role == "superadmin",
                        ShopStaff.is_active.is_(True),
                    )
                )
                if count <= 1:
                    raise ValueError("Cannot demote the last active superadmin.")
            user.role = role
            user.session_version += 1
        else:
            raise ValueError("Unsupported operation.")
        await session.commit()
    print("Staff account operation committed.")


def main() -> None:
    """Parse the requested mutation, without exposing password arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("add", "disable", "reset-password", "set-role")
    )
    parser.add_argument("username")
    parser.add_argument(
        "--role", choices=VALID_ROLES, default="viewer"
    )
    args = parser.parse_args()
    asyncio.run(manage_user(args.action, args.username, args.role))


if __name__ == "__main__":
    main()
