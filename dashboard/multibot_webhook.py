"""Token-redacted public webhook routes for many authenticated bots.

The path contains a random 256-bit secret, not a Bot API token. Telegram
additionally authenticates its official secret-token header. The signed
admin session is intentionally irrelevant to external provider webhooks.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from services import shop_admin_security as security

router = APIRouter(tags=["Multi-bot provider webhook"])


@router.post("/webhooks/v2/{binding_id}/{route_secret}")
async def receive_multibot_webhook(
    binding_id: str, route_secret: str, request: Request,
) -> dict:
    """Claim a provider update in one bot-specific receipt before any send."""
    supervisor = getattr(
        request.app.state, "multi_bot_supervisor", None,
    )
    if supervisor is None or not supervisor.owns_lease:
        raise HTTPException(status_code=503, detail="Receiver unavailable")
    declared = request.headers.get("content-length")
    if declared is not None and (
        not declared.isdecimal() or int(declared) > 256_000
    ):
        raise HTTPException(status_code=413, detail="Payload too large")
    body = await request.body()
    if len(body) > 256_000:
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid update")
    try:
        return await supervisor.dispatch_webhook(
            binding_id=binding_id,
            secret=route_secret,
            telegram_header=request.headers.get(
                "X-Telegram-Bot-Api-Secret-Token"
            ),
            payload=payload,
        )
    except security.SecurityRejected as error:
        raise HTTPException(
            status_code=error.status, detail=error.code,
        ) from None
