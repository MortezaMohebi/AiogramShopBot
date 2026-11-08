"""Trusted Store/Bot/media binding checks, independent of Worker deployment."""

from __future__ import annotations

from sqlalchemy import select

from models.shop_content import Product, ProductMedia
from models.shop_multibot import ShopBot
from services import shop_admin_security as security
from services.shop_platform_capabilities import CAPABILITIES
from services.shop_workflow_schema import Definition


def authorize(actor, scope, *, write=False, store_id=None):
    """Require a matching authenticated actor, live role and explicit Store grant."""
    if (
        actor is None
        or scope is None
        or actor.id != scope.staff_id
        or not actor.is_active
    ):
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(
        actor.role, "workflows.write" if write else "workflows.read"
    )
    scope.require(store_id or scope.current_store_id, write=write)


async def validate_bindings(db, *, store_id: str, definition: Definition):
    """Reject foreign/disabled Bot identities and every nested private media reference."""
    assignment = definition.assignment
    if assignment.mode == "selected":
        rows = (
            (
                await db.execute(
                    select(ShopBot.id).where(
                        ShopBot.store_id == store_id,
                        ShopBot.id.in_(assignment.bot_ids),
                        ShopBot.status != "disabled",
                        ShopBot.platform.in_(definition.target_platforms),
                    )
                )
            )
            .scalars()
            .all()
        )
        if set(rows) != set(assignment.bot_ids) or not rows:
            raise security.SecurityRejected("workflow_bot_not_available", 422)
    references = []
    for node in definition.nodes:
        for platform in definition.target_platforms:
            config = node.config | node.platform_overrides.get(platform, {})
            if config.get("media_id") is not None:
                references.append(
                    (
                        config["media_id"],
                        node.type.removeprefix("send_"),
                        platform,
                    )
                )
            for media_id in config.get("media_ids", []):
                references.append((media_id, "group", platform))
    if not references:
        return
    ids = {item[0] for item in references}
    media = (
        (
            await db.execute(
                select(ProductMedia)
                .join(
                    Product,
                    Product.id == ProductMedia.product_id,
                )
                .where(Product.store_id == store_id, ProductMedia.id.in_(ids))
            )
        )
        .scalars()
        .all()
    )
    indexed = {row.id: row for row in media}
    if set(indexed) != ids:
        raise security.SecurityRejected("workflow_media_not_available", 422)
    for media_id, kind, platform in references:
        row = indexed[media_id]
        limit = CAPABILITIES[platform][
            "photo_bytes" if row.kind == "photo" else "file_bytes"
        ]
        if (kind != "group" and row.kind != kind) or row.size_bytes > limit:
            raise security.SecurityRejected(
                "workflow_media_not_available", 422
            )


async def bot_choices(
    db, *, scope, actor, store_id=None, page=1, q=""
) -> dict:
    """Page the owning Store's eligible Bots without exposing credentials or topology."""
    owner = store_id or scope.current_store_id
    authorize(actor, scope, store_id=owner)
    query = select(ShopBot).where(
        ShopBot.store_id == owner, ShopBot.status != "disabled"
    )
    if q:
        query = query.where(ShopBot.name.ilike("%" + q + "%"))
    rows = (
        (
            await db.execute(
                query.order_by(ShopBot.name, ShopBot.id)
                .offset((page - 1) * 100)
                .limit(101)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "name": row.name,
                "platform": row.platform,
                "status": row.status,
            }
            for row in rows[:100]
        ],
        "has_more": len(rows) > 100,
        "page": page,
    }


async def media_choices(
    db, *, scope, actor, store_id=None, page=1, kind=None, q=""
) -> dict:
    """Return existing same-Store media identities; no private paths, tokens or URLs."""
    owner = store_id or scope.current_store_id
    authorize(actor, scope, store_id=owner)
    query = (
        select(ProductMedia, Product.name)
        .join(Product, Product.id == ProductMedia.product_id)
        .where(Product.store_id == owner)
    )
    if kind:
        query = query.where(ProductMedia.kind == kind)
    if q:
        query = query.where(
            ProductMedia.original_filename.ilike("%" + q + "%")
        )
    rows = (
        await db.execute(
            query.order_by(ProductMedia.id.desc())
            .offset((page - 1) * 100)
            .limit(101)
        )
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "name": row.original_filename,
                "kind": row.kind,
                "size_bytes": row.size_bytes,
                "product_name": name,
            }
            for row, name in rows[:100]
        ],
        "has_more": len(rows) > 100,
        "page": page,
    }
