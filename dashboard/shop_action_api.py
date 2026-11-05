"""Safe signed Action inspection endpoints; no live execution or proof issuance."""

from typing import Annotated, Literal
from uuid import UUID

import config
from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, model_validator
from redis.asyncio import Redis

from dashboard.shop_customer_experience_api import Actor, Db, require
from dashboard.shop_workflow_api import payload, respond
from services import shop_action_catalog as catalog
from services import shop_admin_security as security
from services.shop_action_rate import rate_gate
from services.shop_actions.contracts import StrictModel, bounded_json

router = APIRouter(prefix="/internal/admin/v1/actions", tags=["Action Catalog"])


class DryRun(StrictModel):
    """No authoritative actor, customer, Store or approval claims can be supplied."""

    action_key: str = Field(max_length=81)
    action_version: str = Field(default="1.0.0", max_length=32)
    bot_id: str = Field(min_length=36, max_length=36)
    platform: Literal["telegram", "bale"]
    input: dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def limit_input(cls, value):
        """Bound nested request work before normal schema validation."""
        bounded_json(value)
        return value


async def rate_client():
    """Use the existing private Redis instance; never accept a caller-chosen URL."""
    async with Redis(
        host=config.REDIS_HOST,
        password=config.REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=3,
    ) as redis:
        yield redis


Rate = Annotated[Redis, Depends(rate_client)]


def query_keys(request, allowed):
    """Reject extra/duplicate query fields rather than accepting hidden authority."""
    if any(
        key not in allowed or len(request.query_params.getlist(key)) != 1
        for key in request.query_params
    ):
        raise security.SecurityRejected("action_invalid_request", 422)


@router.get("")
async def listing(
    request: Request,
    actor: Actor,
    db: Db,
    redis: Rate,
    q: str = Query("", max_length=100),
    category: str = Query("", max_length=32),
    side_effect: str = Query("", max_length=24),
    deprecated: Literal["all", "true", "false"] = "all",
    page: int = Query(1, ge=1, le=10001),
    page_size: int = Query(50, ge=1, le=100),
    store_id: UUID | None = None,
    bot_id: UUID | None = None,
    platform: Literal["telegram", "bale"] | None = None,
):
    """List typed policies and actual contextual availability under Store scope."""
    staff, scope = require(actor, request, "workflows.read")
    query_keys(
        request,
        {
            "q",
            "category",
            "side_effect",
            "deprecated",
            "page",
            "page_size",
            "store_id",
            "bot_id",
            "platform",
        },
    )
    await rate_gate(redis, scope)
    return respond(
        await catalog.catalog_view(
            db,
            scope=scope,
            actor=staff,
            q=q,
            category=category,
            side_effect=side_effect,
            deprecated=deprecated,
            page=page,
            page_size=page_size,
            store_id=str(store_id) if store_id else None,
            bot_id=str(bot_id) if bot_id else None,
            platform=platform,
        )
    )


@router.get("/bots")
async def bots(
    request: Request,
    actor: Actor,
    db: Db,
    redis: Rate,
    page: int = Query(1, ge=1, le=10001),
    q: str = Query("", max_length=100),
):
    """Expose owned diagnostic Bot choices without credentials or provider topology."""
    staff, scope = require(actor, request, "workflows.read")
    query_keys(request, {"page", "q"})
    await rate_gate(redis, scope)
    return respond(
        await catalog.bot_choices(db, scope=scope, actor=staff, page=page, q=q)
    )


@router.post("/dry-run")
async def dry_run(request: Request, actor: Actor, db: Db, redis: Rate):
    """Perform an authorized no-effect Catalog read with a rate-limited real context."""
    staff, scope = require(actor, request, "workflows.read")
    query_keys(request, set())
    await rate_gate(redis, scope, dry_run=True)
    data = await payload(request, DryRun)
    return respond(await catalog.dry_run(db, scope=scope, actor=staff, payload=data))


@router.get("/receipts/{invocation_id}")
async def receipt(
    invocation_id: UUID, request: Request, actor: Actor, db: Db, redis: Rate
):
    """Read redacted execution evidence only through the current Store's audit grant."""
    staff, scope = require(actor, request, "workflows.read")
    query_keys(request, set())
    await rate_gate(redis, scope)
    return respond(
        await catalog.receipt_view(
            db, scope=scope, actor=staff, invocation_id=str(invocation_id)
        )
    )


@router.get("/{key}/{version}")
async def detail(
    key: str,
    version: str,
    request: Request,
    actor: Actor,
    db: Db,
    redis: Rate,
    bot_id: UUID | None = None,
    platform: Literal["telegram", "bale"] | None = None,
):
    """Read one exact descriptor; unknown names never resolve to a service method."""
    staff, scope = require(actor, request, "workflows.read")
    query_keys(request, {"bot_id", "platform"})
    await rate_gate(redis, scope)
    return respond(
        await catalog.detail_view(
            db,
            scope=scope,
            actor=staff,
            key=key,
            version=version,
            bot_id=str(bot_id) if bot_id else None,
            platform=platform,
        )
    )
