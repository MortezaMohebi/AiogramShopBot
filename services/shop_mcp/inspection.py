"""Read-only operational and public catalog projections for the designer."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from channels.contracts import Platform
from models.shop_multibot import ShopBot
from models.shop_workflow_runtime import WorkflowRun
from services.shop_actions import adapters, schemas
from services.shop_actions.contracts import ActionRejected
from services.shop_actions.definitions import definition
from services.shop_bot_context import BotContext, resolve_bot_context
from services.shop_mcp.contracts import McpRejected
from services.shop_runtime import admin
from services.shop_runtime.contracts import RuntimeRejected


@dataclass(frozen=True, slots=True)
class CatalogReader:
    """Native public catalog context without a customer session."""

    store_id: str
    bot_id: str
    bot: BotContext


async def catalog(db, principal, name, data):
    """Map only four reviewed reads to their existing typed business adapters.

    This does not forge an Action's human session or a customer principal, and
    cannot select an arbitrary adapter or enter an Action execution path.
    """
    record = await db.scalar(
        select(ShopBot).where(
            ShopBot.id == data["bot_id"],
            ShopBot.store_id == principal.scope.current_store_id,
        )
    )
    if record is None:
        raise McpRejected("mcp_bot_not_available", 404)
    bot = await resolve_bot_context(
        db,
        authenticated_bot_id=record.id,
        authenticated_platform=Platform(record.platform),
    )
    reader = CatalogReader(record.store_id, record.id, bot)
    payload = {
        key: value
        for key, value in data.items()
        if key not in {"store_id", "bot_id"}
    }
    mappings = {
        "catalog.list_categories": (schemas.Page, adapters.list_categories),
        "catalog.search_products": (schemas.Search, adapters.search_products),
        "catalog.get_product": (schemas.ProductInput, adapters.get_product),
        "catalog.get_price_uom": (schemas.ProductInput, adapters.price_uom),
    }
    model, adapter = mappings[name]
    try:
        result = await adapter(db, reader, model.model_validate(payload))
        # Keep the established versioned public output contract authoritative.
        return (
            definition(name, "1.0.0")
            .output_model.model_validate(
                result,
            )
            .model_dump(mode="json")
        )
    except ActionRejected as error:
        raise McpRejected(error.code, 404) from None


async def runtime(db, principal, name, data):
    """Expose operational metadata without answers or transport data."""
    if name == "runtime.list_runs":
        query = select(WorkflowRun).where(
            WorkflowRun.store_id == principal.scope.current_store_id,
        )
        if data["workflow_id"] is not None:
            query = query.where(WorkflowRun.workflow_id == data["workflow_id"])
        rows = (
            await db.scalars(
                query.order_by(
                    WorkflowRun.updated_at.desc(),
                    WorkflowRun.id,
                )
                .offset((data["page"] - 1) * 50)
                .limit(51)
            )
        ).all()
        return {
            "items": [admin.safe_run(row) for row in rows[:50]],
            "page": data["page"],
            "has_more": len(rows) > 50,
        }
    try:
        result = await admin.run_detail(db, principal.scope, data["run_id"])
    except RuntimeRejected as error:
        raise McpRejected(error.code, error.status) from None
    # Summaries may evolve independently of this public MCP privacy contract.
    for event in result["events"]:
        event.pop("summary", None)
    for delivery in result["outbox"]:
        delivery.pop("message_ids", None)
    if name == "runtime.diagnose_failure":
        result["guidance"] = {
            "customer_values_available": False,
            "uncertain_delivery_policy": (
                "Never retry an unknown send outcome."
            ),
            "recovery": (
                "Prepare an exact recovery; require WPMCP human approval."
            ),
        }
    return result
