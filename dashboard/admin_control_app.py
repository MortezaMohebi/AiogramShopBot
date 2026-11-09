"""Explicit ASGI composition for the revocable administration control plane.

The signed business API and authenticated provider routes share one session
and Store authorization boundary. Internal mutations retain the existing
HMAC verifier;
all authenticated internal requests additionally need a server-side session.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from starlette.responses import JSONResponse

import config
from db import session_maker
from models.shop_staff import ShopStaff
from services.shop_admin_security import (
    SecurityRejected, has_permission, require_recent, validate_session,
)
from services import shop_admin_security as security
from services.shop_store_context import bind_context, resolve_context
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot
from sqlalchemy import select
from dashboard.admin_control_api import router
from dashboard.customer_crm_api import router as customer_router
from dashboard.shop_multibot_api import router as multibot_foundation_router
from dashboard.shop_multibot_management_api import router as multibot_management_router
from dashboard.shop_bot_catalog_api import router as bot_catalog_router
from dashboard.shop_multibot_receiver_api import router as multi_receiver_router
from dashboard.shop_relay_pool_api import router as relay_pool_router
from dashboard.shop_store_commerce_api import router as store_commerce_router
from dashboard.shop_store_context_api import router as store_context_router
from dashboard.shop_uom_api import router as shop_uom_router
from dashboard.shop_model_data_api import router as model_data_router
from dashboard.shop_customer_experience_api import router as customer_experience_router
from dashboard.shop_workflow_api import router as workflow_router
from dashboard.shop_action_api import router as action_router
from dashboard.shop_runtime_api import router as runtime_router
from dashboard.shop_service_control_api import router as service_control_router
from dashboard.shop_pwa_api import router as pwa_router
from dashboard.mcp_api import router as mcp_router
from dashboard.shop_mcp_admin_api import router as mcp_admin_router
from dashboard.shop_mcp_admin_api import account_router as mcp_account_router
from services.shop_runtime.contracts import RuntimeRejected
from dashboard.shop_digital_api import router as digital_router
from dashboard.multibot_webhook import router as multi_webhook_router
from dashboard.next_api import bounded_bridge_body, verify_bridge_signature

PREFIX = "/internal/admin/v1"


def bot_onboarding_route(path: str, method: str) -> bool:
    """Exempt only additive bot setup from repeated administrator proof.

    Session validation, role permissions, Store ownership, verified credentials,
    receiver revision checks, and exclusive worker leases remain mandatory.
    Unknown routes and every destructive method retain the step-up boundary.
    """
    if method != "POST":
        return False
    if path == PREFIX + "/bot-registry":
        return True
    return bool(re.fullmatch(
        re.escape(PREFIX) + r"/bot-registry/"
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/"
        r"(?:credentials/stage|verify|receiver/stage|receiver/check-local|receiver/activate)",
        path,
    ))


def permission_for(path: str, method: str) -> str | None:
    """Map server-owned route families to fixed capabilities; fail closed."""
    resource = path.removeprefix(PREFIX).strip("/").split("/")[0]
    if resource in {"store-context", "data-models"}:
        # Model-specific read/write capabilities are checked a second time
        # inside the typed metadata-driven API, after session validation.
        return "dashboard.read"
    if resource in {"auth", "account", "capabilities", "overview"}:
        return "account.manage_self" if resource in {"auth", "account"} else "dashboard.read"
    if resource == "relay-workers" and path.endswith("/state"):
        return "bots.apply"
    if resource == "bot-registry" and "/relay-routes/" in path and path.endswith(
        ("/activate", "/pause", "/revoke")
    ):
        return "bots.apply"
    if resource == "stores" and path.endswith(
        ("/uoms", "/uom-categories")
    ):
        return "catalog.read" if method == "GET" else "catalog.write"
    if resource == "stores" and path.endswith("/product-attribute-options"):
        return "catalog.read" if method == "GET" else None
    if method == "POST" and re.fullmatch(
        re.escape(PREFIX) + r"/products/[1-9][0-9]*/media/order", path,
    ):
        return "media.manage"
    if resource in {"products", "categories", "catalog-specs"}:
        return "catalog.read" if method == "GET" else "catalog.write"
    if method == "GET" and re.fullmatch(
        re.escape(PREFIX) + r"/media/preview/campaign/[1-9][0-9]*", path,
    ):
        return "campaigns.manage"
    return {
        "media": "media.manage",
        "testimonials": "media.manage",
        "upload": "campaigns.manage" if path.endswith("/campaign") else "media.manage",
        "orders": "orders.read" if method == "GET" else "orders.manage",
        "customers": "customers.read",
        "shipping": "shipping.manage",
        "coupons": "coupons.manage",
        "reports": "reports.read",
        "wallets": "finance.read" if method == "GET" else "wallet.adjust",
        "refunds": "finance.read" if method == "GET" else "refund.execute",
        "settings": "settings.manage",
        "services": "settings.manage",
        "pwa-settings": "settings.manage",
        "referral-policy": "settings.manage",
        "stores": "bots.read" if method == "GET" else "bots.configure",
        "bot-registry": (
            "bots.apply"
            if path.endswith(("/receiver/activate", "/receiver/webhook-url"))
            else "bots.read" if method == "GET" else "bots.configure"
        ),
        "bot-catalog": "bots.read" if method == "GET" else "bots.configure",
        "relay-workers": "bots.read" if method == "GET" else "bots.configure",
        "store-customers": "bots.read",
        "support-tickets": "customers.read",
        "fulfillments": "orders.read" if method == "GET" else "orders.manage",
        "customer-notifications": "bots.read",
        "actions": "workflows.read",
        "mcp": "workflows.read",
        "workflow-runtime": ("workflows.read" if method == "GET" else "workflows.publish" if "/publications/" in path else "workflows.runtime.manage"),
        "workflows": (
            "workflows.read"
            if method == "GET" or path.endswith(("/validate", "/simulate"))
            else "workflows.write"
        ),
        "digital-deliveries": "orders.read",
        "payment-accounts": "bots.read" if method == "GET" else "bots.apply",
        "customer-retention": "audit.read",
        "staff": "staff.manage",
        "campaigns": (
            "broadcast.approve"
            if path.endswith(("/start", "/approve"))
            else "campaigns.manage"
        ),
    }.get(resource)


def store_scoped_campaign_route(path: str, method: str) -> bool:
    """Allow guarded campaign routes and their read-only capability metadata.

    In particular, a campaign upload must not widen unrelated upload targets,
    private media previews or the external provider preparation endpoints.
    """
    route = path.removeprefix(PREFIX)
    if method == "GET":
        metadata = {"/campaigns", "/campaigns/bots", "/capabilities"}
        return route in metadata or bool(re.fullmatch(
            r"/(?:campaigns/[1-9][0-9]*/(?:deliveries|media)"
            r"|media/preview/campaign/[1-9][0-9]*)", route,
        ))
    if method == "POST":
        return route in {"/campaigns", "/upload/campaign"} or bool(re.fullmatch(
            r"/campaigns/[1-9][0-9]*/(?:approve|start|pause|resume|cancel|reconcile|media/order)",
            route,
        ))
    return method == "DELETE" and bool(re.fullmatch(
        r"/campaigns/[1-9][0-9]*/media/[1-9][0-9]*", route,
    ))


def store_scoped_content_route(path: str, method: str) -> bool:
    """Allow audited child mutations that prove their Product's Store owner."""
    route = path.removeprefix(PREFIX)
    if method == "POST":
        return route in {"/upload/product", "/upload/testimonial"}
    return method in {"PATCH", "DELETE"} and bool(re.fullmatch(
        r"/(?:media|testimonials)/[1-9][0-9]*", route,
    ))


