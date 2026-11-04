"""Signed-admin management and credential vault for the outbound relay pool.

An assigned route is never automatically promoted. A staged credential must
first be installed in its Cloudflare Worker secret binding and prove the
registered bot identity through a read-only getMe call. All secrets are bound
to exactly one bot and one worker, with no plaintext readback API.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re

import config
from datetime import datetime, timezone
from uuid import uuid4

from aiogram.exceptions import TelegramNetworkError
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_multibot import ShopBot, ShopStore, ShopBotCredential
from models.shop_relay_pool import (
    ShopBotRelayRoute, ShopRelayCredential, ShopRelayEvent, ShopRelayWorker,
)
from services import shop_admin_security as security
from services.shop_bot_secrets import _key_bytes, decrypt_for_bot
from services.shop_telegram_transport import approved_worker_origins
from utils.telegram import create_bot
from utils.telegram_worker import CloudflareWorkerSession, validate_worker_origin

_SLUG = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_RELAY_KEY = re.compile(r"^[\x21-\x7e]{32,256}$")
_PURPOSE = b"aiogramshopbot:relay-auth-storage:v1"


def _cipher() -> Fernet:
    """Derive a distinct authenticated encryption key for relay credentials."""
    secret = hmac.new(_key_bytes(), _PURPOSE, hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(secret))


def _encrypt_secret(
    *, worker_id: str, bot_id: str, version: int, secret: str,
) -> str:
    """Bind the secret to one immutable worker/bot/version combination."""
    if not isinstance(secret, str) or not _RELAY_KEY.fullmatch(secret):
        raise security.SecurityRejected("invalid_worker_secret", 422)
    value = json.dumps({
        "schema": 1, "worker_id": worker_id, "bot_id": bot_id,
        "version": version, "purpose": "telegram-relay-v2", "secret": secret,
    }, ensure_ascii=True, separators=(",", ":"))
    return _cipher().encrypt(value.encode("ascii")).decode("ascii")


def decrypt_secret(credential: ShopRelayCredential) -> str:
    """Return a secret only inside trusted backend operations."""
    try:
        value = json.loads(_cipher().decrypt(
            credential.ciphertext.encode("ascii"),
        ))
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        raise security.SecurityRejected("relay_secret_unreadable", 503) from None
    if (
        not isinstance(value, dict) or value.get("schema") != 1
        or value.get("purpose") != "telegram-relay-v2"
        or value.get("bot_id") != credential.bot_id
        or value.get("worker_id") != credential.worker_id
        or value.get("version") != credential.version
        or not isinstance(value.get("secret"), str)
        or not _RELAY_KEY.fullmatch(value["secret"])
    ):
        raise security.SecurityRejected("relay_secret_binding_mismatch", 409)
    return value["secret"]


def _event(
    db: AsyncSession, worker_id: str, bot_id: str | None,
    actor_id: int | None, action: str, code: str | None = None,
) -> None:
    """Append an audit event without including a token or credential."""
    db.add(ShopRelayEvent(
        id=str(uuid4()), worker_id=worker_id, bot_id=bot_id,
        actor_id=actor_id, action=action, outcome_code=code,
    ))


def _origin(value: str) -> str:
    """Require an approved public relay origin from deployment policy."""
    try:
        origin = validate_worker_origin(value)
    except ValueError:
        raise security.SecurityRejected("invalid_worker_origin", 422) from None
    if origin not in approved_worker_origins():
        raise security.SecurityRejected(
            "transport_endpoint_not_approved", 422,
        )
    return origin


def _safe_worker(worker: ShopRelayWorker) -> dict:
    """Serialize no token or secret, including internal credential hashes."""
    return {
        "id": worker.id, "slug": worker.slug, "name": worker.name,
        "origin": worker.origin, "status": worker.status,
        "max_rps": worker.max_rps, "max_inflight": worker.max_inflight,
        "version": worker.version,
        "updated_at": (
            worker.updated_at.isoformat() if worker.updated_at else None
        ),
    }


def _safe_route(
    route: ShopBotRelayRoute, worker: ShopRelayWorker,
    credential: ShopRelayCredential | None,
) -> dict:
    """Display exact route/secret-state versions without auth material."""
    return {
        "bot_id": route.bot_id, "worker_id": route.worker_id,
        "worker_name": worker.name, "worker_status": worker.status,
        "priority": route.priority, "status": route.status,
        "version": route.version,
        "credential_version": credential.version if credential else None,
        "credential_state": credential.state if credential else None,
        "credential_verified_at": (
            credential.verified_at.isoformat()
            if credential and credential.verified_at else None
        ),
    }


async def list_workers(db: AsyncSession) -> dict:
    """List all registered relay endpoints with safe assignment counts."""
    rows = (await db.scalars(
        select(ShopRelayWorker).order_by(ShopRelayWorker.name).limit(500)
    )).all()
    counts = (await db.execute(
        select(
            ShopBotRelayRoute.worker_id,
            func.count(ShopBotRelayRoute.bot_id),
        ).group_by(ShopBotRelayRoute.worker_id)
    )).all()
    mapped = dict(counts)
    return {
        "items": [{**_safe_worker(row), "bot_count": int(
            mapped.get(row.id, 0),
        )} for row in rows],
        "enabled": bool(config.SHOP_RELAY_POOL_ENABLED),
        "approved_origins": list(approved_worker_origins()),
    }


async def list_bot_routes(
    db: AsyncSession, bot_id: str,
) -> dict:
    """Return one bot's explicit outbound routes in priority order."""
    if await db.get(ShopBot, bot_id) is None:
        raise security.SecurityRejected("bot_not_found", 404)
    pairs = (await db.execute(
        select(ShopBotRelayRoute, ShopRelayWorker)
        .join(
            ShopRelayWorker, ShopRelayWorker.id == ShopBotRelayRoute.worker_id,
        ).where(ShopBotRelayRoute.bot_id == bot_id)
        .order_by(ShopBotRelayRoute.priority).limit(100)
    )).all()
    items = []
    for route, worker in pairs:
        credential = await db.scalar(select(ShopRelayCredential).where(
            ShopRelayCredential.bot_id == bot_id,
            ShopRelayCredential.worker_id == worker.id,
            ShopRelayCredential.state.in_(("staged", "active")),
        ).order_by(ShopRelayCredential.version.desc()).limit(1))
        history = (await db.scalars(select(ShopRelayCredential).where(
            ShopRelayCredential.bot_id == bot_id,
            ShopRelayCredential.worker_id == worker.id,
        ).order_by(ShopRelayCredential.version.desc()).limit(20))).all()
        row = _safe_route(route, worker, credential)
        row["credential_history"] = [{
            "version": item.version,
            "state": item.state,
            "verified_at": (
                item.verified_at.isoformat() if item.verified_at else None
            ),
        } for item in history]
        items.append(row)
    return {"bot_id": bot_id, "items": items}


