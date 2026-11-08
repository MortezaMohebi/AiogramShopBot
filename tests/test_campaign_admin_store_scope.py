"""Exercise signed campaign administration against isolated Store records.

The real session boundary, request signatures, record rules and private file
storage run here. No provider, worker, Redis or configured database is used.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

import config
import dashboard.admin_control_app as control
from dashboard import next_api, next_operations
from models.shop_admin_control import AdminSession
from models.shop_content import ShopIdentity
from models.shop_engagement import (
    ShopCampaign, ShopCampaignDelivery, ShopCampaignMedia,
)
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot, ShopStore
from models.shop_staff import ShopStaff
from models.shop_staff_store import ShopAdminSessionStore, ShopStaffStoreAccess
from services import shop_admin_security as security
import services.shop_store_orm  # noqa: F401 -- install the live record rules.
from tests.schema_support import create_shop_schema

STORE_A = "10000000-0000-4000-8000-000000000001"
STORE_B = "10000000-0000-4000-8000-000000000002"
BOT_A = "20000000-0000-4000-8000-000000000001"
BOT_B = "20000000-0000-4000-8000-000000000002"
BOT_DRAFT = "20000000-0000-4000-8000-000000000003"
SECRET = "offline-campaign-bridge-key-with-sufficient-entropy"
PNG = b"\x89PNG\r\n\x1a\n" + b"offline-image-fixture"


class AsyncDb:
    """Adapt a real SQLite transaction to the application's async boundary."""

    def __init__(self, db: Session) -> None:
        """Keep the disposable transaction for the lifetime of one test."""
        self.db = db

    async def get(self, model, key, **kwargs):
        """Read an actual ORM record, including its identity-map behavior."""
        return self.db.get(model, key, **kwargs)

    async def execute(self, statement):
        """Execute the real SQLAlchemy statement and record rules."""
        return self.db.execute(statement)

    async def scalar(self, statement):
        """Read one actual scalar."""
        return self.db.scalar(statement)

    async def scalars(self, statement):
        """Read an actual scalar result set."""
        return self.db.scalars(statement)

    async def run_sync(self, callback):
        """Run database helpers without replacing their side effects."""
        return callback(self.db)

    def add(self, record):
        """Stage an actual ORM row."""
        self.db.add(record)

    async def delete(self, record):
        """Delete an actual ORM row."""
        self.db.delete(record)

    async def flush(self):
        """Flush pending records and ownership checks."""
        self.db.flush()

    async def commit(self):
        """Commit pending records and ownership checks."""
        self.db.commit()

    async def refresh(self, record):
        """Reload committed generated values."""
        self.db.refresh(record)

    async def rollback(self):
        """Discard a rejected operation."""
        self.db.rollback()