def store_scoped_refund_route(path: str, method: str) -> bool:
    """Permit only the refund boundary that verifies its Order's Store owner."""
    return method == "POST" and bool(re.fullmatch(
        re.escape(PREFIX) + r"/refunds/[1-9][0-9]*/resolve", path,
    ))


def session_proof(token: str, bridge_signature: str, secret: str) -> str:
    """Bind the opaque session token to the existing per-request HMAC."""
    return hmac.new(secret.encode(), ("session-v1\n" + bridge_signature + "\n" + token).encode(), hashlib.sha256).hexdigest()


def create_app(base: FastAPI, *, live_receivers: bool = False) -> FastAPI:
    """Compose secure admin routes around a base-owned Registry lifecycle.

    ``live_receivers`` remains accepted for isolated integration callers;
    receiver ownership belongs exclusively to the supplied base lifespan.
    """
    if live_receivers:
        raise ValueError("The base application must own Registry receivers")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with base.router.lifespan_context(base):
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state = base.state

    @app.exception_handler(SecurityRejected)
    async def security_error(_request: Request, error: SecurityRejected):
        return JSONResponse({"detail": error.code}, status_code=error.status,
                            headers={"Cache-Control": "no-store"})

    @app.middleware("http")
    async def session_boundary(request: Request, call_next):
        path = request.url.path
        # Retired administration routes cannot bypass MFA/session revocation.
        retired = {
            "bot-connections", "bot-profiles", "connection-changes",
            "telegram-transport", "channel-features", "payment-rails", "broadcast",
        }
        resource = path.removeprefix(PREFIX + "/").split("/")[0]
        if (
            path == "/admin" or path.startswith("/admin/")
            or (path.startswith(PREFIX + "/") and resource in retired)
        ):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        if not path.startswith(PREFIX + "/") or path in {
            PREFIX + "/auth/login",
            PREFIX + "/auth/redeem",
            PREFIX + "/auth/owner-setup",
        }:
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
                        PREFIX + "/account/mfa-confirm", PREFIX + "/account/verify-password",
                    }
                    if not enrolled and path not in enrollment_routes:
                        raise SecurityRejected("mfa_enrollment_required", 428)
                permission = permission_for(path, request.method)
                if permission is None or not has_permission(staff.role, permission):
                    raise SecurityRejected("permission_denied")
                if ((path.startswith(PREFIX + "/data-models") and path.endswith("/import")) or path.startswith(PREFIX + "/staff") or path.startswith(PREFIX + "/bot-registry") or path.startswith(PREFIX + "/relay-workers") or path.startswith(PREFIX + "/payment-accounts") or path.startswith(PREFIX + "/bot-catalog") or path.startswith(PREFIX + "/stores") or (path.startswith(PREFIX + "/products/") and path.endswith(("/digital-file", "/digital-licenses"))) or path.startswith(PREFIX + "/customer-retention") or (path.startswith(PREFIX + "/customers") and (request.method != "GET" or path.endswith("/export")))) and (request.method != "GET" or path.endswith("/export")):
                    if not bot_onboarding_route(path, request.method):
                        require_recent(row)
                resource = path.removeprefix(PREFIX).strip("/").split("/")[0]
                if resource in {"services", "pwa-settings"} and request.method != "GET":
                    require_recent(row)
                request.state.admin_session_id = row.id
                # Only session-authenticated requests can acquire StoreContext.
                # A user's allowed set is always re-read from active grants;
                # no browser header, Cookie or query can widen it.
                scope = None
                if resource not in {"auth", "account", "services", "pwa-settings"}:
                    scope = await resolve_context(
                        db, staff_id=staff.id, session_id=row.id,
                    )
                    request.state.store_context = scope
                    if resource == "bot-registry":
                        target = path.removeprefix(
                            PREFIX + "/bot-registry/",
                        ).split("/")[0]
                        if re.fullmatch(r"[0-9a-fA-F-]{36}", target):
                            bot = await db.scalar(select(ShopBot).where(
                                ShopBot.id == target.lower(),
                                ShopBot.store_id.in_(scope.active_store_ids),
                                ShopBot.runtime_owner == "registry",
                            ))
                            if bot is None:
                                raise SecurityRejected("bot_not_found", 404)
                            scope.require(
                                bot.store_id,
                                write=request.method not in {"GET", "HEAD"},
                            )
                    multi_safe = {
                        "store-context",
                        "staff",
                        "stores",
                        "store-customers",
                        "payment-accounts",
                        "bot-registry",
                        "bot-catalog",
                        "products",
                        "categories",
                        "catalog-specs",
                        "orders",
                        "customers",
                        "overview",
                        "reports",
                        "settings",
                        "shipping",
                        "coupons",
                        "data-models",
                        "support-tickets",
                        "fulfillments",
                        "customer-notifications",
                        "digital-deliveries",
                        "wallets",
                        "workflows",
                        "actions",
                        "workflow-runtime",
                        "mcp",
                    }
                    # Read-only financial views have explicit Store joins and
                    # may aggregate safely. Mutation handlers stay unavailable
                    # in a multi-Store selection until independently audited.
                    if request.method == "GET":
                        multi_safe.update({
                            "media", "testimonials", "refunds", "wallets",
                        })
                    if (
                        resource not in multi_safe
                        and not store_scoped_campaign_route(path, request.method)
                        and not store_scoped_content_route(path, request.method)
                        and not store_scoped_refund_route(path, request.method)
                    ) and (
                        scope.current_store_id != DEFAULT_STORE_ID
                        or set(scope.active_store_ids) != {DEFAULT_STORE_ID}
                    ):
                        raise SecurityRejected("store_scope_not_supported", 409)
                    workflow_read = resource == "workflows" and request.method == "POST" and bool(re.fullmatch(
                        re.escape(PREFIX) + r"/workflows/[0-9a-fA-F-]{36}/(?:validate|simulate)", path,
                    ))
                    action_read = (
                        resource == "actions"
                        and path == PREFIX + "/actions/dry-run"
                        and request.method == "POST"
                    )
                    if (
                        not workflow_read
                        and not action_read
                        and request.method not in {"GET", "HEAD"}
                        and resource
                        not in {
                            "store-context",
                            "mcp",
                        }
                    ):
                        scope.require(
                            scope.current_store_id,
                            write=True,
                            manage=resource in {"stores", "staff"},
                        )
                    if resource == "stores" and path.count("/") >= 5:
                        # A targeted Store policy cannot use another Store
                        # merely because both are selected for reads.
                        target = path.split("/")[5] if len(path.split("/")) > 5 else ""
                        if target and target not in {"commerce", "payment-accounts"}:
                            scope.require(
                                target, write=request.method != "GET",
                            )
                await db.commit()
            if scope is None:
                return await call_next(request)
            with bind_context(scope):
                return await call_next(request)
        except SecurityRejected as error:
            return JSONResponse({"detail": error.code}, status_code=error.status,
                                headers={"Cache-Control": "no-store"})
        except HTTPException as error:
            # Body limits run before FastAPI's exception middleware. Preserve
            # their safe HTTP status instead of leaking an unhandled500.
            code = "request_too_large" if error.status_code == 413 else "invalid_request"
            return JSONResponse({"detail": code}, status_code=error.status_code,
                                headers={"Cache-Control": "no-store"})

    # Explicit top-level routes win before the base application mount.
    app.include_router(router)
    app.include_router(customer_router)
    app.include_router(multibot_foundation_router)
    app.include_router(multibot_management_router)
    app.include_router(bot_catalog_router)
    app.include_router(multi_receiver_router)
    app.include_router(relay_pool_router)
    app.include_router(store_commerce_router)
    app.include_router(store_context_router)
    app.include_router(shop_uom_router)
    app.include_router(model_data_router)
    app.include_router(customer_experience_router)
    app.include_router(workflow_router)
    app.include_router(action_router)
    app.include_router(runtime_router)
    app.include_router(service_control_router)
    app.include_router(pwa_router)
    app.include_router(mcp_router)
    app.include_router(mcp_admin_router)
    app.include_router(mcp_account_router)
    @app.exception_handler(RuntimeRejected)
    async def runtime_rejected(_request, error):
        return JSONResponse({"detail": error.code}, status_code=error.status, headers={"Cache-Control": "no-store"})

    app.include_router(digital_router)
    # Public provider callbacks are authenticated by opaque route credentials.
    app.include_router(multi_webhook_router)
    app.mount("/", base)
    return app
