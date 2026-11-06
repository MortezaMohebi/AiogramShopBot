"""Exercise native delegation grants against real staff and Store records."""

from __future__ import annotations

import hashlib
import importlib
import json
import time
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from models.shop_staff import ShopStaff
from models.shop_staff_store import ShopStaffStoreAccess
from services import shop_admin_security as security
from services.shop_mcp.contracts import Delegation, McpRejected
from services.shop_store_context import resolve_context
from tests.test_campaign_admin_store_scope import (
    AsyncDb, STORE_A, STORE_B, campaign_app,
)
from tests.test_mcp_authority import (
    APPROVAL_PRIVATE, AUDIENCE, ISSUER, PRIVATE, delegation_claims, signed,
)

# Register the future tables before the shared fixture creates its real schema.
try:
    importlib.import_module("models.shop_mcp")
except ModuleNotFoundError:
    pass


def service():
    """Fail in the test phase when the native authorization service is absent."""
    try:
        return importlib.import_module("services.shop_mcp.grants")
    except ModuleNotFoundError:
        pytest.fail("Native WPMCP grants have not been implemented.")


async def pairing(
    app, *, store_ids=None, scopes=None, confirm=True, identity_overrides=None,
):
    """Use a real manager session to confirm a signed gateway pairing intent."""
    module = service()
    actor = app.db.get(ShopStaff, 7)
    actor.role = "superadmin"
    app.db.commit()
    db = AsyncDb(app.db)
    scope = await resolve_context(db, staff_id=7, session_id=app.session_id)
    instant = int(time.time())
    claims = Delegation.model_validate(delegation_claims(
        iat=instant, exp=instant + 45,
        scopes=scopes or ["workflow:read", "workflow:write"],
        **(identity_overrides or {}),
    ))
    pending = await module.prepare_pairing(
        db, delegation=claims,
        store_ids=store_ids or [STORE_A], scopes=claims.scopes,
    )
    result = None
    if confirm:
        result = await module.confirm_pairing(
            db, scope=scope, actor=actor, pairing_id=pending["id"],
        )
    return module, db, actor, scope, claims, pending, result


@pytest.mark.asyncio
async def test_signed_pairing_is_not_a_native_grant_until_a_manager_confirms(campaign_app):
    """Gateway signature alone cannot select native staff or grant Store access."""
    module, db, actor, scope, claims, pending, _ = await pairing(
        campaign_app, confirm=False,
    )
    models = importlib.import_module("models.shop_mcp")
    assert campaign_app.db.scalar(
        select(func.count()).select_from(models.McpGrant)
    ) == 0
    with pytest.raises(McpRejected):
        await module.resolve_grant(
            db, delegation=claims, store_id=STORE_A,
            required_scope="workflow:read",
        )
    confirmed = await module.confirm_pairing(
        db, scope=scope, actor=actor, pairing_id=pending["id"],
    )
    assert confirmed["id"] == claims.grant_id
    assert confirmed["store_ids"] == [STORE_A]
    repeated = await module.confirm_pairing(
        db, scope=scope, actor=actor, pairing_id=pending["id"],
    )
    assert repeated["id"] == confirmed["id"]
    principal = await module.resolve_grant(
        db, delegation=claims, store_id=STORE_A,
        required_scope="workflow:read",
    )
    assert principal.actor.id == 7
    assert principal.scope.allowed_store_ids == (STORE_A,)
    assert principal.scope.session_id == claims.grant_id
    assert principal.scope.session_id != campaign_app.session_id


@pytest.mark.asyncio
async def test_a_grant_uuid_cannot_impersonate_a_real_human_session(campaign_app):
    """Even matching UUIDs cannot turn delegated authority into native consent."""
    module, db, actor, _, claims, pending, _ = await pairing(
        campaign_app, identity_overrides={"grant_id": campaign_app.session_id},
    )
    principal = await module.resolve_grant(
        db, delegation=claims, store_id=STORE_A,
        required_scope="workflow:read",
    )
    with pytest.raises(McpRejected):
        await module.confirm_pairing(
            db, scope=principal.scope, actor=actor, pairing_id=pending["id"],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"sub": "another-gateway-owner"},
        {"client_id": "another-client"},
        {"tenant_id": "40000000-0000-4000-8000-000000000091"},
        {"workspace_id": "40000000-0000-4000-8000-000000000092"},
        {"connection_id": "40000000-0000-4000-8000-000000000093"},
        {"grant_version": 2},
    ],
)
async def test_a_valid_identity_from_another_gateway_grant_has_no_native_authority(
    campaign_app, changes,
):
    """A signed principal must match every field of the manager-confirmed grant."""
    module, db, _, _, claims, _, _ = await pairing(campaign_app)
    changed = Delegation.model_validate(claims.model_dump() | changes)
    with pytest.raises(McpRejected):
        await module.resolve_grant(
            db, delegation=changed, store_id=STORE_A,
            required_scope="workflow:read",
        )


