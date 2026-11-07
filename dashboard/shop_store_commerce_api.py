"""Signed store/customer commerce configuration and payment account API.

Store policies are opt-in. Security-sensitive payment connection creation,
authorization, provider token staging and finance sharing require fresh
password plus MFA proof. No token or customer secret is returned to browsers.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from dashboard.admin_control_api import Proof, StrictPayload, fresh_proof
from dashboard.next_api import database, signed_staff
from models.shop_content import ShopIdentity
from models.shop_engagement import ShopWalletAccount
from models.shop_multibot import ShopBot
from models.shop_staff import ShopStaff
from models.shop_store_commerce import ShopStoreCustomer
from services import shop_admin_security as security
from services import shop_payment_accounts as accounts
from services import shop_store_commerce as commerce
from services.shop_service_controls import service_enabled

router = APIRouter(prefix="/internal/admin/v1", tags=["Store Commerce"])
Db = Annotated[AsyncSession, Depends(database)]
Actor = Annotated[ShopStaff | None, Depends(signed_staff)]


def require(member: ShopStaff | None, capability: str) -> ShopStaff:
    """Use current server-side role, never untrusted browser claims."""
    if member is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(member.role, capability)
    return member


class SharingPolicyUpdate(Proof):
    """Explicitly approve a Store-level sharing change."""

    expected_version: int = Field(ge=0)
    cart_scope: Literal["bot", "customer"]
    credit_scope: Literal["identity", "customer"]


class BotCommerceUpdate(Proof):
    """Explicit per-bot feature inheritance/allow/deny toggles."""

    expected_version: int = Field(ge=0)
    cart_enabled: bool | None = None
    credit_enabled: bool | None = None
    credit_label: str | None = Field(default=None, max_length=80)


class PaymentAccountCreate(Proof):
    """Register a provider connection without activating it."""

    platform: Literal["telegram", "bale"]
    rail_type: Literal["bale_wallet", "telegram_fiat", "telegram_stars"]
    name: str = Field(min_length=1, max_length=100)
    token: str | None = Field(default=None, max_length=512)


class PaymentAccountState(Proof):
    """Controlled activation or deactivation of one existing provider."""

    expected_version: int = Field(ge=1)
    state: Literal["active", "disabled"]


class BotAccountGrant(Proof):
    """Grant/revoke a Store-owned provider to a matching-platform bot."""

    enabled: bool
    priority: int = Field(ge=1, le=1000)


def telegram_fiat_available() -> bool:
    """Only offer IRR setup when this installation can use the rail."""
    return config.TELEGRAM_IRR_MINOR_MULTIPLIER > 0 and service_enabled("telegram-fiat")


@router.get("/stores/{store_id}/commerce")
async def store_policy(store_id: UUID, actor: Actor, db: Db) -> dict:
    """Show whether this Store shares carts or internal credit."""
    require(actor, "bots.read")
    record = await commerce.policy_for(db, store_id=str(store_id))
    return {
        "store_id": record.store_id,
        "cart_scope": record.cart_scope,
        "credit_scope": record.credit_scope,
        "version": record.version,
    }


@router.post("/stores/{store_id}/commerce")
async def change_store_policy(
    store_id: UUID, payload: SharingPolicyUpdate,
    actor: Actor, db: Db,
) -> dict:
    """Opt in after MFA; deny shared credit with unreconciled identity balances."""
    member = require(actor, "bots.apply")
    await fresh_proof(db, member, payload)
    result = await commerce.set_store_policy(
        db, store_id=str(store_id), actor_id=member.id,
        expected_version=payload.expected_version,
        cart_scope=payload.cart_scope,
        credit_scope=payload.credit_scope,
    )
    return {
        "store_id": result.store_id,
        "cart_scope": result.cart_scope,
        "credit_scope": result.credit_scope,
        "version": result.version,
    }


@router.get("/bot-registry/{bot_id}/commerce")
async def bot_policy(bot_id: UUID, actor: Actor, db: Db) -> dict:
    """Read the selected bot's own Cart and credit permission overrides."""
    require(actor, "bots.read")
    return await commerce.bot_policy_snapshot(db, bot_id=str(bot_id))


@router.post("/bot-registry/{bot_id}/commerce")
async def change_bot_policy(
    bot_id: UUID, payload: BotCommerceUpdate,
    actor: Actor, db: Db,
) -> dict:
    """Enable/disable features per bot without deleting any historical data."""
    member = require(actor, "bots.apply")
    await fresh_proof(db, member, payload)
    return await commerce.update_bot_policy(
        db, bot_id=str(bot_id), actor_id=member.id,
        expected_version=payload.expected_version,
        cart_enabled=payload.cart_enabled,
        credit_enabled=payload.credit_enabled,
        credit_label=payload.credit_label,
    )


@router.get("/stores/{store_id}/payment-accounts")
async def list_payment_accounts(
    store_id: UUID, actor: Actor, db: Db,
) -> dict:
    """List redacted payment connections owned by one Store."""
    require(actor, "bots.read")
    result = await accounts.list_accounts(db, store_id=str(store_id))
    return {**result, "telegram_fiat_enabled": telegram_fiat_available()}


