"""Read effective customer restrictions without changing CRM history.

An expired temporary restriction restores access while its original flag,
reason and audit remain intact. A blocked identity without an expired bound
profile remains denied. Callers retain their exact Store/Bot ownership filters.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from models.shop_content import ShopIdentity
from models.shop_customer_crm import ShopCustomerProfile
from services.shop_admin_security import clock


def customer_access_clause(
    *,
    now: datetime | None = None,
    identity=ShopIdentity,
) -> ColumnElement[bool]:
    """Allow an unblocked identity or its own expired temporary restriction.

    The correlated subquery binds the Profile to the exact identity primary
    key, including when the caller uses an ORM alias. Missing expiry evidence
    never releases a permanent restriction. Checks perform no writes.
    """
    expired = (
        select(ShopCustomerProfile.identity_id)
        .where(
            ShopCustomerProfile.identity_id == identity.id,
            ShopCustomerProfile.restriction_until.is_not(None),
            ShopCustomerProfile.restriction_until <= clock(now),
        )
        .correlate(identity)
        .exists()
    )
    return or_(identity.is_blocked.is_(False), expired)


async def customer_access_allowed(
    db: AsyncSession,
    identity: ShopIdentity | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Check a loaded identity using the same current database expiry rule."""
    if identity is None or identity.id is None:
        return False
    eligible = await db.scalar(
        select(ShopIdentity.id).where(
            ShopIdentity.id == identity.id,
            customer_access_clause(now=now),
        )
    )
    return eligible is not None
