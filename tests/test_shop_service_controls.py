"""Cover precedence, safety gates and transactional revisions for service switches."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import config
from models.shop_admin_control import AdminEvent
from models.shop_multibot import DEFAULT_STORE_ID, ShopStore
from models.shop_staff import ShopStaff
from services import shop_bot_registry as registry
from services import shop_service_controls as controls
from services.shop_admin_security import SecurityRejected
from tests.schema_support import create_shop_schema
from tests.test_campaign_admin_store_scope import campaign_app


def test_service_controls_keep_legacy_fallback_and_emergency_stop(monkeypatch):
    monkeypatch.setattr(config, "MULTIBOT_V2_RUNTIME_ENABLED", True)
    assert controls.service_enabled("receivers")
    monkeypatch.setattr(controls, "_snapshot", controls.ServiceSnapshot({"receivers": False, "workflow-runtime": True}))
    assert not controls.service_enabled("receivers")
    assert controls.service_enabled("workflow-runtime")
    monkeypatch.setattr(config, "SHOP_WORKFLOW_RUNTIME_KILL_SWITCH", True)
    assert not controls.service_enabled("workflow-runtime")
    monkeypatch.setattr(controls, "_snapshot", controls.ServiceSnapshot(None))
    assert not controls.service_enabled("receivers")


def test_switch_is_versioned_and_audited_atomically(monkeypatch):
    with create_engine("sqlite+pysqlite://").begin() as connection:
        create_shop_schema(connection)
        with Session(connection) as db:
            db.add(ShopStaff(id=1, username="control-admin", password_hash="test",
                             role="superadmin", is_active=True, session_version=1))
            db.flush()
            state = controls.write_override(
                db, key="receivers", enabled=True, expected_version=0, actor_id=1,
            )
            assert state == {"key": "receivers", "override": True, "version": 1}
            assert controls.read_overrides(db) == {"receivers": True}
            with pytest.raises(SecurityRejected, match="service_control_conflict"):
                controls.write_override(
                    db, key="receivers", enabled=False, expected_version=0, actor_id=1,
                )
            events = db.scalars(select(AdminEvent)).all()
            assert [(event.action, event.target) for event in events] == [
                ("services.enabled", "receivers"),
            ]
            assert controls.blocked_reason("telegram-fiat") == "irr_provider_unconfigured"
            controls.write_override(
                db, key="telegram-fiat", enabled=True, expected_version=0, actor_id=1,
            )
            assert controls.read_overrides(db) == {"receivers": True, "telegram-fiat": True}
            pending = next(item for item in controls.describe_controls(db)
                           if item["key"] == "telegram-fiat")
            assert pending["override"] is True
            assert pending["enabled"] is False
            assert pending["blocked_reason"] == "irr_provider_unconfigured"
            monkeypatch.setattr(controls, "_snapshot", controls.ServiceSnapshot(
                controls.read_overrides(db),
            ))
            assert not controls.service_enabled("telegram-fiat")
            monkeypatch.setattr(config, "TELEGRAM_IRR_MINOR_MULTIPLIER", 1)
            assert controls.service_enabled("telegram-fiat")


def test_registered_bot_enables_receiver_default_but_explicit_stop_wins(monkeypatch):
    monkeypatch.setattr(config, "MULTIBOT_V2_RUNTIME_ENABLED", False)
    with create_engine("sqlite+pysqlite://").begin() as connection:
        create_shop_schema(connection)
        with Session(connection) as db:
            db.add(ShopStaff(id=1, username="owner", password_hash="test",
                             role="superadmin", is_active=True, session_version=1))
            db.add(ShopStore(id=DEFAULT_STORE_ID, slug="default", name="Shop", state="active"))
            db.flush()

            def receiver():
                return next(item for item in controls.describe_controls(db)
                            if item["key"] == "receivers")

            assert not receiver()["enabled"]
            bot = registry.register_bot(db, store_id=DEFAULT_STORE_ID, platform="telegram",
                                        name="Draft Telegram", actor_id=1)
            assert receiver()["enabled"] and receiver()["override"] is None
            assert bot.status == "draft" and bot.credential_version is None
            monkeypatch.setattr(controls, "_snapshot", controls.read_snapshot(db))
            assert controls.service_enabled("receivers")
            controls.write_override(db, key="receivers", enabled=False, expected_version=0, actor_id=1)
            assert receiver()["default"] and not receiver()["enabled"]
            monkeypatch.setattr(controls, "_snapshot", controls.read_snapshot(db))
            assert not controls.service_enabled("receivers")


@pytest.mark.asyncio
async def test_refresh_reads_committed_choices_and_fails_closed(monkeypatch):
    from contextlib import asynccontextmanager

    monkeypatch.setattr(controls, "_snapshot", controls.ServiceSnapshot({}))
    monkeypatch.setattr(config, "MULTIBOT_V2_RUNTIME_ENABLED", True)

    class Readable:
        async def run_sync(self, _operation):
            return controls.ServiceSnapshot({"receivers": False, "telegram-stars": True}, has_registered_bots=True)

    @asynccontextmanager
    async def available():
        yield Readable()

    @asynccontextmanager
    async def offline():
        raise OSError("offline test")
        yield

    await controls.refresh_controls(available)
    assert not controls.service_enabled("receivers")
    assert controls.service_enabled("telegram-stars")
    await controls.refresh_controls(offline)
    assert not controls.service_enabled("telegram-stars")


@pytest.mark.asyncio
async def test_dashboard_service_change_requires_role_and_fresh_session(campaign_app):
    from dashboard.next_api import database
    from models.shop_admin_control import AdminSession
    from services import shop_admin_security as security

    app = campaign_app
    app.app.dependency_overrides[database] = app.legacy.dependency_overrides[database]
    payload = {"enabled": True, "expected_version": 0}

    denied = await app.request("POST", "/services/receivers", payload=payload)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "permission_denied"

    member = app.db.get(ShopStaff, 7)
    member.role = "superadmin"
    security.profile_for(app.db, member.id).mfa_secret = "synthetic-enrollment"
    row = app.db.get(AdminSession, app.session_id)
    row.reauthenticated_at = security.clock() - security.REAUTH_LIMIT
    app.db.commit()

    denied = await app.request("POST", "/services/receivers", payload=payload)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "reauthentication_required"
    assert controls.read_overrides(app.db) == {}

    row.reauthenticated_at = security.clock()
    app.db.commit()
    allowed = await app.request("POST", "/services/receivers", payload=payload)
    assert allowed.status_code == 200
    assert controls.read_overrides(app.db) == {"receivers": True}
