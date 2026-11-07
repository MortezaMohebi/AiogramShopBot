"""Validate the deployment allowlist for registered Telegram relay origins."""

from __future__ import annotations

import os
import re
from ipaddress import ip_address
from urllib.parse import urlsplit

from services import shop_admin_security as security
from utils.telegram_worker import validate_worker_origin

_HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,251}[a-z0-9]$")


def _public_host(host: str) -> bool:
    """Reject local resolver names and non-global IP addresses."""
    if (
        not host or len(host) > 253
        or host in {"localhost", "localhost.localdomain"}
        or host.endswith((".local", ".internal", ".localhost", ".test"))
    ):
        return False
    try:
        return ip_address(host).is_global
    except ValueError:
        return bool(_HOST_RE.fullmatch(host) and "." in host and ".." not in host)



def _worker_origin(value: str) -> str:
    """Reject credentials, private IPs and URL suffixes for relay destinations."""
    try:
        origin = validate_worker_origin(value)
        host = urlsplit(origin).hostname
    except ValueError:
        raise security.SecurityRejected("invalid_worker_origin", 422) from None
    if not host or not _public_host(host):
        raise security.SecurityRejected("invalid_worker_origin", 422)
    return origin



def approved_worker_origins() -> tuple[str, ...]:
    """Allow only previously authorized relay origins with private credentials."""
    approved: set[str] = set()
    declared = os.environ.get("TELEGRAM_WORKER_ALLOWED_ORIGINS", "")
    entries = [item.strip() for item in declared.split(",") if item.strip()]
    for endpoint in entries:
        try:
            approved.add(_worker_origin(endpoint))
        except security.SecurityRejected:
            continue
    return tuple(sorted(approved))