@router.post("/stores/{store_id}/payment-accounts", status_code=201)
async def create_payment_account(
    store_id: UUID, payload: PaymentAccountCreate,
    actor: Actor, db: Db,
) -> dict:
    """Create a disabled-by-default, purpose-encrypted provider connection."""
    member = require(actor, "bots.apply")
    if payload.rail_type == "telegram_fiat" and not telegram_fiat_available():
        raise security.SecurityRejected("telegram_fiat_unavailable", 409)
    await fresh_proof(db, member, payload)
    return await accounts.create_account(
        db, store_id=str(store_id), actor_id=member.id,
        platform=payload.platform, rail_type=payload.rail_type,
        name=payload.name, token=payload.token,
    )


@router.post("/payment-accounts/{account_id}/state")
async def payment_state(
    account_id: UUID, payload: PaymentAccountState,
    actor: Actor, db: Db,
) -> dict:
    """Apply provider activation flags only after fresh MFA."""
    member = require(actor, "bots.apply")
    await fresh_proof(db, member, payload)
    return await accounts.change_account_state(
        db, account_id=str(account_id), actor_id=member.id,
        expected_version=payload.expected_version,
        state=payload.state,
    )


@router.get("/bot-registry/{bot_id}/payment-accounts")
async def bot_payment_accounts(
    bot_id: UUID, actor: Actor, db: Db,
) -> dict:
    """Display account grants for the selected registered bot."""
    require(actor, "bots.read")
    return await accounts.list_bot_accounts(db, bot_id=str(bot_id))


@router.post("/bot-registry/{bot_id}/payment-accounts/{account_id}/grant")
async def grant_payment_account(
    bot_id: UUID, account_id: UUID, payload: BotAccountGrant,
    actor: Actor, db: Db,
) -> dict:
    """Bind a Provider to one Bot only within its authorized Store."""
    member = require(actor, "bots.apply")
    await fresh_proof(db, member, payload)
    return await accounts.grant_bot_access(
        db, bot_id=str(bot_id), account_id=str(account_id),
        enabled=payload.enabled, priority=payload.priority,
    )


@router.get("/store-customers")
async def list_store_customers(
    actor: Actor, db: Db, store_id: UUID | None = None,
    page: int = 1, page_size: int = 30,
) -> dict:
    """List verified merchant customers separately from bot identities."""
    require(actor, "bots.read")
    if page < 1 or page_size not in range(1, 101):
        raise security.SecurityRejected("invalid_request", 422)
    statement = select(ShopStoreCustomer)
    if store_id is not None:
        statement = statement.where(
            ShopStoreCustomer.store_id == str(store_id),
        )
    total = int(await db.scalar(select(func.count()).select_from(
        statement.subquery(),
    )) or 0)
    customers = (await db.scalars(statement.order_by(
        ShopStoreCustomer.id.desc(),
    ).offset((page - 1) * page_size).limit(page_size))).all()
    items = []
    for customer in customers:
        identities = (await db.scalars(select(ShopIdentity).where(
            ShopIdentity.store_id == customer.store_id,
            ShopIdentity.customer_id == customer.id,
        ).order_by(ShopIdentity.id))).all()
        items.append({
            "id": customer.id,
            "store_id": customer.store_id,
            "display_name": customer.display_name,
            "identities": [{
                "id": identity.id, "bot_id": identity.bot_id,
                "platform": identity.platform,
                "platform_user_id": str(identity.platform_user_id),
            } for identity in identities],
        })
    return {
        "items": items, "total": total,
        "page": page, "page_size": page_size,
    }


@router.get("/store-customers/{customer_id}")
async def store_customer(
    customer_id: int, actor: Actor, db: Db,
) -> dict:
    """Show all verified identities and separate historical wallet balances."""
    require(actor, "bots.read")
    customer = await db.get(ShopStoreCustomer, customer_id)
    if customer is None:
        raise security.SecurityRejected("customer_not_found", 404)
    identities = (await db.scalars(select(ShopIdentity).where(
        ShopIdentity.customer_id == customer.id,
        ShopIdentity.store_id == customer.store_id,
    ).order_by(ShopIdentity.id))).all()
    account_rows = (await db.execute(
        select(ShopWalletAccount.id, ShopWalletAccount.balance_irr,
               ShopWalletAccount.scope, ShopWalletAccount.identity_id)
        .where(
            ShopWalletAccount.store_id == customer.store_id,
            (ShopWalletAccount.customer_id == customer.id)
            | ShopWalletAccount.identity_id.in_(
                [identity.id for identity in identities]
            ),
        )
    )).all()
    return {
        "customer": {
            "id": customer.id, "store_id": customer.store_id,
            "display_name": customer.display_name,
            "phone": customer.phone,
        },
        "identities": [{
            "id": identity.id,
            "platform": identity.platform,
            "bot_id": identity.bot_id,
            "platform_user_id": str(identity.platform_user_id),
        } for identity in identities],
        "wallets": [{
            "id": account_id, "balance_irr": str(balance),
            "scope": scope, "identity_id": identity_id,
        } for account_id, balance, scope, identity_id in account_rows],
    }
