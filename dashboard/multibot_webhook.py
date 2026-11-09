"""Token-redacted public webhook routes for many authenticated bots.

The path contains a random 256-bit secret, not a Bot API token. Telegram
additionally authenticates its official secret-token header. The signed
admin session is intentionally irrelevant to external provider webhooks.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, Response

from db import session_maker
from services import shop_admin_security as security
from services.shop_bot_secrets import webhook_probe_signature
from services.shop_multibot_webhook import (
    PROBE_HEADER, PROOF_HEADER, TELEGRAM_SECRET_HEADER, authenticate_webhook, probe_nonce,
)

router = APIRouter(tags=["Multi-bot provider webhook"])


@router.post("/webhooks/v2/{binding_id}/{route_secret}", response_model=None)
async def receive_multibot_webhook(
    binding_id: str, route_secret: str, request: Request,
) -> dict | Response:
    """Claim a provider update in one bot-specific receipt before any send."""
    telegram_header = request.headers.get(TELEGRAM_SECRET_HEADER)
    challenge = request.headers.get(PROBE_HEADER)
    if challenge is not None:
        try:
            nonce = probe_nonce(binding_id, challenge)
            async with session_maker() as db:
                await authenticate_webhook(
                    db, binding_id=binding_id, secret=route_secret,
                    telegram_header=telegram_header, probe=True,
                )
        except security.SecurityRejected:
            raise HTTPException(status_code=404, detail="Not found") from None
        return Response(status_code=204, headers={
            PROOF_HEADER: webhook_probe_signature(binding_id, nonce, response=True),
            "Cache-Control": "no-store",
        })
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
            telegram_header=telegram_header,
            payload=payload,
        )
    except security.SecurityRejected as error:
        raise HTTPException(
            status_code=error.status, detail=error.code,
        ) from None