async def create_worker(
    db: AsyncSession, *, slug: str, name: str, origin: str,
    max_rps: int, max_inflight: int, actor_id: int,
) -> dict:
    """Create an inert worker record without contacting its HTTPS endpoint."""
    if (
        not isinstance(slug, str) or not _SLUG.fullmatch(slug)
        or not isinstance(name, str) or not 1 <= len(name.strip()) <= 160
        or type(max_rps) is not int or not 1 <= max_rps <= 20
        or type(max_inflight) is not int or not 1 <= max_inflight <= 50
    ):
        raise security.SecurityRejected("invalid_relay_worker", 422)
    endpoint = _origin(origin)
    existing = await db.scalar(select(ShopRelayWorker.id).where(
        (ShopRelayWorker.slug == slug)
        | (ShopRelayWorker.origin == endpoint),
    ))
    if existing:
        raise security.SecurityRejected("relay_worker_exists", 409)
    worker = ShopRelayWorker(
        id=str(uuid4()), slug=slug, name=name.strip(), origin=endpoint,
        max_rps=max_rps, max_inflight=max_inflight, status="draft",
        updated_by=actor_id,
    )
    db.add(worker)
    _event(db, worker.id, None, actor_id, "created")
    await db.commit()
    return _safe_worker(worker)


