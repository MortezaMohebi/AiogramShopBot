"""Platform-scoped shop identities for common Telegram and Bale services.

The user database used by the legacy Telegram shop is preserved separately.
This new identity layer never treats equal numeric IDs across platforms as
the same customer, nor opts customers into campaigns without consent.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import Platform
from models.shop_content import ShopIdentity
from models.shop_customer_crm import ShopCustomerProfile
from services.shop_customer_crm import effective_restriction


async def register_customer(
    session: AsyncSession,
    *,
    platform: Platform,
    platform_user_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> ShopIdentity:
    """Create or update a platform identity without granting campaign opt-in."""
    if type(platform_user_id) is not int or platform_user_id <= 0:
        raise ValueError("Platform user ID must be a positive integer.")
    if username is not None:
        username = username.strip()[:255] or None
    if first_name is not None:
        first_name = first_name.strip()[:255] or None

    condition = (
        ShopIdentity.platform == platform.value,
        ShopIdentity.platform_user_id == platform_user_id,
    )
    result = await session.execute(select(ShopIdentity).where(*condition))
    identity = result.scalar_one_or_none()
    if identity is None:
        identity = ShopIdentity(
            platform=platform.value,
            platform_user_id=platform_user_id,
            username=username,
            first_name=first_name,
            allow_announcements=False,
        )
        session.add(identity)
    else:
        if username is not None:
            identity.username = username
        if first_name is not None:
            identity.first_name = first_name
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        # Parallel /start events may race to create the same identity.
        result = await session.execute(select(ShopIdentity).where(*condition))
        identity = result.scalar_one()
    return identity


async def is_blocked(
    session: AsyncSession, *, platform: Platform, platform_user_id: int
) -> bool:
    """Check the platform-scoped ban without mutating any records."""
    rows = await session.execute(
        select(
            ShopIdentity.is_blocked,
            ShopCustomerProfile.restriction_until,
        )
        .outerjoin(
            ShopCustomerProfile,
            ShopCustomerProfile.identity_id == ShopIdentity.id,
        )
        .where(
            ShopIdentity.platform == platform.value,
            ShopIdentity.platform_user_id == platform_user_id,
        )
    )
    row = rows.first()
    return effective_restriction(row[0], row[1]) if row else False
