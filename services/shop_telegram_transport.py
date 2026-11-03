"""Validated and encrypted Telegram outbound transport configurations.

Outbound transport is separate from inbound Webhook/getUpdates. Only
deployment-allowlisted proxy endpoints and Worker origins may receive the
Telegram Bot API token; an admin cannot redirect it to an arbitrary server.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from ipaddress import ip_address
from urllib.parse import unquote, urlsplit

from aiohttp import BasicAuth
from aiogram.client.session.aiohttp import AiohttpSession
from cryptography.fernet import InvalidToken

import config
from services import shop_admin_security as security
from utils.telegram_worker import (
    CloudflareWorkerSession,
    validate_worker_origin,
)

MODES = frozenset({"direct", "http_proxy", "cloudflare_worker"})
_PROXY_SCHEMES = frozenset({"http", "socks5"})
_LABELS = {
    "direct": "Direct",
    "http_proxy": "HTTP / SOCKS5 Proxy",
    "cloudflare_worker": "Cloudflare Worker",
}
_HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,251}[a-z0-9]$")
_SECRET_MAX = 256


@dataclass(frozen=True, slots=True)
class TelegramTransportSpec:
    """Immutable transport settings; all sensitive fields are encrypted at rest."""

    mode: str
    proxy_url: str = ""
    proxy_username: str = ""
    proxy_password: str = ""
    worker_url: str = ""
    worker_secret: str = ""


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


def proxy_origin(\n    raw_url: str, *, permit_userinfo: bool = False,\n    permit_private: bool = False,\n) -> str:
    """Normalize an HTTP CONNECT or SOCKS5 endpoint and its explicit TCP port."""
    try:
        value = urlsplit(raw_url.strip())
        host = value.hostname
        port = value.port
    except (ValueError, AttributeError):
        raise security.SecurityRejected("invalid_proxy_endpoint", 422) from None
    if (
        value.scheme not in _PROXY_SCHEMES
        or not host or (not permit_private and not _public_host(host))
        or port is None or not 1 <= port <= 65535
        or value.path not in ("", "/")
        or value.query or value.fragment
        or (not permit_userinfo and (
            value.username is not None or value.password is not None
        ))
    ):
        raise security.SecurityRejected("invalid_proxy_endpoint", 422)
    return f"{value.scheme}://{host.lower()}:{port}"


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


def approved_proxy_urls() -> tuple[str, ...]:
    """Load approved endpoints from server policy, not from browser input."""
    approved: set[str] = set()
    declared = os.environ.get("TELEGRAM_PROXY_ALLOWED_ENDPOINTS", "")
    entries = [item.strip() for item in declared.split(",") if item.strip()]
    inherited = getattr(config, "TELEGRAM_PROXY_URL", None)
    if inherited:
        entries.append(inherited)
    for endpoint in entries:
        # A deployment misconfiguration does not accidentally widen policy.
        try:
            approved.add(proxy_origin(\n                endpoint, permit_userinfo=True, permit_private=True,\n            ))
        except security.SecurityRejected:
            continue
    return tuple(sorted(approved))


def approved_worker_origins() -> tuple[str, ...]:
    """Allow only previously authorized relay origins with private credentials."""
    approved: set[str] = set()
    declared = os.environ.get("TELEGRAM_WORKER_ALLOWED_ORIGINS", "")
    entries = [item.strip() for item in declared.split(",") if item.strip()]
    inherited = getattr(config, "TELEGRAM_WORKER_URL", "")
    if inherited:
        entries.append(inherited)
    for endpoint in entries:
        try:
            approved.add(_worker_origin(endpoint))
        except security.SecurityRejected:
            continue
    return tuple(sorted(approved))


def validate(spec: TelegramTransportSpec) -> TelegramTransportSpec:
    """Validate the full chosen configuration without making network calls."""
    if spec.mode not in MODES:
        raise security.SecurityRejected("invalid_transport_mode", 422)

    if spec.mode == "direct":
        if any((
            spec.proxy_url, spec.proxy_username, spec.proxy_password,
            spec.worker_url, spec.worker_secret,
        )):
            raise security.SecurityRejected("invalid_request", 422)
        return spec

    if spec.mode == "http_proxy":
        origin = proxy_origin(spec.proxy_url, permit_private=True)
        if origin not in approved_proxy_urls():
            raise security.SecurityRejected("transport_endpoint_not_approved", 422)
        if spec.worker_url or spec.worker_secret:
            raise security.SecurityRejected("invalid_request", 422)
        if (
            bool(spec.proxy_username) != bool(spec.proxy_password)
            or len(spec.proxy_username) > 128
            or len(spec.proxy_password) > _SECRET_MAX
            or any(not c.isprintable() for c in spec.proxy_username + spec.proxy_password)
        ):
            raise security.SecurityRejected("invalid_proxy_credentials", 422)
        return TelegramTransportSpec(
            mode=spec.mode,
            proxy_url=origin,
            proxy_username=spec.proxy_username,
            proxy_password=spec.proxy_password,
        )

    origin = _worker_origin(spec.worker_url)
    if origin not in approved_worker_origins():
        raise security.SecurityRejected("transport_endpoint_not_approved", 422)
    if spec.proxy_url or spec.proxy_username or spec.proxy_password:
        raise security.SecurityRejected("invalid_request", 422)
    if (
        not 32 <= len(spec.worker_secret) <= _SECRET_MAX
        or any(not c.isprintable() for c in spec.worker_secret)
    ):
        raise security.SecurityRejected("invalid_worker_secret", 422)
    return TelegramTransportSpec(
        mode=spec.mode, worker_url=origin, worker_secret=spec.worker_secret,
    )


def from_submission(
    payload: dict, previous: TelegramTransportSpec,
) -> TelegramTransportSpec:
    """Reuse an unchanged endpoint's hidden password unless replaced.

    Blank secrets on a different endpoint cannot be reused, and switching
    transports wipes irrelevant secrets before persistence.
    """
    mode = payload.get("mode")
    if mode == "direct":
        return validate(TelegramTransportSpec(mode="direct"))
    if mode == "http_proxy":
        endpoint = str(payload.get("proxy_url") or "").strip()
        normalized = proxy_origin(endpoint, permit_private=True)
        username = str(payload.get("proxy_username") or "").strip()
        password = str(payload.get("proxy_password") or "")
        if (
            not password and previous.mode == "http_proxy"
            and previous.proxy_url == normalized
            and previous.proxy_username == username
        ):
            password = previous.proxy_password
        return validate(TelegramTransportSpec(
            mode="http_proxy", proxy_url=normalized,
            proxy_username=username, proxy_password=password,
        ))
    if mode == "cloudflare_worker":
        url = _worker_origin(str(payload.get("worker_url") or ""))
        secret = str(payload.get("worker_secret") or "")
        if (
            not secret and previous.mode == "cloudflare_worker"
            and previous.worker_url == url
        ):
            secret = previous.worker_secret
        return validate(TelegramTransportSpec(
            mode="cloudflare_worker", worker_url=url, worker_secret=secret,
        ))
    raise security.SecurityRejected("invalid_transport_mode", 422)


def encrypted(spec: TelegramTransportSpec) -> str:
    """Encrypt the complete validated settings with the existing Fernet key."""
    safe = validate(spec)
    document = json.dumps(
        asdict(safe), ensure_ascii=False, separators=(",", ":"),
    )
    return security.cipher().encrypt(document.encode("utf-8")).decode("ascii")


def decrypted(value: str) -> TelegramTransportSpec:
    """Authenticate ciphertext and revalidate endpoints before any API call."""
    try:
        raw = security.cipher().decrypt(value.encode("ascii"))
        fields = json.loads(raw)
        if not isinstance(fields, dict) or set(fields) != set(
            TelegramTransportSpec.__dataclass_fields__
        ):
            raise ValueError("Invalid encrypted settings schema")
        if any(not isinstance(entry, str) for entry in fields.values()):
            raise ValueError("Invalid encrypted settings types")
        return validate(TelegramTransportSpec(**fields))
    except (InvalidToken, ValueError, UnicodeError, TypeError):
        raise security.SecurityRejected("transport_config_unreadable", 503) from None


def env_spec() -> TelegramTransportSpec:
    """Resolve legacy deployment settings without storing plaintext secrets."""
    mode = getattr(config, "TELEGRAM_API_MODE", "direct")
    if mode == "direct":
        return TelegramTransportSpec(mode="direct")
    if mode == "http_proxy":
        raw = getattr(config, "TELEGRAM_PROXY_URL", "") or ""
        try:
            info = urlsplit(raw)
            username = unquote(info.username) if info.username else ""
            password = unquote(info.password) if info.password else ""
        except ValueError:
            raise security.SecurityRejected("invalid_proxy_endpoint", 503) from None
        return validate(TelegramTransportSpec(
            mode="http_proxy", proxy_url=proxy_origin(
                raw, permit_userinfo=True, permit_private=True,
            ), proxy_username=username, proxy_password=password,
        ))
    if mode == "cloudflare_worker":
        return validate(TelegramTransportSpec(
            mode="cloudflare_worker",
            worker_url=getattr(config, "TELEGRAM_WORKER_URL", ""),
            worker_secret=getattr(config, "TELEGRAM_WORKER_SECRET", ""),
        ))
    raise security.SecurityRejected("invalid_transport_mode", 503)


def make_session(spec: TelegramTransportSpec) -> AiohttpSession:
    """Construct the chosen Aiogram session without modifying Bale or Bot tokens."""
    validated = validate(spec)
    if validated.mode == "direct":
        return AiohttpSession()
    if validated.mode == "http_proxy":
        auth = (
            BasicAuth(validated.proxy_username, validated.proxy_password)
            if validated.proxy_username else None
        )
        return AiohttpSession(
            proxy=(validated.proxy_url, auth) if auth else validated.proxy_url,
        )
    return CloudflareWorkerSession(
        worker_url=validated.worker_url,
        relay_secret=validated.worker_secret,
    )


def config_fingerprint(spec: TelegramTransportSpec) -> str:
    """Compute a non-reversible digest of the exact active route and credentials."""
    payload = json.dumps(
        asdict(spec), ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def public_data(spec: TelegramTransportSpec, *, version: int, source: str) -> dict:
    """Expose human-friendly settings without returning authentication material."""
    return {
        "mode": spec.mode,
        "label": _LABELS[spec.mode],
        "version": version,
        "source": source,
        "proxy_url": spec.proxy_url if spec.mode == "http_proxy" else "",
        "proxy_username": spec.proxy_username if spec.mode == "http_proxy" else "",
        "has_proxy_password": bool(spec.proxy_password),
        "worker_url": spec.worker_url if spec.mode == "cloudflare_worker" else "",
        "has_worker_secret": bool(spec.worker_secret),
    }
