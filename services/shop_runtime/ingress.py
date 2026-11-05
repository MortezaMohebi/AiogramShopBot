"""Offer authenticated Telegram/Bale updates to Runtime before legacy claims."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select

import config
from channels.contracts import Platform
from db import session_maker
from models.shop_delivery import ShopInboundUpdate
from models.shop_content import ShopIdentity
from models.shop_multibot import LEGACY_BOT_IDS
from models.shop_workflow_runtime import WorkflowInbox
from services import shop_admin_security as security
from services.shop_bot_context import resolve_bot_context, resolve_legacy_bot_context
from services.shop_bot_operations import legacy_state
from services.shop_bot_profiles import get_bot_options
from services.shop_identity import is_blocked, register_customer
from services.shop_multibot_client import provider_client
from services.shop_bot_secrets import resolve_active_token
from services.shop_runtime import adapters, sessions


def _deployment_enabled() -> bool:
    """Keep all receiver hooks inert under their default deployment flags."""
    return bool(
        getattr(config, "SHOP_WORKFLOW_RUNTIME_ENABLED", False)
        and not getattr(config, "SHOP_WORKFLOW_RUNTIME_KILL_SWITCH", False)
    )


def _financial(payload) -> bool:
    """Leave provider financial updates reachable before every Runtime gate."""
    if not isinstance(payload, Mapping):
        return False
    message = payload.get("message")
    return "pre_checkout_query" in payload or (
        isinstance(message, Mapping) and "successful_payment" in message
    )


async def _existing_inbox(bot_id, payload) -> dict | None:
    """Keep previously accepted inputs owned by Runtime even after disabling it."""
    if not bot_id or not isinstance(payload, Mapping):
        return None
    update_id = payload.get("update_id")
    if type(update_id) is not int or not 0 <= update_id <= 9_223_372_036_854_775_807:
        return None
    async with session_maker() as db:
        state = await db.scalar(
            select(WorkflowInbox.status).where(
                WorkflowInbox.bot_id == bot_id,
                WorkflowInbox.input_id == str(update_id),
            )
        )
    if state is not None:
        return {"handled": True, "duplicate": True, "status": state}
    return None


async def _acknowledge(context, payload, *, client=None) -> None:
    """Clear callback loading state without allowing a failed ack to replay input."""
    query = payload.get("callback_query")
    if not isinstance(query, Mapping) or not isinstance(query.get("id"), str):
        return

    async def acknowledge(provider):
        """Use only the current platform's supported acknowledgement operation."""
        if context.platform == Platform.TELEGRAM:
            await provider.answer_callback_query(
                callback_query_id=query["id"], cache_time=0
            )
        else:
            await provider.acknowledge(query["id"])

    try:
        if client is not None:
            await acknowledge(client)
        else:
            async with session_maker() as db:
                token = await db.run_sync(
                    lambda sync: resolve_active_token(sync, bot_id=context.bot_id)
                )
            async with provider_client(
                context.platform.value, token, bot_id=context.bot_id
            ) as provider:
                await acknowledge(provider)
    except Exception:
        # Input is already durable. A provider ack is cosmetic and may safely
        # expire; do not send an error message or expose credential URLs.
        return


async def try_ingress(context, payload, client=None) -> dict:
    """Handle a Runtime-owned authenticated input or return legacy fallback.

    The receiver must invoke this before claiming its legacy provider receipt.
    The coordinator commits the Inbox before any upload download/transition;
    this layer never delivers customer prompts or business effects inline.
    """
    if _financial(payload):
        return {"handled": False}
    prior = await _existing_inbox(getattr(context, "bot_id", None), payload)
    if not _deployment_enabled():
        return prior or {"handled": False}
    if prior and prior["status"] != "pending":
        return prior
    event = adapters.normalize(context, payload)
    if event is None:
        return prior or {"handled": False}
    async with session_maker() as db:
        # Preserve at-most-once legacy quarantine across enabling Runtime.
        receipt = await db.scalar(
            select(ShopInboundUpdate.status).where(
                ShopInboundUpdate.bot_id == context.bot_id,
                ShopInboundUpdate.platform == event.platform,
                ShopInboundUpdate.update_id == int(event.update_id),
            )
        )
        if receipt is not None:
            return {"handled": True, "status": "duplicate", "receipt_state": receipt}
        try:
            current = await resolve_bot_context(
                db,
                authenticated_bot_id=context.bot_id,
                authenticated_platform=context.platform,
                authenticated_provider_bot_id=context.provider_bot_id,
            )
        except security.SecurityRejected:
            return prior or {"handled": False}
        if current.store_id != context.store_id or not await sessions.enabled(
            db, current
        ):
            return prior or {"handled": False}
        if current.runtime_owner == "legacy":
            state = await legacy_state(db, event.platform)
            options = await get_bot_options(db, event.platform)
            if state.state != "active" or options.maintenance_enabled:
                return prior or {"handled": False}
        if await is_blocked(
            db,
            bot_id=current.bot_id,
            platform=current.platform,
            platform_user_id=event.user_id,
        ):
            # Legacy paid-order refunds remain reachable for restricted
            # customers; their exact ownership is checked by the old flow.
            if event.kind == "callback" and not event.callback.startswith(
                ("wf:", "wfe:")
            ):
                return prior or {"handled": False}
            return {"handled": True, "status": "blocked"}
        source = payload.get("callback_query") or payload.get("message")
        sender = source.get("from", {}) if isinstance(source, Mapping) else {}
        was_existing = (
            await db.scalar(
                select(ShopIdentity.id).where(
                    ShopIdentity.bot_id == current.bot_id,
                    ShopIdentity.platform_user_id == event.user_id,
                    ShopIdentity.customer_id.is_not(None),
                )
            )
            is not None
        )
        await register_customer(
            db,
            bot_id=current.bot_id,
            platform=current.platform,
            platform_user_id=event.user_id,
            username=sender.get("username")[:255]
            if isinstance(sender.get("username"), str)
            else None,
            first_name=sender.get("first_name")[:255]
            if isinstance(sender.get("first_name"), str)
            else None,
        )

        async def verify(db, verified_context, verified_event, principal):
            """Defer scoped byte verification until the Inbox commit is durable."""
            return await adapters.verify_upload(
                db, verified_context, verified_event, principal, client=client
            )

        result = await sessions.handle(
            db,
            context=current,
            event=event,
            file_verifier=verify,
            was_existing=was_existing,
        )
    if result.get("handled") and event.kind == "callback":
        await _acknowledge(current, payload, client=client)
    return result


async def try_legacy_ingress(platform, payload, client=None) -> dict:
    """Bridge an authenticated original receiver after its current Bot gate.

    This helper is shared by webhooks, polling and the outer Aiogram middleware
    so direct message/photo/document input gets the same durable Inbox chance.
    """
    if _financial(payload):
        return {"handled": False}
    try:
        platform = Platform(platform)
    except ValueError:
        return {"handled": False}
    prior = await _existing_inbox(LEGACY_BOT_IDS[platform.value], payload)
    if not _deployment_enabled():
        return prior or {"handled": False}
    if prior and prior["status"] != "pending":
        return prior
    async with session_maker() as db:
        state = await legacy_state(db, platform.value)
        options = await get_bot_options(db, platform.value)
        if state.state != "active" or options.maintenance_enabled:
            return prior or {"handled": False}
        try:
            context = await resolve_legacy_bot_context(
                db, authenticated_platform=platform
            )
        except security.SecurityRejected:
            return prior or {"handled": False}
    return await try_ingress(context, payload, client=client)
