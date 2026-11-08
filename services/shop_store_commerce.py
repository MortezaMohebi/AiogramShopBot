"""Store-level ownership, independently verified identities and sharing policy.

No customer is merged by numeric provider ID, phone number or shared bot
membership. A link requires authenticated actions from both endpoints and
an explicit final confirmation; financial balances are never merged.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_content import ShopIdentity
from models.shop_engagement import ShopWalletAccount
from models.shop_multibot import ShopBot, ShopStore
from models.shop_store_commerce import (
    ShopStoreCommercePolicy, ShopStoreCustomer,
    ShopStoreCustomerLinkEvent, ShopBotCommercePolicy,
)
from services import shop_admin_security as security


@dataclass(frozen=True, slots=True)
class StoreSharingPolicy:
    """The effective conservative opt-in configuration for one Store."""

    store_id: str
    cart_scope: str = "bot"
    credit_scope: str = "identity"
    version: int = 0


async def policy_for(
    db: AsyncSession, *, store_id: str,
) -> StoreSharingPolicy:
    """Read Store settings without silently creating or activating a policy."""
    row = await db.get(ShopStoreCommercePolicy, store_id)
    if row is None:
        return StoreSharingPolicy(store_id=store_id)
    return StoreSharingPolicy(
        store_id=store_id, cart_scope=row.cart_scope,
        credit_scope=row.credit_scope, version=row.version,
    )


async def bot_store(
    db: AsyncSession, *, bot_id: str,
) -> str:
    """Derive Store identity from a trusted Bot ID held by the runtime."""
    bot = await db.get(ShopBot, bot_id)
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    store = await db.get(ShopStore, bot.store_id)
    if store is None or store.state != "active":
        raise security.SecurityRejected("store_not_active", 409)
    return store.id


async def attach_new_customer(
    db: AsyncSession, identity: ShopIdentity,
) -> ShopStoreCustomer:
    """Create the first StoreCustomer for a new provider-scoped identity."""
    if not identity.store_id or identity.customer_id is not None:
        raise security.SecurityRejected("invalid_customer_owner", 409)
    customer = ShopStoreCustomer(
        store_id=identity.store_id,
        display_name=identity.first_name,
    )
    db.add(customer)
    await db.flush()
    identity.customer_id = customer.id
    return customer


async def link_confirmed_identities(
    db: AsyncSession, *, source: ShopIdentity,
    target: ShopIdentity, request_id: str,
) -> int:
    """Merge only customer profile references after an authenticated link.

    The target's historical orders, identity credit, subscription consent and
    existing carts keep their original owner. If a funded shared Customer
    wallet exists for the target, reject until manual financial review.
    """
    if (
        source.id == target.id or source.bot_id == target.bot_id
        or source.store_id != target.store_id
        or source.customer_id is None or target.customer_id is None
    ):
        raise security.SecurityRejected("customer_link_scope_mismatch", 409)

    customer_ids = sorted({source.customer_id, target.customer_id})
    locked = (await db.scalars(
        select(ShopStoreCustomer).where(
            ShopStoreCustomer.id.in_(customer_ids),
        ).order_by(ShopStoreCustomer.id).with_for_update()
    )).all()
    if (
        len(locked) != len(customer_ids)
        or any(item.store_id != source.store_id for item in locked)
    ):
        raise security.SecurityRejected("customer_link_scope_mismatch", 409)

    if source.customer_id != target.customer_id:
        funded = await db.scalar(select(func.count()).select_from(
            ShopWalletAccount
        ).where(
            ShopWalletAccount.store_id == source.store_id,
            ShopWalletAccount.customer_id == target.customer_id,
            ShopWalletAccount.scope == "customer",
            ShopWalletAccount.balance_irr > 0,
        ))
        if funded:
            raise security.SecurityRejected(
                "customer_credit_requires_reconciliation", 409,
            )
        # One user may have many independently verified bot identities.
        # The target customer cluster joins the already-proven source cluster.
        await db.execute(update(ShopIdentity).where(
            ShopIdentity.store_id == source.store_id,
            ShopIdentity.customer_id == target.customer_id,
        ).values(customer_id=source.customer_id))

    db.add(ShopStoreCustomerLinkEvent(
        id=str(uuid4()), request_id=request_id,
        source_identity_id=source.id, target_identity_id=target.id,
        store_id=source.store_id, customer_id=source.customer_id,
    ))
    return source.customer_id


async def set_store_policy(
    db: AsyncSession, *, store_id: str, actor_id: int,
    expected_version: int, cart_scope: str, credit_scope: str,
) -> StoreSharingPolicy:
    """Change opt-in sharing only if identity balances can remain accessible."""
    if cart_scope not in {"bot", "customer"} or credit_scope not in {
        "identity", "customer",
    }:
        raise security.SecurityRejected("invalid_store_sharing_policy", 422)
    store = await db.get(ShopStore, store_id)
    if store is None:
        raise security.SecurityRejected("store_not_found", 404)
    row = await db.scalar(select(ShopStoreCommercePolicy).where(
        ShopStoreCommercePolicy.store_id == store_id,
    ).with_for_update())
    if row is None:
        if expected_version != 0:
            raise security.SecurityRejected("configuration_changed", 409)
        row = ShopStoreCommercePolicy(store_id=store_id)
        db.add(row)
    elif row.version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)

    if credit_scope == "customer" and row.credit_scope != "customer":
        # An existing balance is never hidden or silently added to the
        # Customer account. Explicit, auditable transfer must precede cutover.
        remaining = await db.scalar(select(func.count()).select_from(
            ShopWalletAccount
        ).where(
            ShopWalletAccount.store_id == store_id,
            ShopWalletAccount.scope == "identity",
            ShopWalletAccount.balance_irr > 0,
        ))
        if remaining:
            raise security.SecurityRejected(
                "identity_credit_requires_reconciliation", 409,
            )
    row.cart_scope = cart_scope
    row.credit_scope = credit_scope
    row.version += 1
    row.updated_by = actor_id
    await db.commit()
    return StoreSharingPolicy(
        store_id=store_id, cart_scope=row.cart_scope,
        credit_scope=row.credit_scope, version=row.version,
    )


async def bot_policy_snapshot(
    db: AsyncSession, *, bot_id: str,
) -> dict:
    """Return explicit per-bot permissions; absence never means allow."""
    bot = await db.get(ShopBot, bot_id)
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    row = await db.get(ShopBotCommercePolicy, bot_id)
    return {
        "bot_id": bot_id,
        "runtime_owner": bot.runtime_owner,
        "version": row.version if row else 0,
        "cart_enabled": row.cart_enabled if row else None,
        "credit_enabled": row.credit_enabled if row else None,
        "credit_label": row.credit_label if row else None,
        "default_deny": bot.runtime_owner == "registry",
    }


async def update_bot_policy(
    db: AsyncSession, *, bot_id: str, actor_id: int,
    expected_version: int, cart_enabled: bool | None,
    credit_enabled: bool | None, credit_label: str | None,
) -> dict:
    """Store independent Cart/Credit switches without erasing any balances."""
    if (
        cart_enabled is not None and type(cart_enabled) is not bool
    ) or (
        credit_enabled is not None and type(credit_enabled) is not bool
    ):
        raise security.SecurityRejected("invalid_bot_commerce_policy", 422)
    if credit_label is not None:
        credit_label = credit_label.strip()
        if not 1 <= len(credit_label) <= 80:
            raise security.SecurityRejected("invalid_bot_commerce_policy", 422)
    bot = await db.get(ShopBot, bot_id)
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    row = await db.scalar(select(ShopBotCommercePolicy).where(
        ShopBotCommercePolicy.bot_id == bot_id,
    ).with_for_update())
    if row is None:
        if expected_version != 0:
            raise security.SecurityRejected("configuration_changed", 409)
        row = ShopBotCommercePolicy(bot_id=bot_id)
        db.add(row)
    elif row.version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)
    row.cart_enabled = cart_enabled
    row.credit_enabled = credit_enabled
    row.credit_label = credit_label
    row.version += 1
    row.updated_by = actor_id
    await db.commit()
    return await bot_policy_snapshot(db, bot_id=bot_id)
