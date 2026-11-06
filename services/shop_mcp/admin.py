"""Native human connection management without business approval authority."""

from __future__ import annotations

import json

from sqlalchemy import select

from models.shop_mcp import McpGrant, McpGrantStore, McpPairing, McpRequest
from services import shop_admin_security as security
from services.shop_mcp import grants
from services.shop_mcp.contracts import McpRejected

PAGE_SIZE = 20


async def _owner(db, scope, actor):
    """Use the real human session, never a delegated MCP principal."""
    current = await grants._human(db, scope, actor, recent=False)
    security.require_permission(current.role, "workflows.read")
    scope.require(scope.current_store_id)
    return current


async def pairing_review(db, *, scope, actor, pairing_id):
    """Disclose signed consent only to a manager of every requested Store."""
    current = await _owner(db, scope, actor)
    row = await db.get(McpPairing, pairing_id)
    if row is None:
        raise McpRejected("mcp_pairing_not_found", 404)
    stores = grants._list(row.stores_json)
    if scope.current_store_id not in stores:
        raise McpRejected("mcp_pairing_not_found", 404)
    await grants._manager_stores(db, current, stores)
    if row.confirmed_by not in (None, current.id):
        raise McpRejected("mcp_pairing_not_found", 404)
    result = grants._pairing_view(row)
    expired = security.utc(row.expires_at) <= security.clock()
    permitted = all(
        security.has_permission(current.role, grants.SCOPE_CAPABILITIES[s][0])
        for s in result["scopes"]
    )
    return result | {
        "expired": expired,
        "can_confirm": permitted and not expired and not result["confirmed"],
        "approval_authority": "wpmcp",
    }


async def grant_detail(db, *, scope, actor, grant_id):
    """Read one's own consent, including its safe revocation receipt."""
    current = await _owner(db, scope, actor)
    row = await db.get(McpGrant, grant_id)
    if row is None or row.staff_id != current.id:
        raise McpRejected("mcp_grant_not_found", 404)
    result = await grants._grant_view(db, row)
    result["store_ids"] = [
        item for item in result["store_ids"] if item in scope.allowed_store_ids
    ]
    return result | {
        "gateway": {
            "issuer": row.gateway_issuer,
            "client_id": row.gateway_client_id,
            "connection_id": row.gateway_connection_id,
            "workspace_id": row.gateway_workspace_id,
        },
        "expired": security.utc(row.expires_at) <= security.clock(),
        "can_revoke": row.revoked_at is None,
        "approval_authority": "wpmcp",
    }


async def overview(db, *, scope, actor, page=1):
    """Page owned grants for the selected Store without cross-Store metadata."""
    current = await _owner(db, scope, actor)
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise McpRejected("mcp_invalid_request", 422)
    rows = (
        await db.scalars(
            select(McpGrant)
            .join(McpGrantStore, McpGrantStore.grant_id == McpGrant.id)
            .where(
                McpGrant.staff_id == current.id,
                McpGrantStore.store_id == scope.current_store_id,
            )
            .order_by(McpGrant.created_at.desc(), McpGrant.id)
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE + 1)
        )
    ).all()
    items = []
    for row in rows[:PAGE_SIZE]:
        item = await grant_detail(
            db, scope=scope, actor=current, grant_id=row.id
        )
        item["store_ids"] = [scope.current_store_id]
        items.append(item)
    return {
        "actor_id": current.id,
        "store_id": scope.current_store_id,
        "items": items,
        "page": page,
        "has_more": len(rows) > PAGE_SIZE,
        "approval_authority": "wpmcp",
        "scopes": sorted(grants.SCOPES),
    }


async def history(db, *, scope, actor, page=1):
    """Page operational receipts without arguments, results or customer data."""
    current = await _owner(db, scope, actor)
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise McpRejected("mcp_invalid_request", 422)
    rows = (
        await db.scalars(
            select(McpRequest)
            .join(McpGrant, McpGrant.id == McpRequest.grant_id)
            .where(
                McpRequest.store_id == scope.current_store_id,
                McpGrant.staff_id == current.id,
            )
            .order_by(McpRequest.created_at.desc(), McpRequest.id)
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE + 1)
        )
    ).all()
    return {
        "store_id": scope.current_store_id,
        "page": page,
        "has_more": len(rows) > PAGE_SIZE,
        "items": [
            {
                "operation_id": row.id,
                "grant_id": row.grant_id,
                "tool": row.tool,
                "state": row.state,
                "created_at": security.utc(row.created_at).isoformat(),
            }
            for row in rows[:PAGE_SIZE]
        ],
    }


async def pairing_status(db, *, delegation):
    """Let the exact signed requester verify native consent after response loss."""
    row = await db.get(McpPairing, delegation.grant_id)
    if row is None or json.loads(row.identity_json) != grants._identity(
        delegation
    ):
        raise McpRejected("mcp_pairing_not_found", 404)
    result = grants._pairing_view(row)
    if row.confirmed_at is None:
        return result | {
            "status": "expired"
            if security.utc(row.expires_at) <= security.clock()
            else "pending",
        }
    for store_id in result["store_ids"]:
        await grants.resolve_grant(
            db,
            delegation=delegation,
            store_id=store_id,
            required_scope=result["scopes"][0],
        )
    grant = await db.get(McpGrant, row.id)
    return result | {
        "status": "confirmed",
        "grant": await grants._grant_view(db, grant),
    }
