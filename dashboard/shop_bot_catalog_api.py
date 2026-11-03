"""Audited bot/product Many2many ACL management and read-only previews.

All writes are superadmin-only, session-bound and require recent proof in the
ASGI boundary. Product and category records remain managed by the existing
editor; this module only grants/denies visibility to specific bot identities.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.next_api import database, signed_staff
from models.shop_bot_catalog_acl import (
    ShopBotCatalogAudit, ShopBotProductRule,
)
from models.shop_content import Product
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_bot_catalog_acl as catalog_acl

router = APIRouter(prefix="/internal/admin/v1", tags=["Bot catalog ACL"])
Db = Annotated[AsyncSession, Depends(database)]
Staff = Annotated[ShopStaff | None, Depends(signed_staff)]


def require(staff: ShopStaff | None, permission: str) -> ShopStaff:
    """Allow only roles with explicit authority over bot catalog policy."""
    if staff is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(staff.role, permission)
    return staff


class StrictPayload(BaseModel):
    """Disallow unknown keys that might broaden rule changes."""

    model_config = ConfigDict(extra="forbid")


class BotRulesChange(StrictPayload):
    """Change up to 100 product/category Many2many rules in one transaction."""

    expected_version: int = Field(ge=1)
    kind: Literal["product", "category"]
    target_ids: list[int] = Field(min_length=1, max_length=100)
    effect: Literal["allow", "deny", "inherit"]


class ProductBotAssignment(StrictPayload):
    """One version-checked bot/product entitlement change."""

    bot_id: UUID
    effect: Literal["allow", "deny", "inherit"]
    expected_version: int = Field(ge=1)


class ProductRulesChange(StrictPayload):
    """Atomic Many2many edit from one product's admin form."""

    assignments: list[ProductBotAssignment] = Field(
        min_length=1, max_length=100,
    )


def _page(page: int, page_size: int) -> tuple[int, int]:
    """Bound page size and offset to protect the shared database."""
    if not 1 <= page <= 100_000 or not 1 <= page_size <= 100:
        raise security.SecurityRejected("invalid_request", 422)
    return (page - 1) * page_size, page_size


@router.get("/bot-catalog/bots/{bot_id}")
async def bot_catalog_policy(
    bot_id: UUID, staff: Staff, db: Db,
    kind: Literal["product", "category"] = "product",
    q: str = "", page: int = 1, page_size: int = 20,
) -> dict:
    """List searchable, paginated grant candidates with effective access."""
    require(staff, "bots.read")
    offset, limit = _page(page, page_size)
    if len(q) > 100:
        raise security.SecurityRejected("invalid_request", 422)
    bot = await db.get(ShopBot, str(bot_id))
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    if bot.store_id != DEFAULT_STORE_ID:
        return {
            "bot_id": bot.id, "kind": kind, "default_effect": "deny",
            "policy_ready": False, "items": [], "total": 0,
            "page": page, "page_size": page_size,
        }
    model, target_model, id_key = catalog_acl.RULE_OBJECTS[kind]
    base = select(target_model)
    count_stmt = select(func.count()).select_from(target_model)
    if q.strip():
        needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        criterion = target_model.name.ilike(f"%{needle}%", escape="\\")
        base = base.where(criterion)
        count_stmt = count_stmt.where(criterion)
    total = int(await db.scalar(count_stmt) or 0)
    records = (await db.scalars(
        base.order_by(target_model.id.desc()).offset(offset).limit(limit)
    )).all()
    ids = [row.id for row in records]
    explicit = {}
    if ids:
        rules = (await db.scalars(select(model).where(
            model.bot_id == bot.id,
            getattr(model, id_key).in_(ids),
        ))).all()
        explicit = {getattr(row, id_key): row.effect for row in rules}

    preview_scope = await catalog_acl.resolve_scope(
        db, bot_id=bot.id, preview=True,
    )
    permitted: set[int] = set()
    if kind == "product" and ids:
        permitted = await catalog_acl.visible_product_ids(
            db, preview_scope, ids,
        )

    return {
        "bot_id": bot.id,
        "kind": kind,
        "default_effect": (
            "allow" if preview_scope.default_allow else "deny"
        ),
        "policy_ready": preview_scope.available,
        "items": [{
            "id": row.id, "name": row.name,
            "is_published": row.is_published,
            "category_id": row.category_id if kind == "product" else None,
            "effect": explicit.get(row.id, "inherit"),
            "effective_access": (
                row.id in permitted if kind == "product" else None
            ),
        } for row in records],
        "total": total, "page": page, "page_size": page_size,
    }


