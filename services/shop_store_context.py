"""Odoo-style Store environment derived from revocable, server-side grants.

- allowed_stores: verified staff memberships, never a browser claim;
- current_store: one active write owner, even when several are selected;
- active_stores: one or more authorized stores visible for list/report reads.

A user-level default survives logins. Each device session has an independent
active set and current Store. Every request reloads the live membership, so
revoking a Store takes effect without waiting for token/session expiry.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_admin_control import AdminSession
from models.shop_multibot import ShopStore
from models.shop_staff import ShopStaff
from models.shop_staff_store import (
    ShopAdminSessionStore, ShopStaffStoreAccess, ShopStaffStorePreference,
)
from services import shop_admin_security as security

MAX_ACTIVE_STORES = 32
LEVELS = ("viewer", "editor", "manager")
_LEVEL_RANK = {"viewer": 0, "editor": 1, "manager": 2}


@dataclass(frozen=True, slots=True)
class AuthorizedStore:
    """One Store and an explicit membership level in a user's accessible set."""

    id: str
    slug: str
    name: str
    state: str
    access_level: str


@dataclass(frozen=True, slots=True)
class StoreContext:
    """Immutable, effective Store selection derived from the real session."""

    staff_id: int
    session_id: str
    allowed_stores: tuple[AuthorizedStore, ...]
    active_store_ids: tuple[str, ...]
    current_store_id: str
    default_store_id: str
    version: int

    @property
    def allowed_store_ids(self) -> tuple[str, ...]:
        """Return all granted IDs, including Stores not selected on this device."""
        return tuple(store.id for store in self.allowed_stores)

    @property
    def current_store(self) -> AuthorizedStore:
        """Resolve the Store used as the sole owner for writes."""
        return next(
            store for store in self.allowed_stores
            if store.id == self.current_store_id
        )

    def require(
        self, store_id: str, *, write: bool = False, manage: bool = False,
    ) -> None:
        """Deny inactive, unauthorized or ambiguous cross-Store operations."""
        allowed = next(
            (item for item in self.allowed_stores if item.id == store_id),
            None,
        )
        if allowed is None or store_id not in self.active_store_ids:
            raise security.SecurityRejected("store_access_denied", 403)
        if (write or manage) and store_id != self.current_store_id:
            raise security.SecurityRejected("store_switch_required", 409)
        minimum = "manager" if manage else "editor" if write else "viewer"
        if _LEVEL_RANK[allowed.access_level] < _LEVEL_RANK[minimum]:
            raise security.SecurityRejected("store_permission_denied", 403)

    def serialize(self) -> dict:
        """Return non-secret selections and the granted Store list."""
        return {
            "staff_id": self.staff_id,
            "current_store_id": self.current_store_id,
            "default_store_id": self.default_store_id,
            "active_store_ids": list(self.active_store_ids),
            "allowed_store_ids": list(self.allowed_store_ids),
            "version": self.version,
            "stores": [{
                "id": store.id, "slug": store.slug, "name": store.name,
                "state": store.state, "access_level": store.access_level,
                "active": store.id in self.active_store_ids,
                "current": store.id == self.current_store_id,
            } for store in self.allowed_stores],
        }


_REQUEST_CONTEXT: ContextVar[StoreContext | None] = ContextVar(
    "shop_admin_store_context", default=None,
)


def current_context() -> StoreContext | None:
    """Read trusted request scope; never infer it from provider/user IDs."""
    return _REQUEST_CONTEXT.get()


@contextmanager
def bind_context(context: StoreContext) -> Iterator[None]:
    """Bind a verified scope only for the lifetime of one admin request."""
    token: Token[StoreContext | None] = _REQUEST_CONTEXT.set(context)
    try:
        yield
    finally:
        _REQUEST_CONTEXT.reset(token)


async def memberships(
    db: AsyncSession, *, staff_id: int,
) -> tuple[AuthorizedStore, ...]:
    """Load live, active grants joined to nonarchived Stores."""
    rows = (await db.execute(
        select(ShopStaffStoreAccess, ShopStore)
        .join(ShopStore, ShopStore.id == ShopStaffStoreAccess.store_id)
        .where(
            ShopStaffStoreAccess.staff_id == staff_id,
            ShopStaffStoreAccess.is_active.is_(True),
            ShopStore.state != "archived",
        ).order_by(ShopStore.slug)
    )).all()
    return tuple(
        AuthorizedStore(
            id=store.id, slug=store.slug, name=store.name,
            state=store.state, access_level=membership.access_level,
        ) for membership, store in rows
    )


