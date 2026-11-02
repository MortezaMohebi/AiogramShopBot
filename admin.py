"""SQLAdmin login using database staff identities and revocable sessions."""

from __future__ import annotations

from sqlalchemy import select
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

import config
from db import session_maker
from models.shop_staff import ShopStaff
from utils.utils import (
    create_access_token,
    decode_token,
    verify_password,
)


class AdminAuth(AuthenticationBackend):
    """Authenticate against hashed credentials and a live active-staff row."""

    async def login(self, request: Request) -> bool:
        """Create a short-lived role-bearing session after password verification."""
        form = await request.form()
        username, password = form.get("username"), form.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            return False
        username = username.strip().casefold()
        if not 1 <= len(username) <= 80 or not password:
            return False

        async with session_maker() as session:
            staff = await session.scalar(
                select(ShopStaff).where(
                    ShopStaff.username == username,
                    ShopStaff.is_active.is_(True),
                )
            )
            if staff is None or not verify_password(
                password, staff.password_hash
            ):
                return False
            token = create_access_token({
                "sub": str(staff.id),
                "role": staff.role,
                "sv": staff.session_version,
            })
        request.session.clear()
        request.session["token"] = token
        return True

    async def logout(self, request: Request) -> bool:
        """Remove the admin session token."""
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        """Revalidate the staff identity and session version on every request."""
        token = request.session.get("token")
        if not isinstance(token, str):
            return False
        claims = decode_token(token)
        if not isinstance(claims, dict):
            request.session.clear()
            return False
        try:
            staff_id = int(claims.get("sub"))
        except (TypeError, ValueError):
            request.session.clear()
            return False
        if staff_id <= 0 or type(claims.get("sv")) is not int:
            request.session.clear()
            return False
        async with session_maker() as session:
            staff = await session.get(ShopStaff, staff_id)
            if (
                staff is None or not staff.is_active
                or staff.session_version != claims["sv"]
                or staff.role != claims.get("role")
            ):
                request.session.clear()
                return False
            request.state.shop_role = staff.role
            request.state.shop_staff_id = staff.id
        return True


authentication_backend = AdminAuth(secret_key=config.JWT_SECRET_KEY)