@pytest.mark.asyncio
async def test_native_membership_is_intersected_with_the_explicit_store_and_scope_grant(campaign_app):
    """Being a manager of Store B does not add it to a Store A MCP grant."""
    module, db, _, _, claims, _, _ = await pairing(campaign_app)
    for store_id, requested in (
        (STORE_B, "workflow:read"), (STORE_A, "workflow:publish"),
    ):
        with pytest.raises(McpRejected):
            await module.resolve_grant(
                db, delegation=claims, store_id=store_id,
                required_scope=requested,
            )
    member = campaign_app.db.get(ShopStaffStoreAccess, (7, STORE_A))
    member.is_active = False
    campaign_app.db.commit()
    with pytest.raises(McpRejected):
        await module.resolve_grant(
            db, delegation=claims, store_id=STORE_A,
            required_scope="workflow:read",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["role", "session_version", "is_active"])
async def test_current_staff_changes_override_cached_grant_authority(campaign_app, change):
    """A cached ORM identity cannot retain authority after native staff changes."""
    module, db, actor, _, claims, _, _ = await pairing(campaign_app)
    if change == "role":
        actor.role = "viewer"
    elif change == "session_version":
        actor.session_version += 1
    else:
        actor.is_active = False
    campaign_app.db.commit()
    with pytest.raises(McpRejected):
        await module.resolve_grant(
            db, delegation=claims, store_id=STORE_A,
            required_scope="workflow:write", write=True,
        )


@pytest.mark.asyncio
async def test_owner_can_revoke_after_store_access_is_removed_and_replay_cannot_reenable(campaign_app):
    """Revocation removes authority even when the owner lost the original Store."""
    module, db, actor, scope, claims, _, _ = await pairing(campaign_app)
    campaign_app.db.get(ShopStaffStoreAccess, (7, STORE_A)).is_active = False
    campaign_app.db.commit()
    first = await module.revoke_grant(
        db, scope=scope, actor=actor, grant_id=claims.grant_id,
    )
    repeated = await module.revoke_grant(
        db, scope=scope, actor=actor, grant_id=claims.grant_id,
    )
    assert first["revoked"] is True
    assert repeated["version"] == first["version"]
    with pytest.raises(McpRejected):
        await module.resolve_grant(
            db, delegation=claims, store_id=STORE_A,
            required_scope="workflow:read",
        )


@pytest.mark.asyncio
async def test_pairing_expires_and_a_changed_retry_cannot_expand_its_store_scope(campaign_app):
    """A pending intent cannot be retargeted or confirmed after its deadline."""
    module, db, actor, scope, claims, pending, _ = await pairing(
        campaign_app, confirm=False,
    )
    with pytest.raises(McpRejected):
        await module.prepare_pairing(
            db, delegation=claims, store_ids=[STORE_A, STORE_B],
            scopes=claims.scopes,
        )
    models = importlib.import_module("models.shop_mcp")
    row = campaign_app.db.get(models.McpPairing, pending["id"])
    row.expires_at = security.clock() - timedelta(seconds=1)
    campaign_app.db.commit()
    with pytest.raises(McpRejected):
        await module.confirm_pairing(
            db, scope=scope, actor=actor, pairing_id=pending["id"],
        )


@pytest.mark.asyncio
async def test_actual_private_http_rechecks_grants_rejects_nonce_replay_and_defaults_off(campaign_app):
    """A valid signature authenticates one request, without a browser session."""
    _, db, _, _, claims, _, _ = await pairing(campaign_app)
    api = importlib.import_module("dashboard.mcp_api")
    settings = importlib.import_module("services.shop_mcp.settings")
    proofs = importlib.import_module("services.shop_mcp.proofs")
    configuration = proofs.ProofConfiguration(
        issuer=ISSUER, audience=AUDIENCE,
        delegation_keys={"wpmcp-delegation-test": PRIVATE.public_key()},
        approval_keys={"wpmcp-approval-test": APPROVAL_PRIVATE.public_key()},
    )
    campaign_app.app.state.mcp_settings = settings.McpSettings(
        enabled=True, proofs=configuration,
    )

    async def database():
        yield db

    campaign_app.app.dependency_overrides[api.database] = database
    body = json.dumps({"store_id": STORE_A}, separators=(",", ":")).encode()
    target = "/internal/mcp/v1/access"
    values = claims.model_dump() | {
        "target": target, "body_sha256": hashlib.sha256(body).hexdigest(),
    }
    token = signed(values)
    transport = httpx.ASGITransport(app=campaign_app.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://offline.test",
    ) as client:
        headers = {
            "content-type": "application/json", "x-wpmcp-delegation": token,
        }
        accepted = await client.post(target, content=body, headers=headers)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["store_id"] == STORE_A
        replay = await client.post(target, content=body, headers=headers)
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "mcp_request_replayed"
        forged = await client.post(
            target, content=body + b" ", headers=headers,
        )
        assert forged.status_code == 401
        campaign_app.app.state.mcp_settings = settings.McpSettings(
            enabled=False, proofs=None,
        )
        disabled = await client.post(target, content=body, headers=headers)
        assert disabled.status_code == 503