async def update_worker_state(
    db: AsyncSession, *, worker_id: str, state: str,
    expected_version: int, actor_id: int,
) -> dict:
    """Pause/disable or resume an already verified worker without secret edits."""
    if state not in {"active", "paused", "disabled"}:
        raise security.SecurityRejected("invalid_relay_worker", 422)
    worker = await db.scalar(select(ShopRelayWorker).where(
        ShopRelayWorker.id == worker_id,
    ).with_for_update())
    if worker is None:
        raise security.SecurityRejected("relay_worker_not_found", 404)
    if worker.version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)
    if state == "active":
        exists = await db.scalar(select(ShopBotRelayRoute.bot_id).where(
            ShopBotRelayRoute.worker_id == worker_id,
            ShopBotRelayRoute.status == "active",
        ).limit(1))
        if not exists:
            raise security.SecurityRejected("relay_worker_not_verified", 409)
    if worker.status == state:
        raise security.SecurityRejected("bot_state_unchanged", 409)
    worker.status = state
    worker.version += 1
    worker.updated_by = actor_id
    _event(db, worker.id, None, actor_id, "state_changed")
    await db.commit()
    return _safe_worker(worker)


async def assign_route(
    db: AsyncSession, *, bot_id: str, worker_id: str,
    priority: int, actor_id: int, expected_version: int | None = None,
) -> dict:
    """Attach a Worker to a bot without granting immediate transport access."""
    if type(priority) is not int or not 1 <= priority <= 1000:
        raise security.SecurityRejected("invalid_relay_priority", 422)
    bot = await db.get(ShopBot, bot_id)
    worker = await db.get(ShopRelayWorker, worker_id)
    store = await db.get(ShopStore, bot.store_id) if bot else None
    if (
        bot is None or bot.runtime_owner != "registry"
        or bot.platform != "telegram"
        or store is None or store.state != "active"
        or worker is None or worker.status == "disabled"
    ):
        raise security.SecurityRejected("relay_route_not_supported", 409)
    priority_owner = await db.scalar(select(ShopBotRelayRoute.worker_id).where(
        ShopBotRelayRoute.bot_id == bot_id,
        ShopBotRelayRoute.priority == priority,
        ShopBotRelayRoute.worker_id != worker_id,
    ).limit(1))
    if priority_owner is not None:
        raise security.SecurityRejected("relay_priority_taken", 409)
    row = await db.scalar(select(ShopBotRelayRoute).where(
        ShopBotRelayRoute.bot_id == bot_id,
        ShopBotRelayRoute.worker_id == worker_id,
    ).with_for_update())
    if row is None:
        if expected_version is not None:
            raise security.SecurityRejected("configuration_changed", 409)
        row = ShopBotRelayRoute(
            bot_id=bot_id, worker_id=worker_id, priority=priority,
            status="staged", updated_by=actor_id,
        )
        db.add(row)
        action = "assigned"
    else:
        if row.version != expected_version:
            raise security.SecurityRejected("configuration_changed", 409)
        if row.status == "active":
            raise security.SecurityRejected("relay_route_must_pause", 409)
        row.priority = priority
        row.version += 1
        row.updated_by = actor_id
        action = "priority_changed"
    _event(db, worker_id, bot_id, actor_id, action)
    await db.commit()
    return _safe_route(row, worker, None)


