"""Native consent and current authority for the WPMCP adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from models.shop_admin_control import AdminSession
from models.shop_mcp import McpGrant, McpGrantStore, McpNonce, McpPairing
from models.shop_multibot import ShopStore
from models.shop_staff import ShopStaff
from models.shop_staff_store import ShopStaffStoreAccess
from services import shop_admin_security as security
from services.shop_mcp.contracts import (
    SCOPES,
    Delegation,
    McpRejected,
    PairingRequest,
)
from services.shop_store_context import StoreContext, memberships
from services.shop_workflow_schema import canonical_json

# Grant scopes narrow existing capabilities; they never create a native role.
SCOPE_CAPABILITIES = {
    "workflow:read": ("workflows.read", "viewer"),
    "workflow:validate": ("workflows.read", "viewer"),
    "workflow:simulate": ("workflows.read", "viewer"),
    "workflow:write": ("workflows.write", "editor"),
    "workflow:publish": ("workflows.publish", "manager"),
    "workflow:rollback": ("workflows.publish", "manager"),
    "runtime:read": ("workflows.read", "viewer"),
    "runtime:control": ("workflows.runtime.manage", "manager"),
    "actions:read": ("workflows.read", "viewer"),
    "bots:read": ("workflows.read", "viewer"),
    "audit:read": ("audit.read", "manager"),
    "catalog:read": ("catalog.read", "viewer"),
}
_WRITING_SCOPES = frozenset(
    {
        "workflow:write",
        "workflow:publish",
        "workflow:rollback",
        "runtime:control",
    }
)
_IDENTITY_FIELDS = (
    "iss",
    "aud",
    "sub",
    "client_id",
    "tenant_id",
    "workspace_id",
    "connection_id",
    "grant_id",
    "grant_version",
)


@dataclass(frozen=True, slots=True)
class NativePrincipal:
    """Current native identity and an optional selected Store."""

    grant: McpGrant
    actor: ShopStaff
    delegation: Delegation
    scope: StoreContext | None
    scopes: frozenset[str]


@dataclass(frozen=True, slots=True)
class HumanAccountSession:
    """A Store-free account identity; validated against the real session row."""

    staff_id: int
    session_id: str
    authority_kind: str = "admin_session"


def _identity(delegation: Delegation) -> dict:
    """Keep transport retries outside the immutable consent identity."""
    return {name: getattr(delegation, name) for name in _IDENTITY_FIELDS}


def _list(value: str) -> list[str]:
    """Fail closed if stored authorization data is damaged or unbounded."""
    try:
        result = json.loads(value)
        if not isinstance(result, list) or len(result) > 32:
            raise ValueError("invalid_list")
        if any(not isinstance(item, str) for item in result):
            raise ValueError("invalid_item")
        return result
    except (ValueError, TypeError, RecursionError):
        raise McpRejected("mcp_grant_unreadable", 503) from None


def _pairing_view(row: McpPairing) -> dict:
    """Project requested identity and scope without native credentials."""
    return {
        "id": row.id,
        "identity": json.loads(row.identity_json),
        "store_ids": _list(row.stores_json),
        "scopes": _list(row.scopes_json),
        "expires_at": security.utc(row.expires_at).isoformat(),
        "confirmed": row.confirmed_at is not None,
    }


async def _grant_view(db, row: McpGrant) -> dict:
    """Return owned delegation metadata without an access or refresh token."""
    store_ids = (
        await db.scalars(
            select(McpGrantStore.store_id)
            .where(McpGrantStore.grant_id == row.id)
            .order_by(McpGrantStore.store_id)
        )
    ).all()
    return {
        "id": row.id,
        "version": row.version,
        "store_ids": store_ids,
        "scopes": _list(row.scopes_json),
        "revoked": row.revoked_at is not None,
        "expires_at": security.utc(row.expires_at).isoformat(),
    }


async def prepare_pairing(
    db,
    *,
    delegation: Delegation,
    store_ids: list[str],
    scopes: list[str],
) -> dict:
    """Persist one signed proposal without assigning native staff authority."""
    try:
        request = PairingRequest(store_ids=store_ids, scopes=scopes)
        if set(request.scopes) - set(delegation.scopes):
            raise ValueError("scope_not_requested")
        if delegation.grant_version != 1:
            raise ValueError("new_grant_version_required")
    except (ValidationError, ValueError, TypeError):
        raise McpRejected("mcp_pairing_invalid", 422) from None
    identity = _identity(delegation)
    values = {
        "identity": identity,
        "store_ids": sorted(request.store_ids),
        "scopes": sorted(request.scopes),
    }
    digest = hashlib.sha256(canonical_json(values).encode()).hexdigest()
    row = await db.scalar(
        select(McpPairing)
        .where(McpPairing.id == delegation.grant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        row = McpPairing(
            id=delegation.grant_id,
            identity_json=canonical_json(identity),
            stores_json=canonical_json(values["store_ids"]),
            scopes_json=canonical_json(values["scopes"]),
            request_sha256=digest,
            expires_at=security.clock() + timedelta(minutes=5),
        )
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            row = await db.scalar(
                select(McpPairing)
                .where(McpPairing.id == delegation.grant_id)
                .execution_options(populate_existing=True)
            )
    if row is None:
        raise McpRejected("mcp_pairing_unavailable", 503)
    if not hmac.compare_digest(row.request_sha256, digest):
        raise McpRejected("mcp_pairing_conflict", 409)
    if (
        row.confirmed_at is None
        and security.utc(row.expires_at) <= security.clock()
    ):
        raise McpRejected("mcp_pairing_expired", 410)
    return _pairing_view(row)


async def _human(db, scope, actor, *, recent: bool) -> ShopStaff:
    """Require an actual human dashboard session for grant changes."""
    if (
        scope is None
        or actor is None
        or scope.staff_id != actor.id
        or scope.authority_kind != "admin_session"
    ):
        raise McpRejected("mcp_admin_session_required", 401)
    current = await db.scalar(
        select(ShopStaff)
        .where(ShopStaff.id == actor.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    session = await db.scalar(
        select(AdminSession)
        .where(
            AdminSession.id == scope.session_id,
            AdminSession.staff_id == actor.id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    instant = security.clock()
    if (
        current is None
        or not current.is_active
        or session is None
        or session.revoked_at is not None
        or session.version != current.session_version
        or security.utc(session.expires_at) <= instant
        or security.utc(session.last_seen_at) + security.IDLE_LIMIT <= instant
    ):
        raise McpRejected("mcp_admin_session_required", 401)
    if recent:
        try:
            security.require_recent(session)
        except security.SecurityRejected as rejected:
            raise McpRejected(rejected.code, rejected.status) from None
    return current


async def _manager_stores(db, actor, store_ids) -> None:
    """Require current manager access to every requested Store."""
    await db.execute(
        select(ShopStaffStoreAccess)
        .where(
            ShopStaffStoreAccess.staff_id == actor.id,
            ShopStaffStoreAccess.store_id.in_(store_ids),
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    allowed = {
        item.id: item for item in await memberships(db, staff_id=actor.id)
    }
    if any(
        store_id not in allowed or allowed[store_id].access_level != "manager"
        for store_id in store_ids
    ):
        raise McpRejected("mcp_store_access_denied", 403)


async def confirm_pairing(db, *, scope, actor, pairing_id: str) -> dict:
    """Confirm the exact Store and scope set through native authority."""
    current = await _human(db, scope, actor, recent=True)
    row = await db.scalar(
        select(McpPairing)
        .where(McpPairing.id == pairing_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise McpRejected("mcp_pairing_not_found", 404)
    existing = await db.scalar(
        select(McpGrant)
        .where(McpGrant.id == pairing_id)
        .execution_options(populate_existing=True)
    )
    if row.confirmed_at is not None:
        if (
            row.confirmed_by != current.id
            or existing is None
            or existing.revoked_at is not None
        ):
            raise McpRejected("mcp_pairing_consumed", 409)
        return await _grant_view(db, existing)
    if security.utc(row.expires_at) <= security.clock():
        raise McpRejected("mcp_pairing_expired", 410)
    store_ids, scopes = _list(row.stores_json), _list(row.scopes_json)
    await _manager_stores(db, current, store_ids)
    for item in scopes:
        if item not in SCOPE_CAPABILITIES or not security.has_permission(
            current.role, SCOPE_CAPABILITIES[item][0]
        ):
            raise McpRejected("mcp_permission_denied", 403)
    identity = json.loads(row.identity_json)
    grant = McpGrant(
        id=row.id,
        staff_id=current.id,
        staff_version=current.session_version,
        gateway_issuer=identity["iss"],
        audience=identity["aud"],
        gateway_subject=identity["sub"],
        gateway_client_id=identity["client_id"],
        gateway_tenant_id=identity["tenant_id"],
        gateway_workspace_id=identity["workspace_id"],
        gateway_connection_id=identity["connection_id"],
        scopes_json=row.scopes_json,
        version=1,
        expires_at=security.clock() + timedelta(days=30),
    )
    db.add(grant)
    try:
        await db.flush()
        for store_id in store_ids:
            db.add(McpGrantStore(grant_id=grant.id, store_id=store_id))
        row.confirmed_at, row.confirmed_by = security.clock(), current.id
        await db.run_sync(
            lambda sync: security.audit(
                sync, current.id, "mcp.grant.confirmed", grant.id
            )
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise McpRejected("mcp_pairing_conflict", 409) from None
    return await _grant_view(db, grant)


def _matches(grant: McpGrant, delegation: Delegation) -> bool:
    """Match every gateway identity and version to the native grant."""
    return (
        grant.gateway_issuer == delegation.iss
        and grant.audience == delegation.aud
        and grant.gateway_subject == delegation.sub
        and grant.gateway_client_id == delegation.client_id
        and grant.gateway_tenant_id == delegation.tenant_id
        and grant.gateway_workspace_id == delegation.workspace_id
        and grant.gateway_connection_id == delegation.connection_id
        and grant.id == delegation.grant_id
        and grant.version == delegation.grant_version
    )


async def resolve_grant(
    db,
    *,
    delegation: Delegation,
    store_id: str | None,
    required_scope: str,
    write: bool = False,
) -> NativePrincipal:
    """Intersect native permissions, membership and delegated scopes."""
    initial = await db.scalar(
        select(McpGrant)
        .where(McpGrant.id == delegation.grant_id)
        .execution_options(populate_existing=True)
    )
    if initial is None or not _matches(initial, delegation):
        raise McpRejected("mcp_grant_invalid", 401)
    store_ids = set(
        (
            await db.scalars(
                select(McpGrantStore.store_id).where(
                    McpGrantStore.grant_id == initial.id,
                )
            )
        ).all()
    )
    if store_id is not None and store_id not in store_ids:
        raise McpRejected("mcp_store_access_denied", 403)
    if write:
        if store_id is None or required_scope not in _WRITING_SCOPES:
            raise McpRejected("mcp_scope_required", 403)
        # Take the existing domain parent mutex before authority locks. Taking
        # Store SHARE and upgrading it later would deadlock concurrent writers.
        await db.scalar(
            select(ShopStore.id)
            .where(ShopStore.id == store_id)
            .with_for_update(key_share=True)
        )
    actor = await db.scalar(
        select(ShopStaff)
        .where(ShopStaff.id == initial.staff_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    grant = await db.scalar(
        select(McpGrant)
        .where(McpGrant.id == delegation.grant_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        actor is None
        or not actor.is_active
        or grant is None
        or not _matches(grant, delegation)
        or grant.revoked_at is not None
        or grant.staff_version != actor.session_version
        or security.utc(grant.expires_at) <= security.clock()
    ):
        raise McpRejected("mcp_grant_invalid", 401)
    granted = set(_list(grant.scopes_json))
    if granted - SCOPES:
        raise McpRejected("mcp_grant_unreadable", 503)
    effective = granted.intersection(delegation.scopes)
    if (
        required_scope not in effective
        or required_scope not in SCOPE_CAPABILITIES
    ):
        raise McpRejected("mcp_scope_required", 403)
    capability, minimum = SCOPE_CAPABILITIES[required_scope]
    if not security.has_permission(actor.role, capability):
        raise McpRejected("mcp_permission_denied", 403)
    await db.execute(
        select(ShopStaffStoreAccess)
        .where(
            ShopStaffStoreAccess.staff_id == actor.id,
            ShopStaffStoreAccess.store_id.in_(store_ids),
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    allowed = tuple(
        item
        for item in await memberships(db, staff_id=actor.id)
        if item.id in store_ids
    )
    selected = store_id or (allowed[0].id if allowed else None)
    scope = None
    if selected is not None:
        scope = StoreContext(
            staff_id=actor.id,
            session_id=grant.id,
            allowed_stores=allowed,
            active_store_ids=(selected,),
            current_store_id=selected,
            default_store_id=selected,
            version=grant.version,
            authority_kind="mcp_grant",
        )
        try:
            scope.require(
                selected,
                write=write or minimum == "editor",
                manage=minimum == "manager",
            )
        except security.SecurityRejected as rejected:
            raise McpRejected(rejected.code, rejected.status) from None
    elif store_id is not None:
        raise McpRejected("mcp_store_access_denied", 403)
    return NativePrincipal(
        grant,
        actor,
        delegation,
        scope,
        frozenset(effective),
    )


async def revoke_grant(db, *, scope, actor, grant_id: str) -> dict:
    """Let an owner revoke even after losing native Store access."""
    current = await _human(db, scope, actor, recent=False)
    grant = await db.scalar(
        select(McpGrant)
        .where(McpGrant.id == grant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if grant is None:
        raise McpRejected("mcp_grant_not_found", 404)
    if grant.staff_id != current.id:
        if not security.has_permission(current.role, "staff.manage"):
            raise McpRejected("mcp_grant_not_found", 404)
        stores = (
            await db.scalars(
                select(McpGrantStore.store_id).where(
                    McpGrantStore.grant_id == grant.id,
                )
            )
        ).all()
        await _manager_stores(db, current, stores)
    return await _revoke(db, grant, current.id)


async def _revoke(db, grant, actor_id):
    """Persist one revocation and audit event, preserving an exact retry."""
    if grant.revoked_at is None:
        grant.revoked_at, grant.version = security.clock(), grant.version + 1
        await db.run_sync(
            lambda sync: security.audit(
                sync, actor_id, "mcp.grant.revoked", grant.id
            )
        )
        await db.commit()
    return await _grant_view(db, grant)


async def account_grant(db, *, actor, session_id, grant_id, revoke=False):
    """Allow an owner to withdraw after losing every Store membership."""
    current = await _human(
        db, HumanAccountSession(actor.id, session_id), actor, recent=False
    )
    grant = await db.scalar(
        select(McpGrant)
        .where(McpGrant.id == grant_id, McpGrant.staff_id == current.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if grant is None:
        raise McpRejected("mcp_grant_not_found", 404)
    result = (
        await _revoke(db, grant, current.id)
        if revoke
        else (await _grant_view(db, grant))
    )
    return {
        key: result[key] for key in ("id", "version", "revoked", "expires_at")
    } | {
        "gateway_issuer": grant.gateway_issuer,
        "client_id": grant.gateway_client_id,
        "connection_id": grant.gateway_connection_id,
    }


async def consume_nonce(db, delegation: Delegation) -> None:
    """Claim one request ID in the domain transaction."""
    db.add(
        McpNonce(
            id=delegation.jti,
            grant_id=delegation.grant_id,
            expires_at=datetime.fromtimestamp(delegation.exp, UTC),
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise McpRejected("mcp_request_replayed", 401) from None
