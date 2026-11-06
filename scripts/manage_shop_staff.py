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
from sqlalchemy.orm import Session

from db import session_maker
from models.shop_staff import ShopStaff
from utils.utils import hash_password, verify_password

VALID_ROLES = (
    "superadmin", "sales", "content", "finance", "marketing", "viewer"
)
USER_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{2,79}\Z")


def recover_admin_mfa(db: Session, username: str, password: str) -> None:
    """Reset one active admin's MFA after owner-terminal password proof.

    The caller commits the transaction. All sessions are revoked; the normal
    login policy then requires this administrator to enroll a new authenticator.
    """
    from services import shop_admin_security as security

    user = db.scalar(select(ShopStaff).where(
        ShopStaff.username == username,
    ).with_for_update())
    if (user is None or not user.is_active or user.role != "superadmin"
            or not verify_password(password, user.password_hash)):
        raise ValueError("Active administrator and current password required.")
    profile = security.profile_for(db, user.id)
    if not profile.mfa_secret and not profile.pending_mfa:
        raise ValueError("Administrator has no MFA enrollment to reset.")
    security.disable_mfa(db, profile)
    user.session_version += 1
    security.revoke_others(db, user.id, None)
    security.audit(db, user.id, "mfa.owner_recovery")


async def manage_user(action: str, username: str, role: str) -> None:
    """Perform an explicit account operation using one DB transaction."""
    username = username.strip().casefold()
    if not USER_RE.fullmatch(username):
        raise ValueError("Username must be 3–80 lowercase ASCII characters.")
    if role not in VALID_ROLES:
        raise ValueError("Invalid staff role.")
    if action == "reset-mfa":
        password = getpass.getpass("Current dashboard password: ")
        confirmation = input(f"Type {username} to reset its MFA: ").strip()
        if confirmation != username:
            raise ValueError("MFA reset cancelled; account confirmation differs.")
        async with session_maker() as session:
            await session.run_sync(
                lambda sync: recover_admin_mfa(sync, username, password)
            )
            await session.commit()
        print("MFA reset committed; all sessions revoked. Enroll MFA after login.")
        return
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
        "action", choices=("add", "disable", "reset-password", "reset-mfa", "set-role")
    )
    parser.add_argument("username")
    parser.add_argument(
        "--role", choices=VALID_ROLES, default="viewer"
    )
    args = parser.parse_args()
    asyncio.run(manage_user(args.action, args.username, args.role))


if __name__ == "__main__":
    main()
