"""Dispatch a closed typed designer tool through fresh native authority."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy import select

from models.shop_multibot import ShopBot
from services import shop_action_catalog as actions
from services import shop_admin_security as security
from services import shop_workflows as workflows
from services.shop_mcp import changes, grants, journal, mutations
from services.shop_mcp.catalog import BY_NAME
from services.shop_mcp.contracts import McpRejected
from services.shop_platform_capabilities import platform_capabilities
from services.shop_store_context import bind_context
from services.shop_workflow_bindings import validate_bindings
from services.shop_workflow_schema import Definition


async def authorize(db, delegation, name: str, arguments: dict):
    """Check types and lock Store before authority for effectful tools."""
    tool = BY_NAME.get(name)
    if tool is None:
        raise McpRejected("mcp_tool_not_found", 404)
    try:
        request = tool.request.model_validate(arguments)
        data = request.model_dump(mode="json")
        if getattr(request, "patches", None) is not None:
            # Omitted patch fields mean "preserve". Materializing optional
            # defaults here would turn an incremental edit into null writes.
            data["patches"] = [
                patch.model_dump(mode="json", exclude_unset=True)
                for patch in request.patches
            ]
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise McpRejected("mcp_invalid_request", 422) from None
    principal = await grants.resolve_grant(
        db,
        delegation=delegation,
        store_id=data["store_id"],
        required_scope=tool.scopes[0],
        write=tool.write,
    )
    for requested in tool.scopes[1:]:
        if requested not in principal.scopes:
            raise McpRejected("mcp_scope_required", 403)
        capability, minimum = grants.SCOPE_CAPABILITIES[requested]
        if not security.has_permission(principal.actor.role, capability):
            raise McpRejected("mcp_permission_denied", 403)
        principal.scope.require(
            data["store_id"],
            write=minimum == "editor",
            manage=minimum == "manager",
        )
    return tool, principal, data


async def dispatch(db, principal, name: str, arguments: dict) -> dict:
    """Use the same authority boundary for HTTP callers and internal tests."""
    try:
        tool, current, data = await authorize(
            db,
            principal.delegation,
            name,
            arguments,
        )
        return await invoke_authorized(db, tool, current, data)
    except McpRejected:
        await db.rollback()
        raise
    except security.SecurityRejected as rejected:
        await db.rollback()
        raise McpRejected(rejected.code, rejected.status) from None


async def invoke_authorized(db, tool, current, data):
    """Execute after ``authorize`` locks and checks native authority.

    The HTTP route consumes its nonce between authorization and this internal
    call. It must not reacquire Store locks after taking authority SHARE locks.
    """
    with bind_context(current.scope):
        if tool.write:
            receipt, result = await journal.begin(db, current, tool.name, data)
            if result is not None:
                return result
            result = await _write(db, current, tool.name, data)
            return await journal.finish(db, receipt, result)
        return await _read(db, current, tool.name, data)


async def _write(db, principal, name, data):
    """Explicitly map reversible tools and frozen sensitive proposals."""
    sensitive = {
        "workflow.prepare_publish": "workflow.publish",
        "workflow.prepare_rollback": "workflow.rollback",
        "runtime.prepare_gate": "runtime.gate",
        "runtime.prepare_retry": "runtime.retry",
        "runtime.prepare_cancel": "runtime.cancel",
        "runtime.prepare_delivery_retry": "runtime.delivery_retry",
    }
    if name in sensitive:
        from services.shop_mcp.preparations import prepare

        return await prepare(db, principal, sensitive[name], data)
    if name == "changes.create":
        base = await mutations.base(
            db,
            principal,
            data["workflow_id"],
            data["expected_revision"],
        )
        return await changes.create(
            db,
            principal,
            identity=data["id"],
            workflow_id=data["workflow_id"],
            base=base,
            proposal=changes.edit(base, data),
            operation_id=data["operation_id"],
        )
    if name == "changes.update":
        return await changes.update(db, principal, data)
    if name == "changes.apply":
        return await changes.apply(db, principal, data)
    if name == "changes.cancel":
        return await changes.cancel(db, principal, data)
    return await mutations.mutate(db, principal, name, data)


async def _read(db, principal, name, data):
    """Call only known read services and return privacy-limited projections."""
    common = {"scope": principal.scope, "actor": principal.actor}
    values = {key: value for key, value in data.items() if key != "store_id"}
    if name == "context.get_profile":
        return {
            "native_staff_id": principal.actor.id,
            "grant_id": principal.grant.id,
            "grant_version": principal.grant.version,
            "scopes": sorted(principal.scopes),
            "store_ids": list(principal.scope.allowed_store_ids)
            if principal.scope
            else [],
            "approval_authority": "wpmcp",
        }
    if name == "context.list_stores":
        return {
            "items": [
                {
                    "id": item.id,
                    "name": item.name,
                    "access_level": item.access_level,
                }
                for item in (
                    principal.scope.allowed_stores if principal.scope else ()
                )
            ]
        }
    if name == "platforms.get_capabilities":
        return {"platforms": platform_capabilities()}
    if name == "bots.list":
        rows = (
            await db.scalars(
                select(ShopBot)
                .where(
                    ShopBot.store_id == data["store_id"],
                    ShopBot.name.ilike("%" + data["q"] + "%"),
                )
                .order_by(ShopBot.name, ShopBot.id)
                .offset((data["page"] - 1) * 50)
                .limit(51)
            )
        ).all()
        return {
            "items": [
                {
                    "id": row.id,
                    "name": row.name,
                    "platform": row.platform,
                    "status": row.status,
                }
                for row in rows[:50]
            ],
            "page": data["page"],
            "has_more": len(rows) > 50,
        }
    if name == "actions.list":
        return await actions.catalog_view(db, **common, **values)
    if name == "actions.get":
        return await actions.detail_view(db, **common, **values)
    if name == "workflow.list":
        return await workflows.list_workflows(db, **common, **values)
    if name == "workflow.get":
        return await workflows.read_workflow(db, **common, **values)
    if name == "workflow.list_revisions":
        return await workflows.list_revisions(db, **common, **values)
    if name == "workflow.compare_revisions":
        return await workflows.compare_revisions(db, **common, **values)
    if name == "workflow.validate":
        return await workflows.validate_workflow(db, **common, **values)
    if name == "workflow.simulate":
        identity = values.pop("workflow_id")
        return await workflows.simulate_workflow(
            db,
            **common,
            workflow_id=identity,
            payload=values,
        ) | {"simulation": True}
    if name == "changes.get":
        return await changes.get(
            db,
            principal,
            data["change_set_id"],
            data["version"],
        )
    if name in {
        "workflow.validate_change_set",
        "workflow.simulate_change_set",
    }:
        row = await changes.owned(db, principal, data["change_set_id"])
        _, proposal = await changes.revision(db, row)
        definition = Definition.model_validate(proposal["definition"])
        await validate_bindings(
            db, store_id=row.store_id, definition=definition
        )
        if name == "workflow.validate_change_set":
            return await actions.workflow_report(
                db,
                **common,
                store_id=row.store_id,
                definition=definition,
            )
        return await _simulate_proposal(db, principal, definition, data)
    if name == "operations.get_status":
        return await journal.status(db, principal, data["operation_id"])
    if name in {
        "workflow.get_operation_status",
        "runtime.get_operation_status",
    }:
        from services.shop_mcp.execution import receipt

        return await receipt(db, principal, operation_id=data["operation_id"])
    if name in {
        "catalog.list_categories",
        "catalog.search_products",
        "catalog.get_product",
        "catalog.get_price_uom",
    }:
        from services.shop_mcp.inspection import catalog

        return await catalog(db, principal, name, data)
    if name in {
        "runtime.list_runs",
        "runtime.get_run",
        "runtime.diagnose_failure",
    }:
        from services.shop_mcp.inspection import runtime

        return await runtime(db, principal, name, data)
    raise McpRejected("mcp_tool_not_found", 404)


async def _simulate_proposal(db, principal, definition, data):
    """Use the pure Simulator with only synthetic context and an owned Bot."""
    from services.shop_workflow_simulator import simulate

    bot = await db.scalar(
        select(ShopBot).where(
            ShopBot.id == data["bot_id"],
            ShopBot.store_id == data["store_id"],
            ShopBot.platform == data["platform"],
            ShopBot.status != "disabled",
        )
    )
    if (
        bot is None
        or data["platform"] not in definition.target_platforms
        or definition.assignment.mode == "selected"
        and bot.id not in definition.assignment.bot_ids
    ):
        raise McpRejected("workflow_bot_not_available", 422)
    return simulate(
        definition,
        platform=data["platform"],
        context=data["context"]
        | {
            "store_name": principal.scope.current_store.name,
            "bot_name": bot.name,
        },
        events=data["events"],
    ) | {"simulation": True, "bot_id": bot.id, "platform": bot.platform}
