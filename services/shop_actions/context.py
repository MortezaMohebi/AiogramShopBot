"""Build and revalidate Action identity from authenticated Backend boundaries."""

from __future__ import annotations

from dataclasses import dataclass, replace

from channels.contracts import Platform
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services.shop_actions.contracts import ActionRejected
from services.shop_bot_context import BotContext, resolve_bot_context
from services.shop_customer_account import customer_for_bot
from services.shop_store_context import resolve_context

CUSTOMER_SCOPES = frozenset(
    {
        "catalog.read",
        "cart.read",
        "cart.write",
        "orders.read",
        "checkout.read",
        "support.write",
    }
)
STAFF_SCOPES = frozenset({"catalog.read", "actions.approve"})


@dataclass(frozen=True, slots=True)
class ActionPrincipal:
    """Backend-only identity capability; never deserialize from a request body."""

    actor_kind: str
    actor_key: str
    store_id: str
    bot_id: str
    platform: str
    scopes: frozenset[str]
    bot: BotContext
    identity_id: int | None = None
    customer_id: int | None = None
    platform_user_id: int | None = None
    staff_id: int | None = None
    session_id: str | None = None


async def customer_principal(
    db,
    *,
    verified_bot: BotContext,
    platform_user_id: int,
) -> ActionPrincipal:
    """Use a transport-verified Bot/user and an existing live customer identity."""
    try:
        current = await resolve_bot_context(
            db,
            authenticated_bot_id=verified_bot.bot_id,
            authenticated_platform=verified_bot.platform,
        )
    except security.SecurityRejected:
        raise ActionRejected("action_bot_unavailable") from None
    if current.store_id != verified_bot.store_id:
        raise ActionRejected("action_identity_changed")
    try:
        identity, customer = await customer_for_bot(
            db,
            current,
            platform_user_id=platform_user_id,
        )
    except ValueError:
        raise ActionRejected("action_customer_unavailable") from None
    return ActionPrincipal(
        actor_kind="customer",
        actor_key=f"customer:{identity.id}",
        store_id=current.store_id,
        bot_id=current.bot_id,
        platform=current.platform.value,
        scopes=CUSTOMER_SCOPES,
        bot=current,
        identity_id=identity.id,
        customer_id=customer.id,
        platform_user_id=platform_user_id,
    )


async def staff_principal(db, *, scope, actor, bot_id: str) -> ActionPrincipal:
    """Independently reload a revocable staff session and its effective Store grants."""
    try:
        fresh_scope = await resolve_context(
            db,
            staff_id=actor.id,
            session_id=scope.session_id,
        )
        fresh_actor = await db.get(ShopStaff, actor.id)
        if fresh_actor is None or not fresh_actor.is_active:
            raise ActionRejected("action_actor_unavailable")
        from models.shop_admin_control import AdminSession

        session = await db.get(AdminSession, fresh_scope.session_id)
        instant = security.clock()
        if (
            session is None
            or session.version != fresh_actor.session_version
            or session.revoked_at is not None
            or security.utc(session.expires_at) <= instant
            or security.utc(session.last_seen_at) + security.IDLE_LIMIT <= instant
        ):
            raise ActionRejected("action_actor_unavailable")
        security.require_permission(fresh_actor.role, "workflows.read")
        from models.shop_multibot import ShopBot

        record = await db.get(ShopBot, bot_id)
        if record is None:
            raise ActionRejected("action_bot_unavailable")
        fresh_scope.require(record.store_id)
        current = await resolve_bot_context(
            db,
            authenticated_bot_id=record.id,
            authenticated_platform=Platform(record.platform),
        )
        grants = frozenset(
            key
            for key in STAFF_SCOPES
            if security.has_permission(fresh_actor.role, key)
        )
    except (security.SecurityRejected, ValueError):
        raise ActionRejected("action_actor_unavailable") from None
    return ActionPrincipal(
        actor_kind="staff",
        actor_key=f"staff:{fresh_actor.id}",
        store_id=current.store_id,
        bot_id=current.bot_id,
        platform=current.platform.value,
        scopes=grants,
        bot=current,
        staff_id=fresh_actor.id,
        session_id=fresh_scope.session_id,
    )


async def refresh_principal(db, principal: ActionPrincipal) -> ActionPrincipal:
    """Recheck live ownership and grants even when replaying an existing receipt."""
    if (
        principal.store_id != principal.bot.store_id
        or principal.bot_id != principal.bot.bot_id
        or principal.platform != principal.bot.platform.value
    ):
        raise ActionRejected("action_identity_changed")
    if principal.actor_kind == "customer":
        fresh = await customer_principal(
            db,
            verified_bot=principal.bot,
            platform_user_id=principal.platform_user_id,
        )
    elif principal.actor_kind == "staff":
        from types import SimpleNamespace

        fresh = await staff_principal(
            db,
            scope=SimpleNamespace(session_id=principal.session_id),
            actor=SimpleNamespace(id=principal.staff_id),
            bot_id=principal.bot_id,
        )
    else:
        raise ActionRejected("action_actor_unavailable")
    if any(
        getattr(fresh, key) != getattr(principal, key)
        for key in (
            "actor_key",
            "store_id",
            "bot_id",
            "platform",
            "identity_id",
            "customer_id",
            "platform_user_id",
            "staff_id",
            "session_id",
        )
    ):
        raise ActionRejected("action_identity_changed")
    return replace(fresh, scopes=fresh.scopes & principal.scopes)