@dataclass
class CampaignFixture:
    """Bundle an isolated app, real session and signing identity."""

    db: Session
    app: FastAPI
    legacy: FastAPI
    token: str
    session_id: str

    def select_store(self, store_id: str) -> None:
        """Select one granted Store before the next signed request."""
        self.db.execute(delete(ShopAdminSessionStore))
        self.db.add(ShopAdminSessionStore(
            session_id=self.session_id, store_id=store_id,
        ))
        self.db.get(AdminSession, self.session_id).current_store_id = store_id
        self.db.commit()

    async def request(self, method: str, path: str, *, payload=None,
                      fields=None, file: bool = False, wrapped=True,
                      raise_app_exceptions: bool = True):
        """Send exact signed JSON or multipart bytes through the real app."""
        target = control.PREFIX + path
        if file:
            request = httpx.Request(
                method, "http://offline.test" + target,
                data=fields, files={"file": ("fixture.png", PNG, "image/png")},
            )
            body = request.read()
            content_type = request.headers["content-type"]
        else:
            body = json.dumps(payload or {}).encode() if method != "GET" else b""
            content_type = "application/json"
        stamp = str(int(time.time()))
        signature = hmac.new(SECRET.encode(), "\n".join((
            stamp, method, target, hashlib.sha256(body).hexdigest(), "7", "1",
        )).encode(), hashlib.sha256).hexdigest()
        headers = {
            "content-type": content_type, "x-shop-time": stamp,
            "x-shop-signature": signature, "x-shop-staff": "7",
            "x-shop-version": "1", "x-shop-session": self.token,
            "x-shop-session-proof": control.session_proof(
                self.token, signature, SECRET,
            ),
        }
        transport = httpx.ASGITransport(
            app=self.app if wrapped else self.legacy,
            raise_app_exceptions=raise_app_exceptions,
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await client.request(
                method, "http://offline.test" + target,
                content=body, headers=headers,
            )

    def campaign(self, store_id=STORE_A, *, status="draft") -> ShopCampaign:
        """Persist a campaign before binding a trusted request scope."""
        row = ShopCampaign(
            store_id=store_id, bot_id=BOT_A if store_id == STORE_A else BOT_B,
            title="کمپین آزمون", text="خبر فروشگاه", audience="all", status=status,
        )
        self.db.add(row)
        self.db.commit()
        return row


@pytest.fixture
def campaign_app(monkeypatch, tmp_path):
    """Create real staff grants and a revocable signed device session."""
    monkeypatch.setattr(config, "NEXT_ADMIN_BRIDGE_ENABLED", True)
    monkeypatch.setattr(config, "NEXT_ADMIN_BRIDGE_SECRET", SECRET)
    monkeypatch.setattr(config, "SHOP_MEDIA_ROOT", str(tmp_path))
    engine = create_engine("sqlite:///:memory:")
    create_shop_schema(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(ShopStaff(
            id=7, username="marketing-test", password_hash="test-only",
            role="marketing", is_active=True, session_version=1,
        ))
        for store_id, slug in ((STORE_A, "a-store"), (STORE_B, "b-store"),
                               (DEFAULT_STORE_ID, "legacy-store")):
            db.add(ShopStore(id=store_id, slug=slug, name=slug, state="active"))
            db.add(ShopStaffStoreAccess(
                staff_id=7, store_id=store_id, access_level="manager",
                is_active=True,
            ))
        for bot_id, store_id, status in ((BOT_A, STORE_A, "active"),
                                         (BOT_B, STORE_B, "active"),
                                         (BOT_DRAFT, STORE_A, "draft")):
            db.add(ShopBot(
                id=bot_id, store_id=store_id, slug=bot_id[-4:], name=bot_id[-4:],
                platform="telegram", status=status, runtime_owner="registry",
            ))
        db.commit()
        token = security.issue_session(db, db.get(ShopStaff, 7), "Offline test")
        session_id = db.scalar(select(AdminSession.id))
        row = db.get(AdminSession, session_id)
        row.current_store_id = STORE_A
        db.add_all([ShopAdminSessionStore(session_id=session_id, store_id=value)
                    for value in (STORE_A, STORE_B)])
        db.commit()
        adapter = AsyncDb(db)

        @asynccontextmanager
        async def session_maker():
            yield adapter

        async def database():
            yield adapter

        monkeypatch.setattr(control, "session_maker", session_maker)
        legacy = FastAPI()
        legacy.include_router(next_api.router)
        legacy.include_router(next_operations.router, prefix=control.PREFIX)
        legacy.dependency_overrides[next_api.database] = database
        app = control.create_app(legacy)
        app.dependency_overrides[next_api.database] = database
        yield CampaignFixture(db, app, legacy, token, session_id)
    engine.dispose()


@pytest.mark.asyncio
async def test_registry_draft_uses_explicit_bot_and_current_store(campaign_app):
    """A selected bot must reach the persisted unsent campaign unchanged."""
    response = await campaign_app.request("POST", "/campaigns", payload={
        "title": "عنوان", "text": "اعلان", "audience": "all", "bot_id": BOT_A,
    })
    assert response.status_code == 201, response.text
    row = campaign_app.db.get(ShopCampaign, response.json()["id"])
    assert (row.store_id, row.bot_id, row.status) == (STORE_A, BOT_A, "draft")


@pytest.mark.asyncio
async def test_bot_options_are_redacted_current_store_choices(campaign_app):
    """Marketing gets only active same-Store bot identities, without secrets."""
    response = await campaign_app.request("GET", "/campaigns/bots")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "store_id": STORE_A, "store_name": "a-store",
        "bots": [{"id": BOT_A, "name": "0001", "platform": "telegram"}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(("changes", "status", "detail"), [
    ({"bot_id": BOT_B}, 404, "bot_not_found"),
    ({"bot_id": BOT_DRAFT}, 409, "bot_not_active"),
    ({"audience": "bale"}, 422, "invalid_campaign_audience"),
])
async def test_invalid_registry_target_never_creates_draft(
    campaign_app, changes, status, detail,
):
    """Cross-Store, inactive, missing and mismatched targets fail closed."""
    response = await campaign_app.request("POST", "/campaigns", payload={
        "title": "عنوان", "text": "اعلان", "audience": "all", "bot_id": BOT_A,
        **changes,
    })
    assert response.status_code == status, response.text
    assert response.json()["detail"] == detail
    assert campaign_app.db.scalar(select(ShopCampaign.id)) is None


@pytest.mark.asyncio
async def test_campaign_requires_bot_even_in_default_store(campaign_app):
    """No Store can infer an environment-owned sender from an omitted Bot."""
    campaign_app.select_store(DEFAULT_STORE_ID)
    response = await campaign_app.request("POST", "/campaigns", payload={
        "title": "عنوان", "text": "اعلان", "audience": "bale",
    })
    assert response.status_code == 422, response.text
    assert campaign_app.db.scalar(select(ShopCampaign.id)) is None


@pytest.mark.asyncio
async def test_campaign_create_requires_trusted_store_context(campaign_app):
    """A signed staff header alone must not infer default ownership."""
    response = await campaign_app.request("POST", "/campaigns", wrapped=False,
                                          payload={"title": "عنوان", "text": "اعلان", "bot_id": BOT_A})
    assert response.status_code == 403, response.text
    assert campaign_app.db.scalar(select(ShopCampaign.id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["/campaigns", "/campaigns/bots"])
async def test_campaign_reads_deny_unprivileged_staff(campaign_app, resource):
    """A viewer's valid signed session cannot gain marketing access."""
    campaign_app.db.get(ShopStaff, 7).role = "viewer"
    campaign_app.db.commit()
    response = await campaign_app.request("GET", resource)
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_campaign_list_reports_store_and_bot_without_cross_store_rows(
    campaign_app,
):
    """List contracts expose their real owner while excluding unselected Stores."""
    own = campaign_app.campaign()
    campaign_app.campaign(STORE_B)
    campaign_app.select_store(STORE_A)
    response = await campaign_app.request("GET", "/campaigns")
    assert response.status_code == 200, response.text
    owners = [(item["id"], item["store_id"], item["bot_id"])
              for item in response.json()]
    assert owners == [(own.id, STORE_A, BOT_A)]


@pytest.mark.asyncio
@pytest.mark.parametrize(("store_id", "bot_id"), [
    (STORE_B, BOT_B), (STORE_A, BOT_DRAFT),
])
async def test_delivery_receipts_cannot_expose_another_store_identity(
    campaign_app, store_id, bot_id,
):
    """A corrupt child key cannot disclose another Store or Bot's recipient."""
    campaign = campaign_app.campaign()
    identity = ShopIdentity(
        store_id=store_id, bot_id=bot_id,
        platform="telegram", platform_user_id=999,
    )
    campaign_app.db.add(identity)
    campaign_app.db.flush()
    campaign_app.db.add(ShopCampaignDelivery(
        campaign_id=campaign.id, identity_id=identity.id, bot_id=bot_id,
        status="unknown",
    ))
    own_identity = ShopIdentity(
        store_id=STORE_A, bot_id=BOT_A, platform="telegram", platform_user_id=101,
    )
    campaign_app.db.add(own_identity)
    campaign_app.db.flush()
    own_delivery = ShopCampaignDelivery(
        campaign_id=campaign.id, identity_id=own_identity.id,
        bot_id=BOT_A, status="unknown",
    )
    campaign_app.db.add(own_delivery)
    campaign_app.db.commit()
    response = await campaign_app.request(
        "GET", f"/campaigns/{campaign.id}/deliveries",
    )
    assert response.status_code == 200, response.text
    assert response.json() == [{
        "id": own_delivery.id, "platform": "telegram", "user_id": "101",
        "completed_steps": 0, "last_error_code": None,
    }]


@pytest.mark.asyncio
async def test_paused_store_cannot_create_campaign(campaign_app):
    """A previously active Bot does not override a paused Store."""
    campaign_app.db.get(ShopStore, STORE_A).state = "paused"
    campaign_app.db.commit()
    response = await campaign_app.request("POST", "/campaigns", payload={
        "title": "عنوان", "text": "اعلان", "bot_id": BOT_A,
    })
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "store_not_active"
    assert campaign_app.db.scalar(select(ShopCampaign.id)) is None


@pytest.mark.asyncio
async def test_store_viewer_membership_cannot_write_campaign(campaign_app):
    """The marketing role cannot override a read-only Store membership."""
    membership = campaign_app.db.get(ShopStaffStoreAccess, (7, STORE_A))
    membership.access_level = "viewer"
    campaign_app.db.commit()
    response = await campaign_app.request("POST", "/campaigns", payload={
        "title": "عنوان", "text": "اعلان", "bot_id": BOT_A,
    })
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "store_permission_denied"
    assert campaign_app.db.scalar(select(ShopCampaign.id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("worker", "dispatch", "registry", "enabled"), [
    (False, True, True, False),
    (True, False, True, False),
    (True, True, False, False),
    (True, True, True, True),
])
async def test_registry_start_capability_requires_every_send_switch(
    campaign_app, monkeypatch, worker, dispatch, registry, enabled,
):
    """Current Store dashboards can read truthful default-off send controls."""
    monkeypatch.setattr(config, "SHOP_BROADCAST_WORKER_ENABLED", worker)
    monkeypatch.setattr(config, "SHOP_CAMPAIGN_DISPATCH_ENABLED", dispatch)
    monkeypatch.setattr(config, "SHOP_BROADCAST_REGISTRY_ENABLED", registry,
                        raising=False)
    response = await campaign_app.request("GET", "/capabilities")
    assert response.status_code == 200, response.text
    assert response.json()["broadcast_registry_enabled"] is enabled


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), [
    ("POST", "/campaigns/1/media"),
    ("GET", "/campaigns/1/export"),
    ("POST", "/campaigns/1/dispatch"),
    ("POST", "/capabilities"),
    ("GET", "/capabilities/other"),
])
async def test_campaign_scope_allowlist_does_not_widen_other_routes(
    campaign_app, method, path,
):
    """An audited draft path does not enable arbitrary campaign/provider paths."""
    response = await campaign_app.request(method, path)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "store_scope_not_supported"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [
    "approve", "start", "pause", "resume", "cancel", "reconcile",
])
async def test_campaign_controls_cannot_mutate_another_selected_store(
    campaign_app, action,
):
    """Selecting another Store for reads never makes it the current write owner."""
    row = campaign_app.campaign(STORE_B)
    payload = ({
        "delivery_id": 1, "resolution": "skipped", "evidence": "offline evidence",
    } if action == "reconcile" else {})
    response = await campaign_app.request(
        "POST", f"/campaigns/{row.id}/{action}", payload=payload,
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "store_switch_required"
    assert campaign_app.db.get(ShopCampaign, row.id).status == "draft"


@pytest.mark.asyncio
async def test_campaign_draft_media_round_trip_is_store_scoped(
    campaign_app, tmp_path,
):
    """An authorized targeted draft supports private upload/read/delete."""
    row = campaign_app.campaign()
    response = await campaign_app.request(
        "POST", "/upload/campaign", file=True,
        fields={"campaign_id": str(row.id), "caption": "تصویر"},
    )
    assert response.status_code == 201, response.text
    media_id = response.json()["id"]
    path = tmp_path / campaign_app.db.get(ShopCampaignMedia, media_id).storage_key
    listing = await campaign_app.request("GET", f"/campaigns/{row.id}/media")
    assert listing.status_code == 200, listing.text
    assert listing.json()["can_edit"] is True
    assert [item["id"] for item in listing.json()["items"]] == [media_id]
    preview = await campaign_app.request(
        "GET", f"/media/preview/campaign/{media_id}",
    )
    assert preview.status_code == 200, preview.text
    assert preview.content == PNG
    assert preview.headers["cache-control"] == "private, no-store"
    deleted = await campaign_app.request(
        "DELETE", f"/campaigns/{row.id}/media/{media_id}",
    )
    assert deleted.status_code == 200, deleted.text
    assert campaign_app.db.get(ShopCampaignMedia, media_id) is None
    assert not path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["upload", "delete", "list", "preview"])
async def test_campaign_media_cannot_cross_current_or_allowed_store(
    campaign_app, tmp_path, operation,
):
    """Child media ownership is proven through its campaign, even when cached."""
    row = campaign_app.campaign(STORE_B)
    file = ShopCampaignMedia(
        campaign_id=row.id, storage_key="a" * 32 + ".png",
        original_filename="other.png",
        mime_type="image/png", size_bytes=len(PNG), kind="photo", position=10,
    )
    campaign_app.db.add(file)
    campaign_app.db.commit()
    path = tmp_path / file.storage_key
    path.write_bytes(PNG)
    if operation in {"list", "preview"}:
        campaign_app.select_store(STORE_A)
    route, method = {
        "upload": ("/upload/campaign", "POST"),
        "delete": (f"/campaigns/{row.id}/media/{file.id}", "DELETE"),
        "list": (f"/campaigns/{row.id}/media", "GET"),
        "preview": (f"/media/preview/campaign/{file.id}", "GET"),
    }[operation]
    response = await campaign_app.request(
        method, route, file=operation == "upload",
        fields={"campaign_id": str(row.id)},
    )
    expected = 409 if operation in {"upload", "delete"} else 404
    assert response.status_code == expected, response.text
    assert path.read_bytes() == PNG
    assert campaign_app.db.get(ShopCampaignMedia, file.id) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/bot-connections", "/bot-profiles", "/connection-changes",
    "/telegram-transport", "/channel-features", "/payment-rails",
    "/broadcast/prepare/1",
])
async def test_retired_global_controls_have_no_active_route(campaign_app, path):
    """A signed session cannot revive retired environment-owned controls."""
    response = await campaign_app.request("POST", path, payload={})
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_wallet_adjustment_uses_exact_current_store_identity(
    campaign_app, monkeypatch,
):
    """Equal provider IDs in separate bots cannot redirect an admin credit."""
    from uuid import uuid4

    from models.shop_admin_control import AdminProfile
    from models.shop_engagement import ShopWalletAccount, ShopWalletEntry
    from models.shop_store_commerce import ShopBotCommercePolicy

    campaign_app.db.get(ShopStaff, 7).role = "finance"
    campaign_app.db.add(AdminProfile(
        staff_id=7, mfa_secret="offline-enrolled", recovery_hashes="[]",
    ))
    identities = []
    for store_id, bot_id in ((STORE_A, BOT_A), (STORE_B, BOT_B)):
        identity = ShopIdentity(
            store_id=store_id, bot_id=bot_id, platform="telegram",
            platform_user_id=12345,
        )
        campaign_app.db.add(identity)
        campaign_app.db.flush()
        campaign_app.db.add(ShopWalletAccount(
            store_id=store_id, bot_id=bot_id, identity_id=identity.id,
            scope="identity", balance_irr=0,
        ))
        campaign_app.db.add(ShopBotCommercePolicy(
            bot_id=bot_id, credit_enabled=True,
        ))
        identities.append(identity)
    campaign_app.db.commit()
    monkeypatch.setattr(config, "SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR", 1000)
    options = await campaign_app.request("GET", "/wallets/identities")
    assert options.status_code == 200, options.text
    assert [item["id"] for item in options.json()] == [identities[0].id]
    payload = {
        "identity_id": identities[0].id, "amount_irr": 100,
        "direction": "credit", "reason": "Documented offline adjustment",
        "operation_id": str(uuid4()), "confirmation": "CREDIT_CONFIRMED",
    }
    response = await campaign_app.request("POST", "/wallets/adjust", payload=payload)
    assert response.status_code == 200, response.text
    assert response.json()["created"] is True
    repeated = await campaign_app.request("POST", "/wallets/adjust", payload=payload)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["created"] is False
    assert repeated.json()["entry_id"] == response.json()["entry_id"]
    foreign = await campaign_app.request("POST", "/wallets/adjust", payload={
        **payload, "identity_id": identities[1].id, "operation_id": str(uuid4()),
    })
    assert foreign.status_code == 404, foreign.text
    balances = campaign_app.db.scalars(select(ShopWalletAccount).order_by(
        ShopWalletAccount.identity_id,
    )).all()
    assert [account.balance_irr for account in balances] == [100, 0]
    assert len(campaign_app.db.scalars(select(ShopWalletEntry)).all()) == 1
    obsolete = await campaign_app.request("POST", "/wallets/adjust", payload={
        **payload, "platform": "telegram", "user_id": 12345,
    })
    assert obsolete.status_code == 422, obsolete.text


