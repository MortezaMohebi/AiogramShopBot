"""Authoritative staff inspection services; no customer impersonation or execution UI."""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select

from models.shop_action import ShopActionExecution
from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import ShopBot, ShopStore
from services import shop_admin_security as security
from services.shop_actions.catalog import actions
from services.shop_actions.context import staff_principal
from services.shop_actions.contracts import ActionRejected, Invocation
from services.shop_actions.definitions import definitions
from services.shop_actions.execution import invoke
from services.shop_channel_features import get_features
from services.shop_workflow_bindings import authorize


async def environment(db, *, scope, actor, store_id=None, bot_id=None, platform=None):
    """Resolve inspected ownership from live Store/Bot rows, never from role claims."""
    owner = store_id or scope.current_store_id
    authorize(actor, scope, store_id=owner)
    store = await db.get(ShopStore, owner)
    bot, features, operations = None, None, None
    if bot_id is not None:
        bot = await db.scalar(
            select(ShopBot).where(ShopBot.id == bot_id, ShopBot.store_id == owner)
        )
        if bot is None:
            raise security.SecurityRejected("action_bot_unavailable", 404)
        if platform is not None and platform != bot.platform:
            raise security.SecurityRejected("action_platform_mismatch", 422)
        features = await get_features(db, bot.platform, bot_id=bot.id)
        operations = await db.get(ShopBotOperations, bot.id)
    return owner, store, bot, features, operations


def contextual_view(descriptor, env, actor) -> dict:
    """Separate customer-service readiness from staff's limited dry-run authority."""
    owner, store, bot, features, operations = env
    reasons = []
    if not descriptor.service_available:
        reasons.append(descriptor.unavailable_reason or "action_service_unavailable")
    if store is None or store.state != "active":
        reasons.append("action_store_unavailable")
    if bot is None:
        reasons.append("action_bot_required")
    else:
        active = (bot.runtime_owner == "legacy" and bot.status == "legacy") or (
            bot.runtime_owner == "registry"
            and bot.status == "active"
            and bot.credential_version is not None
        )
        if not active or (
            operations is not None and operations.desired_state != "active"
        ):
            reasons.append("action_bot_unavailable")
        if bot.platform not in descriptor.platforms:
            reasons.append("action_platform_unavailable")
        if descriptor.category in {"cart", "checkout"} and not features.cart_enabled:
            reasons.append("action_cart_disabled")
    return descriptor.model_dump(mode="json") | {
        "availability": {"available": not reasons, "reasons": reasons},
        "can_dry_run": not reasons
        and descriptor.category == "catalog"
        and "staff" in descriptor.allowed_actors
        and security.has_permission(actor.role, "catalog.read"),
        "store_id": owner,
        "customer_confirmation_policy": (
            "required"
            if descriptor.confirmation in {"customer_confirmation", "both"}
            else "none"
        ),
        "operator_approval_policy": (
            "required"
            if descriptor.confirmation in {"operator_approval", "both"}
            else "none"
        ),
    }


async def catalog_view(
    db,
    *,
    scope,
    actor,
    q="",
    category="",
    side_effect="",
    deprecated="all",
    page=1,
    page_size=50,
    store_id=None,
    bot_id=None,
    platform=None,
):
    """Filter/paginate safe typed metadata, including registered unavailable Actions."""
    env = await environment(
        db,
        scope=scope,
        actor=actor,
        store_id=store_id,
        bot_id=bot_id,
        platform=platform,
    )
    candidates = [item.descriptor for item in definitions()]
    if q:
        candidates = [
            item
            for item in candidates
            if q.casefold() in (item.key + " " + item.name).casefold()
        ]
    if category:
        candidates = [item for item in candidates if item.category == category]
    if side_effect:
        candidates = [item for item in candidates if item.side_effect == side_effect]
    if deprecated != "all":
        candidates = [
            item for item in candidates if item.deprecated == (deprecated == "true")
        ]
    total = len(candidates)
    actual_page = min(page, max(1, (total + page_size - 1) // page_size))
    selected = candidates[(actual_page - 1) * page_size : actual_page * page_size]
    return {
        "items": [contextual_view(item, env, actor) for item in selected],
        "total": total,
        "page": actual_page,
        "has_more": actual_page * page_size < total,
        "store_id": env[0],
        "bot_id": env[2].id if env[2] else None,
        "platform": env[2].platform if env[2] else None,
        "runtime_available": False,
        "can_inspect_data": security.has_permission(actor.role, "catalog.read"),
    }


async def detail_view(db, *, scope, actor, key, version, bot_id=None, platform=None):
    """Read an exact public descriptor without accepting a method/service name."""
    try:
        spec = actions().resolve(key, version)
    except ActionRejected as error:
        raise security.SecurityRejected(error.code, 404) from None
    env = await environment(
        db, scope=scope, actor=actor, bot_id=bot_id, platform=platform
    )
    return contextual_view(spec.descriptor, env, actor)


async def bot_choices(db, *, scope, actor, page=1, q=""):
    """List owned Bot names/status only, including disabled Bots for diagnosis."""
    authorize(actor, scope)
    query = select(ShopBot).where(ShopBot.store_id == scope.current_store_id)
    if q:
        from services.shop_model_registry import escape_like

        query = query.where(ShopBot.name.ilike("%" + escape_like(q) + "%", escape="\\"))
    rows = (
        await db.scalars(
            query.order_by(ShopBot.name, ShopBot.id).offset((page - 1) * 100).limit(101)
        )
    ).all()
    return {
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "status": item.status,
                "platform": item.platform,
            }
            for item in rows[:100]
        ],
        "page": page,
        "has_more": len(rows) > 100,
    }


