"""Verified StoreCustomer ownership of historical orders across linked Bots.

Orders and payment attempts retain their original Bot and provider owner.
After a proven identity link, the StoreCustomer's active, verified Bot/user
identity tuples grant read-only historical visibility. Numeric user ID alone
never grants an order, and payment/refund initiation is still Bot-original.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import and_, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_content import ShopIdentity, ShopOrder

_MAX_LINKED_IDENTITIES = 100


def order_owner_clause(
    *, store_id: str,
    identity_keys: Sequence[tuple[str, str, int]],
):
    """Build bounded SQL predicates for exact (Bot, platform, user) ownership."""
    if not isinstance(store_id, str) or not store_id:
        raise ValueError("Store is required.")
    if len(identity_keys) > _MAX_LINKED_IDENTITIES:
        raise ValueError("Too many verified Bot identities.")
    if not identity_keys:
        return false()
    criteria = []
    for bot_id, platform, user_id in identity_keys:
        if (
            not isinstance(bot_id, str) or not bot_id
            or platform not in {"telegram", "bale"}
            or type(user_id) is not int or user_id <= 0
        ):
            raise ValueError("Malformed verified Bot identity.")
        criteria.append(and_(
            ShopOrder.bot_id == bot_id,
            ShopOrder.platform == platform,
            ShopOrder.platform_user_id == user_id,
        ))
    return and_(
        ShopOrder.store_id == store_id,
        or_(*criteria),
    )


async def verified_identity_keys(
    db: AsyncSession, *, store_id: str, customer_id: int,
) -> tuple[tuple[str, str, int], ...]:
    """Return only the explicitly linked identities of one StoreCustomer."""
    rows = (await db.execute(select(
        ShopIdentity.bot_id, ShopIdentity.platform,
        ShopIdentity.platform_user_id,
    ).where(
        ShopIdentity.store_id == store_id,
        ShopIdentity.customer_id == customer_id,
        ShopIdentity.is_blocked.is_(False),
    ).order_by(ShopIdentity.id).limit(_MAX_LINKED_IDENTITIES + 1))).all()
    if len(rows) > _MAX_LINKED_IDENTITIES:
        raise ValueError("Verified identity cluster is too large.")
    return tuple((bot, platform, int(user)) for bot, platform, user in rows)


async def order_visible_to_customer(
    db: AsyncSession, *, store_id: str, customer_id: int,
    order_id: int,
) -> ShopOrder | None:
    """Resolve one Order through exact authorized identity ownership."""
    if type(order_id) is not int or order_id <= 0:
        return None
    keys = await verified_identity_keys(
        db, store_id=store_id, customer_id=customer_id,
    )
    return await db.scalar(select(ShopOrder).where(
        ShopOrder.id == order_id,
        order_owner_clause(store_id=store_id, identity_keys=keys),
    ))