@pytest.mark.asyncio
async def test_branding_is_scoped_to_selected_store_including_default(campaign_app):
    """The default Store uses the same isolated settings table as every Store."""
    from models.shop_admin_control import AdminProfile
    from models.shop_store_commerce import ShopStoreSettings

    campaign_app.db.get(ShopStaff, 7).role = "superadmin"
    campaign_app.db.add(AdminProfile(
        staff_id=7, mfa_secret="offline-enrolled", recovery_hashes="[]",
    ))
    campaign_app.db.commit()
    for store_id, brand in ((STORE_A, "فروشگاه اول"), (DEFAULT_STORE_ID, "فروشگاه اصلی")):
        campaign_app.select_store(store_id)
        saved = await campaign_app.request("PATCH", "/settings", payload={
            "brand_name": brand, "faq_text": "پرسش‌های همین فروشگاه",
        })
        assert saved.status_code == 200, saved.text
        read = await campaign_app.request("GET", "/settings")
        assert read.status_code == 200, read.text
        assert read.json()["brand_name"] == brand
    assert campaign_app.db.get(ShopStoreSettings, STORE_A).brand_name == "فروشگاه اول"
    assert campaign_app.db.get(ShopStoreSettings, DEFAULT_STORE_ID).brand_name == "فروشگاه اصلی"
    unsigned_scope = await campaign_app.request("GET", "/settings", wrapped=False)
    assert unsigned_scope.status_code == 403, unsigned_scope.text