@router.post("/bot-catalog/bots/{bot_id}/rules")
async def change_bot_rules(
    bot_id: UUID, payload: BotRulesChange, staff: Staff, db: Db,
) -> dict:
    """Apply allow/deny/inherit in one atomic row-locked operation."""
    actor = require(staff, "bots.configure")
    changed = await db.run_sync(lambda sync: catalog_acl.update_bot_rules(
        sync, bot_id=str(bot_id), actor_id=actor.id,
        expected_version=payload.expected_version,
        object_type=payload.kind, target_ids=payload.target_ids,
        effect=payload.effect,
    ))
    await db.commit()
    return {"ok": True, "changed": changed}


@router.get("/bot-catalog/products/{product_id}")
async def product_bot_policy(
    product_id: int, staff: Staff, db: Db,
    q: str = "", page: int = 1, page_size: int = 30,
) -> dict:
    """Expose product grants as a searchable Many2many admin selection."""
    require(staff, "bots.read")
    offset, limit = _page(page, page_size)
    if len(q) > 100 or product_id <= 0:
        raise security.SecurityRejected("invalid_request", 422)
    product = await db.get(Product, product_id)
    if product is None:
        raise security.SecurityRejected("catalog_target_not_found", 404)
    bots_stmt = select(ShopBot).where(ShopBot.store_id == DEFAULT_STORE_ID)
    count_stmt = select(func.count()).select_from(ShopBot).where(
        ShopBot.store_id == DEFAULT_STORE_ID,
    )
    if q.strip():
        needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        criterion = ShopBot.name.ilike(f"%{needle}%", escape="\\")
        bots_stmt = bots_stmt.where(criterion)
        count_stmt = count_stmt.where(criterion)
    total = int(await db.scalar(count_stmt) or 0)
    bots = (await db.scalars(bots_stmt.order_by(
        ShopBot.name, ShopBot.id,
    ).offset(offset).limit(limit))).all()
    ids = [bot.id for bot in bots]
    records = (await db.scalars(select(ShopBotProductRule).where(
        ShopBotProductRule.product_id == product_id,
        ShopBotProductRule.bot_id.in_(ids),
    ))).all() if ids else []
    existing = {row.bot_id: row.effect for row in records}
    return {
        "product_id": product.id,
        "bots": [{
            "id": bot.id,
            "name": bot.name,
            "platform": bot.platform,
            "status": bot.status,
            "version": bot.version,
            "effect": existing.get(bot.id, "inherit"),
            "default_effect": (
                "allow" if bot.runtime_owner == "legacy" else "deny"
            ),
        } for bot in bots],
        "total": total, "page": page, "page_size": page_size,
    }


@router.post("/bot-catalog/products/{product_id}/rules")
async def change_product_bot_rules(
    product_id: int, payload: ProductRulesChange,
    staff: Staff, db: Db,
) -> dict:
    """Save M2M product entitlements for selected bots without touching others."""
    actor = require(staff, "bots.configure")
    changed = await db.run_sync(
        lambda sync: catalog_acl.update_product_bot_rules(
            sync, product_id=product_id, actor_id=actor.id,
            assignments=[
                (str(item.bot_id), item.effect, item.expected_version)
                for item in payload.assignments
            ],
        )
    )
    await db.commit()
    return {"ok": True, "changed": changed}


@router.get("/bot-catalog/bots/{bot_id}/audit")
async def bot_catalog_audit(
    bot_id: UUID, staff: Staff, db: Db, page: int = 1,
) -> dict:
    """Expose bounded immutable rule change history to authorized staff."""
    require(staff, "bots.read")
    offset, limit = _page(page, 30)
    rows = (await db.scalars(select(ShopBotCatalogAudit).where(
        ShopBotCatalogAudit.bot_id == str(bot_id),
    ).order_by(
        ShopBotCatalogAudit.created_at.desc(),
        ShopBotCatalogAudit.id.desc(),
    ).offset(offset).limit(limit))).all()
    return {"items": [{
        "object_type": item.object_type, "object_id": item.object_id,
        "old_effect": item.old_effect, "new_effect": item.new_effect,
        "actor_id": item.actor_id, "created_at": (
            item.created_at.isoformat() if item.created_at else None
        ),
    } for item in rows]}