async def dry_run(db, *, scope, actor, payload):
    """Allow only staff-authorized Catalog reads; never impersonate a customer."""
    authorize(actor, scope)
    try:
        spec = actions().resolve(payload.action_key, payload.action_version)
    except ActionRejected as error:
        raise security.SecurityRejected(error.code, 404) from None
    if spec.descriptor.category != "catalog" or spec.descriptor.side_effect not in {
        "none",
        "read_only",
    }:
        raise security.SecurityRejected("action_dry_run_forbidden", 403)
    security.require_permission(actor.role, "catalog.read")
    await environment(
        db, scope=scope, actor=actor, bot_id=payload.bot_id, platform=payload.platform
    )
    try:
        principal = await staff_principal(
            db, scope=scope, actor=actor, bot_id=payload.bot_id
        )
    except ActionRejected:
        raise security.SecurityRejected("action_dry_run_unavailable", 409) from None
    result = await invoke(
        db,
        principal,
        Invocation(
            invocation_id=str(uuid4()),
            action_key=payload.action_key,
            action_version=payload.action_version,
            input=payload.input,
            mode="dry_run",
            correlation_id=str(uuid4()),
        ),
    )
    return result.model_dump(mode="json")


async def receipt_view(db, *, scope, actor, invocation_id):
    """Require an audit role and current Store manager before exposing safe receipts."""
    authorize(actor, scope)
    security.require_permission(actor.role, "audit.read")
    scope.require(scope.current_store_id, manage=True)
    row = await db.scalar(
        select(ShopActionExecution).where(
            ShopActionExecution.id == invocation_id,
            ShopActionExecution.store_id == scope.current_store_id,
        )
    )
    if row is None:
        raise security.SecurityRejected("action_receipt_not_found", 404)
    return {
        "invocation_id": row.id,
        "action_key": row.action_key,
        "action_version": row.action_version,
        "store_id": row.store_id,
        "bot_id": row.bot_id,
        "actor": row.actor_key,
        "workflow_id": row.workflow_id,
        "workflow_revision": row.workflow_revision,
        "workflow_run_id": row.workflow_run_id,
        "node_id": row.node_id,
        "status": row.status,
        "side_effect": row.side_effect,
        "retry_count": row.retry_count,
        "correlation_id": row.correlation_id,
        "input_sha256": row.input_sha256,
        "started_at": security.utc(row.started_at).isoformat(),
        "finished_at": (
            security.utc(row.finished_at).isoformat() if row.finished_at else None
        ),
        "result": json.loads(row.result_json),
    }


async def workflow_report(db, *, scope, actor, store_id, definition):
    """Enrich graph validation with live Action availability across assigned Bots.

    Group equivalent policy combinations in SQL: the number of inspected groups
    depends on finite policy states, never on a fixed limit on registered Bots.
    The existing feature resolver remains authoritative for each representative.
    Findings aggregate by node/platform/reason so output cannot grow per Bot.
    """
    from sqlalchemy import func
    from models.shop_channel_features import ShopChannelFeature
    from models.shop_store_commerce import ShopBotCommercePolicy
    from services.shop_actions.definitions import definition as lookup
    from services.shop_workflow_validation import validate_definition

    report = validate_definition(definition).model_dump(mode="json")
    nodes = [node for node in definition.nodes if node.type == "action"]
    if not nodes:
        return report
    groups = (
        ShopBot.platform,
        ShopBot.status,
        ShopBot.runtime_owner,
        ShopBot.credential_version.is_(None),
        ShopBotOperations.desired_state,
        ShopBotCommercePolicy.cart_enabled,
        ShopChannelFeature.cart_enabled,
    )
    query = (
        select(func.min(ShopBot.id))
        .outerjoin(ShopBotOperations, ShopBotOperations.bot_id == ShopBot.id)
        .outerjoin(ShopBotCommercePolicy, ShopBotCommercePolicy.bot_id == ShopBot.id)
        .outerjoin(ShopChannelFeature, ShopChannelFeature.platform == ShopBot.platform)
        .where(
            ShopBot.store_id == store_id,
            ShopBot.platform.in_(definition.target_platforms),
        )
    )
    if definition.assignment.mode == "selected":
        query = query.where(ShopBot.id.in_(definition.assignment.bot_ids))
    else:
        query = query.where(ShopBot.status.in_(("active", "legacy")))
    samples = (await db.scalars(query.group_by(*groups))).all()
    environments = [
        await environment(
            db, scope=scope, actor=actor, store_id=store_id, bot_id=bot_id
        )
        for bot_id in samples
    ]
    seen = set()
    for node in nodes:
        contract = lookup(node.config["action_key"], node.config["action_version"])
        if contract is None:
            continue
        for platform in definition.target_platforms:
            matching = [env for env in environments if env[2].platform == platform]
            reasons = set()
            if not matching:
                reasons.add("action_bot_required")
            for env in matching:
                reasons.update(
                    contextual_view(contract.descriptor, env, actor)["availability"][
                        "reasons"
                    ]
                )
            for reason in sorted(reasons):
                key = (node.id, platform, reason)
                if key in seen:
                    continue
                seen.add(key)
                report["issues"].append(
                    {
                        "code": reason,
                        "message": "این Action برای یکی از Contextهای ربات آماده نیست؛ Action Catalog را بررسی کنید.",
                        "severity": "warning",
                        "node_id": node.id,
                        "field": "action_key",
                        "platform": platform,
                        "blocks_activation": True,
                    }
                )
    return report