@pytest.mark.asyncio
async def test_nondefault_store_catalog_candidates_use_actual_owners(campaign_app):
    """Nondefault catalog controls expose their own rows and deny other Stores."""
    from models.shop_admin_control import AdminProfile
    from models.shop_content import Product
    from models.shop_uom import default_unit_id
    from services.shop_uom import seed_store_units

    campaign_app.db.get(ShopStaff, 7).role = "superadmin"
    campaign_app.db.add(AdminProfile(
        staff_id=7, mfa_secret="offline-enrolled", recovery_hashes="[]",
    ))
    products = []
    for store_id in (STORE_A, STORE_B):
        seed_store_units(campaign_app.db, store_id)
        product = Product(
            store_id=store_id, sku="same-store-sku", name="Catalog product",
            description="Fixture", price=100, uom_id=default_unit_id(store_id),
        )
        campaign_app.db.add(product)
        products.append(product)
    campaign_app.db.commit()
    choices = await campaign_app.request("GET", f"/bot-catalog/bots/{BOT_A}")
    assert choices.status_code == 200, choices.text
    assert choices.json()["policy_ready"] is True
    assert [item["id"] for item in choices.json()["items"]] == [products[0].id]
    assert choices.json()["default_effect"] == "deny"
    path = f"/bot-catalog/bots/{BOT_A}"
    version = campaign_app.db.get(ShopBot, BOT_A).version
    inherited = await campaign_app.request("GET", f"{path}?effect=inherit&q=Catalog")
    assert inherited.status_code == 200
    assert inherited.json()["version"] == version
    assert inherited.json()["total"] == 1
    empty = await campaign_app.request("GET", f"{path}?effect=allow&q=Catalog")
    assert empty.status_code == 200 and empty.json()["total"] == 0
    change = {
        "expected_version": version, "kind": "product",
        "target_ids": [products[0].id], "effect": "allow",
    }
    session = campaign_app.db.get(AdminSession, campaign_app.session_id)
    session.reauthenticated_at = security.clock() - 2 * security.REAUTH_LIMIT
    campaign_app.db.commit()
    expired = await campaign_app.request("POST", f"{path}/rules", payload=change)
    assert expired.json()["detail"] == "reauthentication_required"
    session.reauthenticated_at = security.clock()
    campaign_app.db.commit()
    saved = await campaign_app.request("POST", f"{path}/rules", payload=change)
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"ok": True, "changed": 1, "version": version + 1}
    conflict = await campaign_app.request("POST", f"{path}/rules", payload=change)
    assert conflict.status_code == 409 and conflict.json()["detail"] == "configuration_changed"
    allowed = await campaign_app.request("GET", f"{path}?effect=allow&q=Catalog")
    assert allowed.status_code == 200 and allowed.json()["total"] == 1
    assert allowed.json()["items"][0]["id"] == products[0].id
    assert allowed.json()["version"] == version + 1
    empty = await campaign_app.request("GET", f"{path}?effect=inherit")
    assert empty.status_code == 200 and empty.json()["total"] == 0
    invalid = await campaign_app.request("GET", f"{path}?effect=other")
    assert invalid.status_code == 422
    bots = await campaign_app.request("GET", f"/bot-catalog/products/{products[0].id}")
    assert bots.status_code == 200, bots.text
    assert {item["id"] for item in bots.json()["bots"]} == {BOT_A, BOT_DRAFT}
    denied = await campaign_app.request(
        "POST", f"/bot-catalog/bots/{BOT_B}/rules", payload={
            "expected_version": 1, "kind": "product",
            "target_ids": [products[1].id], "effect": "allow",
        },
    )
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"] == "store_switch_required"
    campaign_app.select_store(STORE_A)
    hidden = await campaign_app.request("GET", f"/bot-catalog/bots/{BOT_B}")
    assert hidden.status_code == 404, hidden.text