async def stage_credential(
    db: AsyncSession, *, bot_id: str, worker_id: str,
    secret: str, actor_id: int,
) -> dict:
    """Stage a new per-bot credential while the previous active key still works."""
    route = await db.scalar(select(ShopBotRelayRoute).where(
        ShopBotRelayRoute.bot_id == bot_id,
        ShopBotRelayRoute.worker_id == worker_id,
    ).with_for_update())
    bot = await db.get(ShopBot, bot_id)
    if (
        route is None or bot is None
        or bot.platform != "telegram"
        or bot.runtime_owner != "registry"
        or bot.provider_bot_id is None or bot.verified_at is None
    ):
        raise security.SecurityRejected("relay_route_not_supported", 409)
    if not isinstance(secret, str) or not _RELAY_KEY.fullmatch(secret):
        raise security.SecurityRejected("invalid_worker_secret", 422)
    key_fingerprint = hmac.new(
        _key_bytes(), ("relay-auth:v2:" + secret).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    duplicate = await db.scalar(select(ShopRelayCredential.id).where(
        ShopRelayCredential.key_fingerprint == key_fingerprint,
        ShopRelayCredential.state != "revoked",
    ).limit(1))
    if duplicate is not None:
        raise security.SecurityRejected("duplicate_relay_credential", 409)
    version = int(await db.scalar(
        select(func.max(ShopRelayCredential.version)).where(
            ShopRelayCredential.bot_id == bot_id,
            ShopRelayCredential.worker_id == worker_id,
        )
    ) or 0) + 1
    previous = (await db.scalars(select(ShopRelayCredential).where(
        ShopRelayCredential.bot_id == bot_id,
        ShopRelayCredential.worker_id == worker_id,
        ShopRelayCredential.state == "staged",
    ).with_for_update())).all()
    for item in previous:
        item.state = "revoked"
    row = ShopRelayCredential(
        id=str(uuid4()), bot_id=bot_id, worker_id=worker_id,
        version=version, state="staged",
        key_fingerprint=key_fingerprint,
        ciphertext=_encrypt_secret(
            worker_id=worker_id, bot_id=bot_id,
            version=version, secret=secret,
        ),
        created_by=actor_id,
    )
    db.add(row)
    _event(db, worker_id, bot_id, actor_id, "credential_staged")
    await db.commit()
    return {
        "bot_id": bot_id, "worker_id": worker_id,
        "version": version, "state": "staged",
        "requires_worker_provisioning": True,
    }


async def _verified_bot_token(
    db: AsyncSession, bot: ShopBot,
) -> str:
    """Read a verified registry credential even before receiver activation."""
    rows = (await db.scalars(select(ShopBotCredential).where(
        ShopBotCredential.bot_id == bot.id,
        ShopBotCredential.verified_bot_id == bot.provider_bot_id,
        ShopBotCredential.verified_at.is_not(None),
        ShopBotCredential.state.in_(("active", "staged")),
    ).order_by(ShopBotCredential.version.desc()).limit(1))).all()
    if not rows or not rows[0].ciphertext:
        raise security.SecurityRejected("bot_credential_not_verified", 409)
    return decrypt_for_bot(
        bot.id, bot.platform, rows[0].ciphertext,
    )


async def activate_route(
    db: AsyncSession, *, bot_id: str, worker_id: str,
    expected_version: int, credential_version: int, actor_id: int,
) -> dict:
    """Probe read-only getMe and promote a secret only on matching bot identity.

    Provider network calls are made outside a transaction. Two simultaneous
    probes are harmless; the post-probe version check serializes promotion.
    """
    if not config.SHOP_RELAY_POOL_ENABLED:
        raise security.SecurityRejected("relay_pool_disabled", 409)
    worker = await db.get(ShopRelayWorker, worker_id)
    bot = await db.get(ShopBot, bot_id)
    route = await db.get(
        ShopBotRelayRoute, (bot_id, worker_id),
    )
    credential = await db.scalar(select(ShopRelayCredential).where(
        ShopRelayCredential.bot_id == bot_id,
        ShopRelayCredential.worker_id == worker_id,
        ShopRelayCredential.version == credential_version,
        ShopRelayCredential.state.in_(("staged", "active")),
    ))
    store = await db.get(ShopStore, bot.store_id) if bot else None
    if (
        worker is None or worker.status == "disabled"
        or bot is None or bot.runtime_owner != "registry"
        or bot.platform != "telegram"
        or store is None or store.state != "active"
        or bot.provider_bot_id is None or bot.verified_at is None
        or route is None or route.version != expected_version
        or credential is None
        or (
            credential.state == "active" and route.status != "paused"
        )
    ):
        raise security.SecurityRejected("relay_activation_not_ready", 409)
    origin = _origin(worker.origin)
    secret = decrypt_secret(credential)
    token = await _verified_bot_token(db, bot)
    expected_provider_id = bot.provider_bot_id
    # Persist the verified admin MFA/replay receipt before remote I/O.
    # Rollback here would allow reusing the same one-time proof.
    await db.commit()
    relay = CloudflareWorkerSession(
        worker_url=origin, relay_secret=secret, bot_id=bot_id,
        credential_version=credential_version,
    )
    client = create_bot(token, relay)
    try:
        try:
            identity = await client.get_me()
        except Exception:
            # Never return network exceptions containing token-bearing URLs.
            raise security.SecurityRejected(
                "relay_probe_failed", 503,
            ) from None
    finally:
        await client.session.close()
    if identity.id != expected_provider_id:
        raise security.SecurityRejected("bot_identity_mismatch", 409)

    # Recheck every security-critical record after the network probe.
    route = await db.scalar(select(ShopBotRelayRoute).where(
        ShopBotRelayRoute.bot_id == bot_id,
        ShopBotRelayRoute.worker_id == worker_id,
    ).with_for_update())
    worker = await db.get(ShopRelayWorker, worker_id, with_for_update=True)
    bot = await db.get(ShopBot, bot_id, with_for_update=True)
    credential = await db.scalar(select(ShopRelayCredential).where(
        ShopRelayCredential.bot_id == bot_id,
        ShopRelayCredential.worker_id == worker_id,
        ShopRelayCredential.version == credential_version,
    ).with_for_update())
    if (
        worker is None or worker.status == "disabled"
        or _origin(worker.origin) != origin
        or route is None or route.version != expected_version
        or bot is None or bot.provider_bot_id != identity.id
        or credential is None
        or credential.state not in {"staged", "active"}
        or (
            credential.state == "active" and route.status != "paused"
        )
    ):
        raise security.SecurityRejected("configuration_changed", 409)
    promoting = credential.state == "staged"
    old = (await db.scalars(select(ShopRelayCredential).where(
        ShopRelayCredential.bot_id == bot_id,
        ShopRelayCredential.worker_id == worker_id,
        ShopRelayCredential.state == "active",
    ).with_for_update())).all()
    if promoting:
        for item in old:
            item.state = "retiring"
        # Exactly one active key remains after a staged-key promotion.
        await db.flush()
        credential.state = "active"
    credential.verified_at = datetime.now(timezone.utc)
    route.status = "active"
    route.version += 1
    route.updated_by = actor_id
    worker.status = "active"
    worker.version += 1
    worker.updated_by = actor_id
    _event(
        db, worker_id, bot_id, actor_id,
        "route_activated" if promoting else "route_resumed",
    )
    await db.commit()
    return {
        "ok": True, "bot_id": bot_id,
        "worker_id": worker_id, "version": route.version,
        "credential_version": credential.version,
        "state": "active",
    }


async def pause_route(
    db: AsyncSession, *, bot_id: str, worker_id: str,
    expected_version: int, actor_id: int,
) -> dict:
    """Pause only future outbound route selection, not pending receipts."""
    route = await db.scalar(select(ShopBotRelayRoute).where(
        ShopBotRelayRoute.bot_id == bot_id,
        ShopBotRelayRoute.worker_id == worker_id,
    ).with_for_update())
    if route is None or route.version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)
    if route.status != "active":
        raise security.SecurityRejected("invalid_operation_state", 409)
    route.status = "paused"
    route.version += 1
    route.updated_by = actor_id
    _event(db, worker_id, bot_id, actor_id, "route_paused")
    await db.commit()
    return {"ok": True, "version": route.version, "status": route.status}


async def revoke_unused_credential(
    db: AsyncSession, *, bot_id: str, worker_id: str,
    version: int, actor_id: int,
) -> dict:
    """Revoke only unused/stale keys; Worker-side deprovisioning is manual."""
    row = await db.scalar(select(ShopRelayCredential).where(
        ShopRelayCredential.bot_id == bot_id,
        ShopRelayCredential.worker_id == worker_id,
        ShopRelayCredential.version == version,
    ).with_for_update())
    if row is None or row.state not in {"staged", "retiring"}:
        raise security.SecurityRejected("invalid_credential_state", 409)
    row.state = "revoked"
    _event(db, worker_id, bot_id, actor_id, "credential_revoked")
    await db.commit()
    return {"ok": True, "state": "revoked"}