async def resolve_context(
    db: AsyncSession, *, staff_id: int, session_id: str,
) -> StoreContext:
    """Resolve effective Store selection; revoked grants disappear at once."""
    session = await db.get(AdminSession, session_id)
    if (
        session is None or session.staff_id != staff_id
        or session.revoked_at is not None
    ):
        raise security.SecurityRejected("session_expired", 401)
    allowed = await memberships(db, staff_id=staff_id)
    if not allowed:
        raise security.SecurityRejected("store_access_denied", 403)

    allowed_ids = {store.id for store in allowed}
    preference = await db.get(ShopStaffStorePreference, staff_id)
    default_id = (
        preference.default_store_id if preference is not None
        and preference.default_store_id in allowed_ids else allowed[0].id
    )
    active_rows = (await db.scalars(select(
        ShopAdminSessionStore.store_id,
    ).where(ShopAdminSessionStore.session_id == session_id))).all()
    selected = tuple(
        store_id for store_id in active_rows if store_id in allowed_ids
    )
    if not selected:
        selected = (default_id,)
    current_id = (
        session.current_store_id
        if session.current_store_id in selected else selected[0]
    )
    return StoreContext(
        staff_id=staff_id, session_id=session_id,
        allowed_stores=allowed,
        active_store_ids=tuple(sorted(selected)),
        current_store_id=current_id, default_store_id=default_id,
        version=session.store_context_version,
    )


async def switch_session(
    db: AsyncSession, *, staff_id: int, session_id: str,
    expected_version: int, current_store_id: str,
    active_store_ids: list[str],
) -> StoreContext:
    """Atomically change a browser's current Store and active Store set."""
    if (
        type(expected_version) is not int or expected_version < 1
        or not 1 <= len(active_store_ids) <= MAX_ACTIVE_STORES
        or len(active_store_ids) != len(set(active_store_ids))
        or current_store_id not in active_store_ids
    ):
        raise security.SecurityRejected("invalid_store_selection", 422)
    session = await db.scalar(select(AdminSession).where(
        AdminSession.id == session_id,
        AdminSession.staff_id == staff_id,
        AdminSession.revoked_at.is_(None),
    ).with_for_update())
    if session is None:
        raise security.SecurityRejected("session_expired", 401)
    if session.store_context_version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)

    allowed = await memberships(db, staff_id=staff_id)
    permitted = {store.id for store in allowed}
    if not set(active_store_ids) <= permitted:
        raise security.SecurityRejected("store_access_denied", 403)
    await db.execute(delete(ShopAdminSessionStore).where(
        ShopAdminSessionStore.session_id == session_id,
    ))
    for store_id in sorted(active_store_ids):
        db.add(ShopAdminSessionStore(
            session_id=session_id, store_id=store_id,
        ))
    session.current_store_id = current_store_id
    session.store_context_version += 1
    await db.commit()
    return await resolve_context(
        db, staff_id=staff_id, session_id=session_id,
    )


async def save_default(
    db: AsyncSession, *, staff_id: int, store_id: str,
    expected_version: int,
) -> dict:
    """Save user-level login default without modifying other open sessions."""
    permitted = {store.id for store in await memberships(
        db, staff_id=staff_id,
    )}
    if store_id not in permitted:
        raise security.SecurityRejected("store_access_denied", 403)
    row = await db.scalar(select(ShopStaffStorePreference).where(
        ShopStaffStorePreference.staff_id == staff_id,
    ).with_for_update())
    if row is None:
        if expected_version != 0:
            raise security.SecurityRejected("configuration_changed", 409)
        row = ShopStaffStorePreference(
            staff_id=staff_id, default_store_id=store_id,
        )
        db.add(row)
    else:
        if row.version != expected_version:
            raise security.SecurityRejected("configuration_changed", 409)
        row.default_store_id = store_id
        row.version += 1
    await db.commit()
    return {
        "default_store_id": row.default_store_id,
        "version": row.version,
    }


async def store_permissions(
    db: AsyncSession, *, member_id: int,
    operator: StoreContext,
) -> dict:
    """Show only Stores this administrator is authorized to manage."""
    manageable = {
        store.id for store in operator.allowed_stores
        if store.id in operator.active_store_ids
        and store.access_level == "manager"
    }
    current_grants = (await db.scalars(select(ShopStaffStoreAccess).where(
        ShopStaffStoreAccess.staff_id == member_id,
        ShopStaffStoreAccess.store_id.in_(manageable),
    ))).all()
    grants = {
        row.store_id: {
            "access_level": row.access_level, "is_active": row.is_active,
        } for row in current_grants
    }
    preference = await db.get(ShopStaffStorePreference, member_id)
    return {
        "staff_id": member_id,
        "stores": [{
            "id": store.id, "name": store.name, "slug": store.slug,
            "state": store.state,
            "access_level": grants.get(store.id, {}).get("access_level"),
            "granted": grants.get(store.id, {}).get("is_active", False),
        } for store in operator.allowed_stores if store.id in manageable],
        "default_store_id": (
            preference.default_store_id if preference else None
        ),
        "default_version": preference.version if preference else 0,
    }


