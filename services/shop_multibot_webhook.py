"""Strict multi-bot webhook origin and path construction.

No URL from an incoming request is used to identify a bot, a receiver, or an
upstream API. Only deployment-approved TLS origins can own a bot endpoint.
"""

from __future__ import annotations

import os
import re
from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from services import shop_admin_security as security


_SECRET = re.compile(r"^[A-Za-z0-9_-]{43}$")


def webhook_url(binding_id: str, secret: str) -> str:
    """Build one opaque route using a verified HTTPS deployment origin."""
    declared = os.environ.get("MULTIBOT_WEBHOOK_BASE_URL", "").strip()
    if not declared:
        return ""
    try:
        origin = urlsplit(declared)
        host = origin.hostname
        port = origin.port
        binding = str(UUID(binding_id))
    except (ValueError, TypeError):
        raise security.SecurityRejected("webhook_url_invalid", 422) from None
    if (
        origin.scheme != "https"
        or not host or origin.username is not None
        or origin.password is not None or origin.query or origin.fragment
        or origin.path not in ("", "/")
        or port not in (None, 443)
        or not _SECRET.fullmatch(secret)
        or host == "localhost" or host.endswith(
            (".local", ".internal", ".localhost", ".test")
        )
    ):
        raise security.SecurityRejected("webhook_url_invalid", 422)
    try:
        if not ip_address(host).is_global:
            raise security.SecurityRejected("webhook_url_invalid", 422)
    except ValueError:
        # DNS resolvability is checked during provider webhook verification.
        if "." not in host or ".." in host:
            raise security.SecurityRejected("webhook_url_invalid", 422)
    return urlunsplit((
        "https", host.lower(),
        f"/webhooks/v2/{binding}/{secret}", "", "",
    ))
