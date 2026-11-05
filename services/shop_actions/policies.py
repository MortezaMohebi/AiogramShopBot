"""Contextual availability is independent of provider workers and UI visibility."""

from services.shop_actions.contracts import ActionRejected
from services.shop_bot_catalog_acl import resolve_scope
from services.shop_channel_features import get_features


async def availability(db, principal, spec, invocation=None) -> dict:
    """Report structured reasons without granting access through metadata."""
    descriptor = spec.descriptor
    reasons = []
    context = {
        "store": principal.store_id,
        "bot": principal.bot_id,
        "customer": principal.customer_id,
        "administrator": principal.staff_id,
        "workflow": invocation.workflow_id if invocation else None,
        "node": invocation.node_id if invocation and invocation.workflow_id else None,
    }
    if any(not context[key] for key in descriptor.required_context):
        reasons.append("action_context_required")
    if principal.actor_kind not in descriptor.allowed_actors:
        reasons.append("action_actor_not_allowed")
    if not set(descriptor.required_scopes) <= principal.scopes:
        reasons.append("action_forbidden")
    if principal.platform not in descriptor.platforms:
        reasons.append("action_platform_unavailable")
    if not descriptor.service_available:
        reasons.append(descriptor.unavailable_reason or "action_service_unavailable")
    if descriptor.category in {"catalog", "cart", "checkout"}:
        scope = await resolve_scope(db, bot_id=principal.bot_id)
        if not scope.available or scope.store_id != principal.store_id:
            reasons.append("action_catalog_unavailable")
    if descriptor.category in {"cart", "checkout"}:
        features = await get_features(db, principal.platform, bot_id=principal.bot_id)
        if not features.cart_enabled:
            reasons.append("action_cart_disabled")
    return {"available": not reasons, "reasons": reasons}


async def require_available(db, principal, spec, invocation=None) -> None:
    """Deny an Action before reading business data or attempting a mutation."""
    result = await availability(db, principal, spec, invocation)
    if result["reasons"]:
        raise ActionRejected(result["reasons"][0])