async def update_staff_permissions(
    db: AsyncSession, *, actor: StoreContext, target_id: int,
    grants: list[dict], default_store_id: str | None,
) -> dict:
    """Replace Store grants inside the manager's scope and recheck the default.

    Removing another manager's final membership on a Store is forbidden.
    Each mutation is serialized against the Store row and staff row.
    """
    if target_id == actor.staff_id:
        raise security.SecurityRejected("use_my_account", 409)
    if not 1 <= len(grants) <= 100:
        raise security.SecurityRejected("invalid_store_grants", 422)
    desired = {record["store_id"]: record["access_level"] for record in grants}
    if (
        len(desired) != len(grants)
        or any(level not in LEVELS for level in desired.values())
    ):
        raise security.SecurityRejected("invalid_store_grants", 422)
    manageable = {
        store.id for store in actor.allowed_stores
        if store.id in actor.active_store_ids
        and store.access_level == "manager"
    }
    if not set(desired) <= manageable:
        raise security.SecurityRejected("store_permission_denied", 403)
    # Serialize grants/revocations on each Store row. Otherwise two admins
    # could concurrently demote two different managers, both see count=2,
    # and accidentally leave that Store with no manager.
    (await db.scalars(select(ShopStore).where(
        ShopStore.id.in_(sorted(manageable)),
    ).order_by(ShopStore.id).with_for_update())).all()
    target = await db.get(ShopStaff, target_id, with_for_update=True)
    if target is None:
        raise security.SecurityRejected("staff_not_found", 404)

    # Reconfiguration may remove only grants under this manager's authority.
    old = (await db.scalars(select(ShopStaffStoreAccess).where(
        ShopStaffStoreAccess.staff_id == target_id,
        ShopStaffStoreAccess.store_id.in_(manageable),
    ).with_for_update())).all()
    existing = {row.store_id: row for row in old}
    if default_store_id is not None and default_store_id not in desired:
        raise security.SecurityRejected("invalid_store_default", 422)
    for row in old:
        replacing = desired.get(row.store_id)
        if row.is_active and row.access_level == "manager" and replacing != "manager":
            count = int(await db.scalar(select(func.count()).select_from(
                ShopStaffStoreAccess,
            ).where(
                ShopStaffStoreAccess.store_id == row.store_id,
                ShopStaffStoreAccess.is_active.is_(True),
                ShopStaffStoreAccess.access_level == "manager",
            )) or 0)
            if count <= 1:
                raise security.SecurityRejected("last_store_manager", 409)
        row.is_active = replacing is not None
        if replacing:
            row.access_level = replacing
        row.changed_by = actor.staff_id
    for store_id, level in desired.items():
        if store_id not in existing:
            db.add(ShopStaffStoreAccess(
                staff_id=target_id, store_id=store_id,
                access_level=level, is_active=True,
                changed_by=actor.staff_id,
            ))
    preference = await db.get(
        ShopStaffStorePreference, target_id, with_for_update=True,
    )
    if default_store_id is not None:
        if preference is None:
            preference = ShopStaffStorePreference(
                staff_id=target_id, default_store_id=default_store_id,
            )
            db.add(preference)
        else:
            preference.default_store_id = default_store_id
            preference.version += 1
    elif preference and preference.default_store_id in manageable and (
        preference.default_store_id not in desired
    ):
        # Never leave a deleted default Store if the operator can repair it.
        if not desired:
            raise security.SecurityRejected("invalid_store_default", 422)
        preference.default_store_id = sorted(desired)[0]
        preference.version += 1
    await db.commit()
    return await store_permissions(db, member_id=target_id, operator=actor)


def grant_new_store_creator(
    db, *, staff_id: int, store_id: str,
) -> None:
    """Grant the creator Store-manager rights in the store's DDL transaction."""
    db.add(ShopStaffStoreAccess(
        staff_id=staff_id, store_id=store_id,
        access_level="manager", is_active=True, changed_by=staff_id,
    ))
