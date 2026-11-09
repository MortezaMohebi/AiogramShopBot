"""Strict multi-bot webhook origin and path construction.

No URL from an incoming request is used to identify a bot, a receiver, or an
upstream API. Only deployment-approved TLS origins can own a bot endpoint.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import secrets
import socket
from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_multibot import ShopBot
from models.shop_multibot_receiver import ShopBotReceiver
from services import shop_admin_security as security
from services.shop_bot_secrets import webhook_probe_signature


_SECRET = re.compile(r"^[A-Za-z0-9_-]{43}$")
_PROBE = re.compile(r"([a-f0-9]{32})\.([a-f0-9]{64})")
PROBE_HEADER = "X-Shop-Webhook-Probe"
PROOF_HEADER = "X-Shop-Webhook-Proof"
TELEGRAM_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _path(binding_id: str, secret: str) -> str:
    """Build the same provider-independent route for local and public ingress."""
    try:
        binding = str(UUID(binding_id))
    except (ValueError, TypeError, AttributeError):
        raise security.SecurityRejected("webhook_url_invalid", 422) from None
    if not isinstance(secret, str) or not _SECRET.fullmatch(secret):
        raise security.SecurityRejected("webhook_url_invalid", 422)
    return f"/webhooks/v2/{binding}/{secret}"


def local_webhook_url(binding_id: str, secret: str) -> str:
    """Use the backend's loopback listener, independent of the public tunnel."""
    return "http://127.0.0.1:5000" + _path(binding_id, secret)


def webhook_url(binding_id: str, secret: str) -> str:
    """Build one opaque route using a verified HTTPS deployment origin."""
    origin_key = "MULTIBOT_WEBHOOK_BASE_URL"
    if binding_id and binding_id == os.environ.get("MULTIBOT_WEBHOOK_BINDING_ID"):
        origin_key = "MULTIBOT_WEBHOOK_BINDING_BASE_URL"
    declared = os.environ.get(origin_key, "").strip()
    if not declared:
        return ""
    try:
        origin = urlsplit(declared)
        host = origin.hostname
        port = origin.port
    except (ValueError, TypeError):
        raise security.SecurityRejected("webhook_url_invalid", 422) from None
    if (
        origin.scheme != "https"
        or not host or origin.username is not None
        or origin.password is not None or origin.query or origin.fragment
        or origin.path not in ("", "/")
        or port not in (None, 443)
        or host == "localhost" or host.endswith(
            (".local", ".internal", ".localhost", ".test")
        )
    ):
        raise security.SecurityRejected("webhook_url_invalid", 422)
    try:
        address = ip_address(host)
    except ValueError:
        # DNS resolvability is checked during provider webhook verification.
        if "." not in host or ".." in host:
            raise security.SecurityRejected("webhook_url_invalid", 422)
    else:
        # SecurityRejected is a ValueError; never catch our own refusal as
        # though a private address had merely failed DNS-name parsing.
        if not address.is_global:
            raise security.SecurityRejected("webhook_url_invalid", 422)
    authority = f"[{host}]" if ":" in host else host.lower()
    return urlunsplit(("https", authority, _path(binding_id, secret), "", ""))


async def authenticate_webhook(
    db: AsyncSession, *, binding_id: str, secret: str,
    telegram_header: str | None, probe: bool = False,
) -> str:
    """Check the exact binding, path secret and provider header."""
    try:
        binding = str(UUID(binding_id))
    except (ValueError, TypeError, AttributeError):
        raise security.SecurityRejected("not_found", 404) from None
    if not isinstance(secret, str) or not _SECRET.fullmatch(secret):
        raise security.SecurityRejected("not_found", 404)
    states = ("staged",) if probe else ("active",)
    row = await db.scalar(select(ShopBotReceiver).where(
        ShopBotReceiver.binding_id == binding,
        ShopBotReceiver.mode == "webhook",
        ShopBotReceiver.state.in_(states),
    ))
    digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
    if row is None or not hmac.compare_digest(digest, row.webhook_secret_digest):
        raise security.SecurityRejected("not_found", 404)
    bot = await db.get(ShopBot, row.bot_id)
    if bot is None or (
        bot.platform == "telegram" and (
            telegram_header is None or not telegram_header.isascii()
            or not hmac.compare_digest(telegram_header, secret)
        )
    ):
        raise security.SecurityRejected("not_found", 404)
    return row.bot_id


def probe_nonce(binding_id: str, header: str) -> str:
    """Accept a readiness request only when signed by the deployment."""
    match = _PROBE.fullmatch(header)
    if (
        match is None or not binding_id.isascii()
        or not hmac.compare_digest(match[2], webhook_probe_signature(binding_id, match[1]))
    ):
        raise security.SecurityRejected("not_found", 404)
    return match[1]


class _PublicResolver(AbstractResolver):
    """Restrict the public test's actual connection to globally routable DNS answers."""

    def __init__(self) -> None:
        self._resolver = DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        addresses = await self._resolver.resolve(host, port, family)
        public = [entry for entry in addresses if ip_address(entry["host"]).is_global]
        if not public:
            raise OSError("Webhook hostname has no public address")
        return public

    async def close(self) -> None:
        await self._resolver.close()


async def probe_webhook(url: str, binding_id: str, secret: str, *, public: bool) -> None:
    """Verify an HTTP round trip to our staged route without dispatching an update."""
    nonce = secrets.token_hex(16)
    headers = {
        PROBE_HEADER: f"{nonce}.{webhook_probe_signature(binding_id, nonce)}",
        TELEGRAM_SECRET_HEADER: secret,
    }
    expected = webhook_probe_signature(binding_id, nonce, response=True)
    code = "webhook_public_unreachable" if public else "webhook_local_unreachable"
    resolver = _PublicResolver() if public else None
    try:
        async with ClientSession(
            timeout=ClientTimeout(total=6), connector=TCPConnector(resolver=resolver),
        ) as client:
            async with client.post(url, headers=headers, allow_redirects=False) as reply:
                proof = reply.headers.get(PROOF_HEADER, "")
                if reply.status == 204 and proof.isascii() and hmac.compare_digest(proof, expected):
                    return
    except (ClientError, asyncio.TimeoutError, OSError, ValueError):
        pass
    finally:
        if resolver is not None:
            await resolver.close()
    raise security.SecurityRejected(code, 503)
