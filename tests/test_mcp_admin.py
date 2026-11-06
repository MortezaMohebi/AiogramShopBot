"""Exercise native connection management with actual signed admin sessions."""

from __future__ import annotations

import importlib
from uuid import uuid4

import pytest
from sqlalchemy import select

from models.shop_admin_control import AdminEvent
from models.shop_mcp import McpGrant
from services.shop_mcp.contracts import McpRejected
from tests.test_campaign_admin_store_scope import (
    STORE_A,
    STORE_B,
)
from tests.test_campaign_admin_store_scope import (
    campaign_app as campaign_app,  # noqa: PLC0414 -- pytest fixture export
)
from tests.test_mcp_grants import pairing


@pytest.fixture(autouse=True)
def native_mfa(campaign_app, monkeypatch):
    """Exercise the real enrolled human boundary without relaxing MFA policy."""
    from cryptography.fernet import Fernet

    from dashboard import next_api
    from services import shop_admin_security as security
    from services.shop_mcp.proofs import ProofConfiguration
    from services.shop_mcp.settings import McpSettings
    from tests.test_mcp_authority import (
        APPROVAL_PRIVATE,
        AUDIENCE,
        ISSUER,
        PRIVATE,
    )

    monkeypatch.setenv(
        "SHOP_SECURITY_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    profile = security.profile_for(campaign_app.db, 7)
    profile.mfa_secret = (
        security.cipher().encrypt(b"JBSWY3DPEHPK3PXP").decode()
    )
    campaign_app.db.commit()
    campaign_app.app.dependency_overrides[next_api.database] = (
        campaign_app.legacy.dependency_overrides[next_api.database]
    )
    campaign_app.app.state.mcp_settings = McpSettings(
        enabled=True,
        proofs=ProofConfiguration(
            issuer=ISSUER,
            audience=AUDIENCE,
            delegation_keys={"wpmcp-delegation-test": PRIVATE.public_key()},
            approval_keys={
                "wpmcp-approval-test": APPROVAL_PRIVATE.public_key()
            },
        ),
    )


def administration():
    """Make missing management behavior fail before implementation."""
    try:
        return importlib.import_module("services.shop_mcp.admin")
    except ModuleNotFoundError:
        pytest.fail("Native MCP connection administration is required.")


@pytest.mark.asyncio
async def test_pairing_review_shows_exact_signed_identity_and_scopes(
    campaign_app,
):
    """Consent displays the stored proposal without silently adding a scope."""
    _, db, actor, scope, claims, pending, _ = await pairing(
        campaign_app, confirm=False
    )
    view = await administration().pairing_review(
        db, scope=scope, actor=actor, pairing_id=pending["id"]
    )
    assert view["identity"]["connection_id"] == claims.connection_id
    assert view["store_ids"] == [STORE_A]
    assert view["scopes"] == sorted(claims.scopes)
    assert view["approval_authority"] == "wpmcp"
    assert view["can_confirm"] is True


@pytest.mark.asyncio
async def test_unmanaged_store_pairing_is_not_disclosed(campaign_app):
    """Selecting another Store never reveals its pending gateway identity."""
    _, db, actor, scope, _, pending, _ = await pairing(
        campaign_app, confirm=False, store_ids=[STORE_B]
    )
    with pytest.raises(McpRejected):
        await administration().pairing_review(
            db, scope=scope, actor=actor, pairing_id=pending["id"]
        )


@pytest.mark.asyncio
async def test_selected_store_inventory_does_not_mix_other_store_grants(
    campaign_app,
):
    """Pagination and Store ownership stay in the native database query."""
    _, db, actor, scope, claims, _, _ = await pairing(campaign_app)
    await pairing(
        campaign_app,
        store_ids=[STORE_B],
        identity_overrides={
            "grant_id": str(uuid4()),
            "connection_id": str(uuid4()),
        },
    )
    result = await administration().overview(
        db, scope=scope, actor=actor, page=1
    )
    assert [item["id"] for item in result["items"]] == [claims.grant_id]
    assert result["store_id"] == STORE_A
    assert STORE_B not in str(result)
    assert "arguments_json" not in str(result)


@pytest.mark.asyncio
async def test_signed_admin_confirm_retry_and_revoke_have_authoritative_receipts(
    campaign_app,
):
    """A dropped response is recovered by reading the same grant UUID."""
    _, _, _, _, claims, pending, _ = await pairing(campaign_app, confirm=False)
    base = "/mcp/pairings/" + pending["id"]
    preview = await campaign_app.request("GET", base)
    assert preview.status_code == 200, preview.text
    for _ in range(2):
        confirmed = await campaign_app.request(
            "POST", base + "/confirm", payload={}
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["id"] == claims.grant_id
    detail = await campaign_app.request(
        "GET", "/mcp/grants/" + claims.grant_id
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["revoked"] is False
    for _ in range(2):
        revoked = await campaign_app.request(
            "POST",
            "/mcp/grants/" + claims.grant_id + "/revoke",
            payload={},
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["revoked"] is True
        assert revoked.json()["version"] == 2
    events = campaign_app.db.scalars(
        select(AdminEvent).where(AdminEvent.action.like("mcp.grant.%"))
    ).all()
    assert sorted(event.action for event in events) == [
        "mcp.grant.confirmed",
        "mcp.grant.revoked",
    ]


@pytest.mark.asyncio
async def test_native_mcp_management_has_no_business_approve_route(
    campaign_app,
):
    """Native delegation consent does not create another effect decision API."""
    await pairing(campaign_app)
    for suffix in ("approve", "deny", "commit"):
        result = await campaign_app.request(
            "POST",
            "/mcp/operations/" + str(uuid4()) + "/" + suffix,
            payload={},
        )
        assert result.status_code == 404, result.text


@pytest.mark.asyncio
async def test_inventory_and_history_never_expose_stored_request_bodies(
    campaign_app,
):
    """Operation history shows receipts and states without model/customer text."""
    _, db, actor, scope, claims, _, _ = await pairing(campaign_app)
    admin = administration()
    result = await admin.history(db, scope=scope, actor=actor, page=1)
    assert result["items"] == []
    grant = await admin.grant_detail(
        db, scope=scope, actor=actor, grant_id=claims.grant_id
    )
    assert grant["gateway"]["connection_id"] == claims.connection_id
    assert "private_key" not in str(grant)
    assert "gateway_subject" not in grant
    assert campaign_app.db.get(McpGrant, claims.grant_id).revoked_at is None


@pytest.mark.asyncio
async def test_signed_private_pairing_requires_separate_native_consent(
    campaign_app,
):
    """Pairing transport persists no staff grant until human confirmation."""
    import hashlib
    import json

    import httpx

    from dashboard import mcp_api
    from models.shop_mcp import McpPairing
    from services.shop_mcp.proofs import ProofConfiguration
    from services.shop_mcp.settings import McpSettings
    from tests.test_mcp_authority import (
        APPROVAL_PRIVATE,
        AUDIENCE,
        ISSUER,
        PRIVATE,
        signed,
    )

    _, db, _, _, claims, pending, _ = await pairing(
        campaign_app, confirm=False
    )
    campaign_app.db.delete(campaign_app.db.get(McpPairing, pending["id"]))
    campaign_app.db.commit()
    campaign_app.app.state.mcp_settings = McpSettings(
        enabled=True,
        proofs=ProofConfiguration(
            issuer=ISSUER,
            audience=AUDIENCE,
            delegation_keys={"wpmcp-delegation-test": PRIVATE.public_key()},
            approval_keys={
                "wpmcp-approval-test": APPROVAL_PRIVATE.public_key()
            },
        ),
    )

    async def database():
        yield db

    campaign_app.app.dependency_overrides[mcp_api.database] = database

    async def private(client, suffix, payload):
        target = "/internal/mcp/v1/pairings/" + suffix
        body = json.dumps(payload, separators=(",", ":")).encode()
        token = signed(
            claims.model_dump()
            | {
                "jti": str(uuid4()),
                "target": target,
                "body_sha256": hashlib.sha256(body).hexdigest(),
            }
        )
        return await client.post(
            target,
            content=body,
            headers={
                "content-type": "application/json",
                "x-wpmcp-delegation": token,
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=campaign_app.app),
        base_url="http://offline.test",
    ) as client:
        prepared = await private(
            client,
            "prepare",
            {
                "store_ids": [STORE_A],
                "scopes": claims.scopes,
            },
        )
        assert prepared.status_code == 200, prepared.text
        assert campaign_app.db.get(McpGrant, claims.grant_id) is None
        status = await private(client, "status", {})
        assert status.json()["result"]["status"] == "pending"
        confirmed = await campaign_app.request(
            "POST",
            "/mcp/pairings/" + pending["id"] + "/confirm",
            payload={},
        )
        assert confirmed.status_code == 200, confirmed.text
        status = await private(client, "status", {})
        assert status.status_code == 200, status.text
        assert status.json()["result"]["status"] == "confirmed"
        assert status.json()["result"]["grant"]["id"] == claims.grant_id


@pytest.mark.asyncio
async def test_owner_can_revoke_after_losing_all_store_access(campaign_app):
    """Withdrawal uses a real account session and never requires Store access."""
    from sqlalchemy import delete

    from models.shop_staff_store import ShopStaffStoreAccess

    _, _, _, _, claims, _, _ = await pairing(campaign_app)
    campaign_app.db.execute(
        delete(ShopStaffStoreAccess).where(ShopStaffStoreAccess.staff_id == 7)
    )
    campaign_app.db.commit()
    path = "/account/mcp-grants/" + claims.grant_id
    result = await campaign_app.request("POST", path + "/revoke", payload={})
    assert result.status_code == 200, result.text
    assert result.json()["revoked"] is True
    result = await campaign_app.request("GET", path)
    assert result.status_code == 200, result.text
    assert result.json()["revoked"] is True
    assert "store_ids" not in result.json()


@pytest.mark.asyncio
async def test_runtime_resource_pages_registered_bot_gates(campaign_app):
    """Many registered Bots do not cause an unbounded MCP response or query."""
    from models.shop_multibot import ShopBot
    from models.shop_workflow_runtime import RuntimeGate
    from services.shop_mcp import discovery

    grants, db, _, _, claims, _, _ = await pairing(
        campaign_app, scopes=["workflow:read", "runtime:read"]
    )
    for number in range(55):
        bot_id = str(uuid4())
        campaign_app.db.add(
            ShopBot(
                id=bot_id,
                store_id=STORE_A,
                slug=f"mcp-page-{number}",
                name=f"QA Bot {number}",
                platform="telegram",
            )
        )
        campaign_app.db.flush()
        campaign_app.db.add(
            RuntimeGate(
                store_id=STORE_A,
                scope_key="bot:" + bot_id,
                bot_id=bot_id,
            )
        )
    campaign_app.db.commit()
    principal = await grants.resolve_grant(
        db,
        delegation=claims,
        store_id=STORE_A,
        required_scope="runtime:read",
    )
    first = await discovery.resource(
        db, principal, STORE_A, "runtime_summary", page=1
    )
    second = await discovery.resource(
        db, principal, STORE_A, "runtime_summary", page=2
    )
    assert len(first["gates"]) == 50
    assert len(second["gates"]) == 5
    assert first["gate_has_more"] is True
    assert second["gate_has_more"] is False
    assert not {row["bot_id"] for row in first["gates"]}.intersection(
        row["bot_id"] for row in second["gates"]
    )


@pytest.mark.asyncio
async def test_disabled_adapter_blocks_consent_but_preserves_owner_withdrawal(
    campaign_app,
):
    """Turning MCP off never prevents withdrawal of an existing owned grant."""
    from services.shop_mcp.settings import McpSettings

    _, _, _, _, claims, pending, _ = await pairing(campaign_app, confirm=False)
    configured = campaign_app.app.state.mcp_settings
    campaign_app.app.state.mcp_settings = McpSettings(
        enabled=False, proofs=None
    )
    target = "/mcp/pairings/" + pending["id"] + "/confirm"
    denied = await campaign_app.request("POST", target, payload={})
    assert denied.status_code == 503, denied.text
    assert campaign_app.db.get(McpGrant, claims.grant_id) is None
    campaign_app.app.state.mcp_settings = configured
    assert (
        await campaign_app.request("POST", target, payload={})
    ).status_code == 200
    campaign_app.app.state.mcp_settings = McpSettings(
        enabled=False, proofs=None
    )
    revoked = await campaign_app.request(
        "POST",
        "/account/mcp-grants/" + claims.grant_id + "/revoke",
        payload={},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked"] is True
    loaded = await campaign_app.request("GET", "/mcp")
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["enabled"] is False