@pytest.mark.asyncio
async def test_customer_case_uses_canonical_same_store_membership(campaign_app):
    """Verified customer membership never merges equal numeric provider IDs."""
    from uuid import uuid4

    from models.shop_store_commerce import ShopStoreCustomer

    campaign_app.db.get(ShopStaff, 7).role = "sales"
    bale = ShopBot(
        id=str(uuid4()), store_id=STORE_A, slug="bale-peer", name="Bale peer",
        platform="bale", status="active", runtime_owner="registry",
    )
    owner = ShopStoreCustomer(store_id=STORE_A)
    other = ShopStoreCustomer(store_id=STORE_B)
    campaign_app.db.add_all([bale, owner, other])
    campaign_app.db.flush()
    identities = [
        ShopIdentity(store_id=STORE_A, bot_id=BOT_A, customer_id=owner.id,
                     platform="telegram", platform_user_id=555),
        ShopIdentity(store_id=STORE_A, bot_id=bale.id, customer_id=owner.id,
                     platform="bale", platform_user_id=777),
        ShopIdentity(store_id=STORE_B, bot_id=BOT_B, customer_id=other.id,
                     platform="telegram", platform_user_id=555),
    ]
    campaign_app.db.add_all(identities)
    campaign_app.db.commit()
    read = await campaign_app.request("GET", f"/customers/{identities[0].id}")
    assert read.status_code == 200, read.text
    assert {item["id"] for item in read.json()["verified_identities"]} == {
        identities[0].id, identities[1].id,
    }
    assert read.json()["verified_other_platform"] == {
        "id": identities[1].id, "platform": "bale", "user_id": "777",
        "approved_at": None,
    }
    campaign_app.select_store(STORE_A)
    hidden = await campaign_app.request("GET", f"/customers/{identities[2].id}")
    assert hidden.status_code == 404, hidden.text


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/health", "/receiver"])
async def test_cached_bot_cannot_bypass_active_store_scope(campaign_app, suffix):
    """Cached bot rows remain hidden before metadata or provider control runs."""
    from models.shop_admin_control import AdminProfile

    campaign_app.db.get(ShopStaff, 7).role = "superadmin"
    campaign_app.db.add(AdminProfile(
        staff_id=7, mfa_secret="offline-enrolled", recovery_hashes="[]",
    ))
    assert campaign_app.db.get(ShopBot, BOT_B) is not None
    campaign_app.select_store(STORE_A)
    response = await campaign_app.request("GET", f"/bot-registry/{BOT_B}{suffix}")
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_selected_other_store_bot_write_requires_switch(campaign_app):
    """A multi-Store read selection never authorizes another Store's Bot write."""
    from models.shop_admin_control import AdminProfile

    campaign_app.db.get(ShopStaff, 7).role = "superadmin"
    campaign_app.db.add(AdminProfile(
        staff_id=7, mfa_secret="offline-enrolled", recovery_hashes="[]",
    ))
    campaign_app.db.commit()
    response = await campaign_app.request(
        "POST", f"/bot-registry/{BOT_B}/credentials/stage", payload={"token": "unused"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "store_switch_required"
