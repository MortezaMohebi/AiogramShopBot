"""Share durable operational choices with the API and long-running workers."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

import config
from models.shop_service_control import ShopServiceControl
from services import shop_admin_security as security

_LOG = logging.getLogger(__name__)
_POLL_SECONDS = 2
# Compatibility flags supply defaults only before an operator overrides them.
FLAGS = {
    "receivers": ("MULTIBOT_V2_RUNTIME_ENABLED",),
    "relay-pool": ("SHOP_RELAY_POOL_ENABLED",),
    "workflow-runtime": ("SHOP_WORKFLOW_RUNTIME_ENABLED",),
    "telegram-fiat": ("TELEGRAM_FIAT_CHECKOUT_ENABLED",),
    "telegram-stars": ("TELEGRAM_STARS_CHECKOUT_ENABLED",),
    "telegram-stars-refunds": ("TELEGRAM_STARS_REFUNDS_ENABLED",),
    "bale-wallet": ("BALE_WALLET_CHECKOUT_ENABLED",),
    "broadcast": ("SHOP_CAMPAIGN_DISPATCH_ENABLED", "SHOP_BROADCAST_WORKER_ENABLED"),
    "bale-paid-broadcast": ("BALE_BROADCAST_PAID_ENABLED",),
    "digital-delivery": ("SHOP_DIGITAL_DELIVERY_ENABLED",),
    "customer-notifications": ("SHOP_CUSTOMER_NOTIFICATIONS_ENABLED",),
    "mcp": ("SHOP_MCP_ENABLED",),
}


@dataclass(frozen=True)
class ServiceSnapshot:
    """One complete process-local view; None means the control DB is unavailable."""

    overrides: Mapping[str, bool | None] | None


_snapshot = ServiceSnapshot({})


def deployment_default(key: str) -> bool:
    """Preserve existing local automation and deployment flags as defaults."""
    if key in {"customer-notifications", "mcp"}:
        return os.environ.get(FLAGS[key][0], "").lower() == "true"
    return all(getattr(config, flag, False) is True for flag in FLAGS[key])


def blocked_reason(key: str) -> str | None:
    """Return safe infrastructure limits that a dashboard switch cannot override."""
    if key == "workflow-runtime" and config.SHOP_WORKFLOW_RUNTIME_KILL_SWITCH:
        return "emergency_stop"
    if key == "telegram-fiat" and not config.TELEGRAM_IRR_MINOR_MULTIPLIER:
        return "irr_provider_unconfigured"
    if key == "bale-paid-broadcast" and (
        config.BALE_BROADCAST_MODE != "business"
        or not config.SHOP_BROADCAST_MAX_PAID_CALLS
    ):
        return "paid_budget_unconfigured"
    if key == "digital-delivery":
        from services.shop_digital_rules import DeliveryPolicyError
        from services.shop_digital_storage import digital_root

        try:
            digital_root(config.SHOP_DIGITAL_ROOT, public_media_root=config.SHOP_MEDIA_ROOT)
        except DeliveryPolicyError:
            return "private_storage_unconfigured"
    if key == "mcp":
        from services.shop_mcp.contracts import McpRejected
        from services.shop_mcp.settings import configured_trust

        try:
            configured_trust()
        except McpRejected:
            return "mcp_trust_unconfigured"
    if key == "relay-pool":
        from services.shop_telegram_transport import approved_worker_origins

        if not approved_worker_origins():
            return "relay_origins_unconfigured"
    return None


def service_enabled(key: str) -> bool:
    """Read the shared service policy without querying on every request."""
    overrides = _snapshot.overrides
    if overrides is None:
        return False
    override = overrides.get(key)
    requested = deployment_default(key) if override is None else override
    return requested and blocked_reason(key) is None


def service_override(key: str) -> bool | None:
    """Preserve callers that validate the raw legacy setting themselves."""
    overrides = _snapshot.overrides
    return False if overrides is None else overrides.get(key)


def registry_broadcast_allowed() -> bool:
    """One dashboard choice enables Registry dispatch; honor the legacy extra flag."""
    overrides = _snapshot.overrides
    if overrides is None:
        return False
    override = overrides.get("broadcast")
    if override is None:
        return getattr(config, "SHOP_BROADCAST_REGISTRY_ENABLED", False) is True
    return override


def read_overrides(db: Session) -> dict[str, bool | None]:
    """Load one coherent, bounded snapshot with no customer or credential data."""
    return dict(db.execute(select(
        ShopServiceControl.key, ShopServiceControl.enabled,
    ).where(ShopServiceControl.key.in_(FLAGS))).all())


def describe_controls(db: Session) -> list[dict]:
    """Report authoritative choices separately from deployment prerequisites."""
    rows = {row.key: row for row in db.scalars(select(ShopServiceControl)).all()}
    result = []
    for key in FLAGS:
        row = rows.get(key)
        override = row.enabled if row is not None else None
        default = deployment_default(key)
        reason = blocked_reason(key)
        result.append({
            "key": key, "override": override, "default": default,
            "enabled": (default if override is None else override) and reason is None,
            "blocked_reason": reason, "version": row.version if row else 0,
        })
    return result


def write_override(
    db: Session, *, key: str, enabled: bool | None,
    expected_version: int, actor_id: int,
) -> dict:
    """Serialize competing writes and audit the change in the same transaction."""
    if key not in FLAGS:
        raise security.SecurityRejected("service_control_not_found", 404)
    if enabled is True and blocked_reason(key):
        raise security.SecurityRejected("service_prerequisite_missing", 409)
    if db.get_bind().dialect.name == "postgresql":
        # An absent row cannot be locked with SELECT FOR UPDATE.
        db.execute(text("SELECT pg_advisory_xact_lock(90211034)"))
    row = db.get(ShopServiceControl, key, populate_existing=True)
    if (row.version if row else 0) != expected_version:
        raise security.SecurityRejected("service_control_conflict", 409)
    if row is None:
        row = ShopServiceControl(key=key, enabled=enabled, version=1)
        db.add(row)
    else:
        row.enabled = enabled
        row.version += 1
    action = "defaulted" if enabled is None else "enabled" if enabled else "disabled"
    security.audit(db, actor_id, "services." + action, key)
    db.flush()
    return {"key": key, "override": enabled, "version": row.version}


async def refresh_controls(session_factory) -> None:
    """Reconcile a running process with committed choices, failing closed on errors."""
    global _snapshot
    try:
        async with asyncio.timeout(_POLL_SECONDS):
            async with session_factory() as db:
                _snapshot = ServiceSnapshot(await db.run_sync(read_overrides))
    except Exception:
        if _snapshot.overrides is not None:
            _LOG.warning("Operational service controls unavailable; new work is paused.")
        _snapshot = ServiceSnapshot(None)


@asynccontextmanager
async def watch_controls(session_factory):
    """Keep this process current until graceful shutdown."""

    async def poll():
        while True:
            await refresh_controls(session_factory)
            await asyncio.sleep(_POLL_SECONDS)

    global _snapshot
    _snapshot = ServiceSnapshot(None)
    task = asyncio.create_task(poll(), name="shop-service-controls")
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        _snapshot = ServiceSnapshot({})
