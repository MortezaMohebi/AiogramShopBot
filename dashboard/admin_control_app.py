"""Explicit ASGI composition for the revocable administration control plane.

The original business app is mounted unchanged. Only authentication/account
routes are replaced. Internal mutations retain the existing HMAC verifier;
all authenticated internal requests additionally need a server-side session.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

import config
from db import session_maker
from models.shop_staff import ShopStaff
from services.shop_admin_security import (
    SecurityRejected, has_permission, require_recent, validate_session,
)
from services import shop_admin_security as security
from dashboard.admin_control_api import router
from dashboard.customer_crm_api import router as customer_router
from dashboard.bot_profile_api import router as bot_profile_router
from dashboard.payment_rails_api import router as payment_rails_router
from dashboard.telegram_transport_api import router as telegram_transport_router
from dashboard.shop_multibot_api import router as multibot_foundation_router
from dashboard.shop_multibot_management_api import router as multibot_management_router
from dashboard.shop_bot_catalog_api import router as bot_catalog_router
from dashboard.shop_multibot_receiver_api import router as multi_receiver_router
from dashboard.shop_relay_pool_api import router as relay_pool_router
from dashboard.shop_store_commerce_api import router as store_commerce_router
from dashboard.multibot_webhook import router as multi_webhook_router
from dashboard.next_api import bounded_bridge_body, verify_bridge_signature

PREFIX = "/internal/admin/v1"


def permission_for(path: str, method: str) -> str | None:
    """Map server-owned route families to fixed capabilities; fail closed."""
    resource = path.removeprefix(PREFIX).strip("/").split("/")[0]
    if resource in {"auth", "account", "capabilities", "overview"}:
        return "account.manage_self" if resource in {"auth", "account"} else "dashboard.read"
    if resource == "telegram-transport" and path.endswith("/apply"):
        return "bots.apply"
    if resource == "relay-workers" and path.endswith("/state"):
        return "bots.apply"
    if resource == "bot-registry" and "/relay-routes/" in path and path.endswith(
        ("/activate", "/pause", "/revoke")
    ):
        return "bots.apply"
    if resource in {"products", "categories"}:
        return "catalog.read" if method == "GET" else "catalog.write"
    return {
        "media": "media.manage", "testimonials": "media.manage",
        "upload": "campaigns.manage" if path.endswith("/campaign") else "media.manage",
        "orders": "orders.read" if method == "GET" else "orders.manage",
        "customers": "customers.read", "shipping": "shipping.manage",
        "coupons": "coupons.manage", "reports": "reports.read",
        "wallets": "finance.read" if method == "GET" else "wallet.adjust",
        "refunds": "finance.read" if method == "GET" else "refund.execute",
        "settings": "settings.manage", "referral-policy": "settings.manage",
        "channel-features": "settings.manage",
        "bot-profiles": "bots.read" if method == "GET" else "bots.configure",
        "payment-rails": "settings.manage",
        "stores": "bots.read" if method == "GET" else "bots.configure",
        "bot-registry": (
            "bots.apply" if path.endswith("/receiver/activate")
            else "bots.read" if method == "GET" else "bots.configure"
        ),
        "bot-catalog": "bots.read" if method == "GET" else "bots.configure",
        "relay-workers": "bots.read" if method == "GET" else "bots.configure",
        "store-customers": "bots.read",
        "payment-accounts": "bots.read" if method == "GET" else "bots.apply",
        "telegram-transport": "bots.read" if method == "GET" else "bots.configure",
        "customer-retention": "audit.read",
        "staff": "staff.manage", "broadcast": "broadcast.approve",
        "campaigns": "broadcast.approve" if path.endswith(("/start", "/approve")) else "campaigns.manage",
        "bot-connections": "bots.read" if method == "GET" else "bots.configure",
        "connection-changes": "bots.read" if method == "GET" else "bots.configure",
    }.get(resource)


def session_proof(token: str, bridge_signature: str, secret: str) -> str:
    """Bind the opaque session token to the existing per-request HMAC."""
    return hmac.new(secret.encode(), ("session-v1\n" + bridge_signature + "\n" + token).encode(), hashlib.sha256).hexdigest()


def create_app(legacy: FastAPI, *, live_receivers: bool = False) -> FastAPI:
    """Wrap the original app without mutating its routes or dependencies."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        supervisor = None
        multi_supervisor = None
        # Legacy startup must not silently register/delete provider webhooks.
        # The supervised controller now owns all receiver-mode transitions.
        original_mode = config.TELEGRAM_UPDATE_MODE
        if live_receivers:
            os.environ["CODESPACE_MANUAL_WEBHOOK"] = "true"
            config.TELEGRAM_UPDATE_MODE = "webhook"
        try:
            async with legacy.router.lifespan_context(legacy):
                config.TELEGRAM_UPDATE_MODE = original_mode
                try:
                    if live_receivers:
                        from services.shop_connection_runtime import ConnectionSupervisor

                        supervisor = ConnectionSupervisor(legacy)
                        await supervisor.start()
                        if config.MULTIBOT_V2_RUNTIME_ENABLED:
                            from services.shop_multibot_supervisor import MultiBotSupervisor

                            multi_supervisor = MultiBotSupervisor(legacy)
                            await multi_supervisor.start()
                    yield
                finally:
                    if multi_supervisor is not None:
                        await multi_supervisor.close()
                    if supervisor:
                        await supervisor.close()
        finally:
            config.TELEGRAM_UPDATE_MODE = original_mode

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state = legacy.state

    @app.exception_handler(SecurityRejected)
    async def security_error(_request: Request, error: SecurityRejected):
        return JSONResponse({"detail": error.code}, status_code=error.status,
                            headers={"Cache-Control": "no-store"})

    @app.middleware("http")
    async def session_boundary(request: Request, call_next):
        path = request.url.path
        # The old password-only SQLAdmin must not bypass MFA/session revocation.
        if path == "/admin" or path.startswith("/admin/"):
            return JSONResponse({"detail": "Use the Next.js administration panel"}, status_code=404)
        if not path.startswith(PREFIX + "/") or path in {PREFIX + "/auth/login", PREFIX + "/auth/redeem"}:
            return await call_next(request)
        try:
            if not config.NEXT_ADMIN_BRIDGE_ENABLED or len(config.NEXT_ADMIN_BRIDGE_SECRET) < 32:
                raise SecurityRejected("security_service_unavailable", 503)
            token = request.headers.get("x-shop-session", "")
            proof = request.headers.get("x-shop-session-proof", "")
            if (not re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
                    or not re.fullmatch(r"[0-9a-f]{64}", proof)
                    or not hmac.compare_digest(proof, session_proof(
                        token, request.headers.get("x-shop-signature", ""), config.NEXT_ADMIN_BRIDGE_SECRET))):
                raise SecurityRejected("session_expired", 401)
            try:
                staff_id = int(request.headers.get("x-shop-staff", "0"))
                version = int(request.headers.get("x-shop-version", "0"))
            except ValueError:
                raise SecurityRejected("session_expired", 401) from None
            # Check the original request signature BEFORE touching session state.
            target = path + ("?" + request.url.query if request.url.query else "")
            body = await bounded_bridge_body(request)
            if not verify_bridge_signature(
                secret=config.NEXT_ADMIN_BRIDGE_SECRET,
                timestamp=request.headers.get("x-shop-time", ""),
                method=request.method, target=target, body=body,
                staff_id=staff_id, session_version=version,
                signature=request.headers.get("x-shop-signature", ""),
            ):
                raise SecurityRejected("session_expired", 401)
            async with session_maker() as db:
                staff = await db.get(ShopStaff, staff_id)
                if staff is None or staff.session_version != version:
                    raise SecurityRejected("session_expired", 401)
                row = await db.run_sync(lambda sync: validate_session(sync, staff, token))
                # Sensitive roles are confined to first-login enrollment until MFA
                # is verified; an existing password-only administrator is not locked out.
                if staff.role in security.MFA_REQUIRED_ROLES:
                    enrolled = await db.run_sync(
                        lambda sync: bool(security.profile_for(sync, staff.id).mfa_secret)
                    )
                    enrollment_routes = {
                        PREFIX + "/auth/me", PREFIX + "/auth/logout",
                        PREFIX + "/account", PREFIX + "/account/mfa-setup",
                        PREFIX + "/account/mfa-confirm",
                    }
                    if not enrolled and path not in enrollment_routes:
                        raise SecurityRejected("mfa_enrollment_required", 428)
                permission = permission_for(path, request.method)
                if permission is None or not has_permission(staff.role, permission):
                    raise SecurityRejected("permission_denied")
                if (path.startswith(PREFIX + "/staff") or path.startswith(PREFIX + "/channel-features") or path.startswith(PREFIX + "/bot-profiles") or path.startswith(PREFIX + "/payment-rails") or path.startswith(PREFIX + "/telegram-transport") or path.startswith(PREFIX + "/bot-registry") or path.startswith(PREFIX + "/relay-workers") or path.startswith(PREFIX + "/payment-accounts") or path.startswith(PREFIX + "/bot-catalog") or path.startswith(PREFIX + "/stores") or path.startswith(PREFIX + "/customer-retention") or (path.startswith(PREFIX + "/customers") and (request.method != "GET" or path.endswith("/export")))) and (request.method != "GET" or path.endswith("/export")):
                    require_recent(row)
                request.state.admin_session_id = row.id
                await db.commit()
            return await call_next(request)
        except SecurityRejected as error:
            return JSONResponse({"detail": error.code}, status_code=error.status,
                                headers={"Cache-Control": "no-store"})

    # Explicit top-level routes win before the legacy fallback mount.
    app.include_router(router)
    app.include_router(customer_router)
    app.include_router(bot_profile_router)
    app.include_router(payment_rails_router)
    app.include_router(telegram_transport_router)
    app.include_router(multibot_foundation_router)
    app.include_router(multibot_management_router)
    app.include_router(bot_catalog_router)
    app.include_router(multi_receiver_router)
    app.include_router(relay_pool_router)
    app.include_router(store_commerce_router)
    # Public provider callbacks are authenticated by opaque route credentials.
    app.include_router(multi_webhook_router)
    app.mount("/", legacy)
    return app
