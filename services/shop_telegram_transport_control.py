"""Durable, audited and hot-applied Telegram transport control plane.

Only the active Telegram token from Deployment is used for provider probes.
A two-phase operation persists "applying" before any outgoing network call;
a crash retains an explicit needs_review receipt, never an automatic retry.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models.shop_bot_profile import ShopBotProfile
from models.shop_telegram_transport import (
    ShopTelegramTransport,
    ShopTelegramTransportChange,
)
from services import shop_admin_security as security
from services.shop_telegram_transport import (
    TelegramTransportSpec,
    approved_proxy_urls,
    approved_worker_origins,
    decrypted,
    encrypted,
    config_fingerprint,
    env_spec,
    from_submission,
    make_session,
    public_data,
)
from utils.telegram_rotating_session import RotatingTelegramSession

CHANGE_LIFETIME = timedelta(minutes=15)
_CONTROL_LOCK_ID = 90211008
_LOCAL_APPLY_LOCK = asyncio.Lock()


async def _lease(db: AsyncSession) -> None:
    """Serialize transport staging with an exclusive transaction advisory lock."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {
        "lock_id": _CONTROL_LOCK_ID,
    })


async def _current(
    db: AsyncSession, *, lock: bool = False,
) -> tuple[ShopTelegramTransport | None, TelegramTransportSpec, int]:
    """Read the verified config or the currently configured deployment fallback."""
    statement = select(ShopTelegramTransport).where(
        ShopTelegramTransport.id == 1,
    )
    if lock:
        statement = statement.with_for_update()
    record = await db.scalar(statement)
    if record is None:
        return None, env_spec(), 1
    return record, decrypted(record.config_ciphertext), record.version


async def overview(db: AsyncSession) -> dict:
    """Provide redacted active configuration, approved endpoints and history."""
    active, spec, version = await _current(db)
    history = (await db.scalars(
        select(ShopTelegramTransportChange)
        .order_by(ShopTelegramTransportChange.created_at.desc())
        .limit(40)
    )).all()
    items = []
    for row in history:
        # Fail closed rather than reflecting raw encrypted/corrupt database data.
        proposed = decrypted(row.proposed_ciphertext)
        items.append({
            "id": row.id,
            "operation": row.operation,
            "status": row.status,
            "expected_version": row.expected_version,
            "proposed": public_data(
                proposed, version=row.expected_version + 1, source="staged",
            ),
            "error_code": row.error_code,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        })
    return {
        "active": {
            **public_data(
                spec, version=version,
                source="database" if active else "deployment",
            ),
            "verified_at": (
                active.verified_at.isoformat() if active else None
            ),
            "verified_bot_id": (
                str(active.verified_bot_id) if active else None
            ),
        },
        "approved_proxy_urls": list(approved_proxy_urls()),
        "approved_worker_origins": list(approved_worker_origins()),
        "history": items,
    }


async def _stage_spec(
    db: AsyncSession, *, actor_id: int, spec: TelegramTransportSpec,
    version: int, operation: str,
) -> ShopTelegramTransportChange:
    """Persist a proposed/previous encrypted snapshot, no provider effects."""
    await _lease(db)
    active, current, actual_version = await _current(db, lock=True)
    if version != actual_version:
        raise security.SecurityRejected("configuration_changed", 409)
    if spec == current:
        raise security.SecurityRejected("transport_unchanged", 409)
    existing = await db.scalar(
        select(ShopTelegramTransportChange.id).where(
            ShopTelegramTransportChange.status.in_(
                ("pending", "applying", "needs_review"),
            )
        ).limit(1)
    )
    if existing:
        raise security.SecurityRejected("connection_change_in_progress", 409)
    row = ShopTelegramTransportChange(
        id=str(uuid4()),
        actor_id=actor_id,
        expected_version=version,
        proposed_ciphertext=encrypted(spec),
        previous_ciphertext=encrypted(current),
        operation=operation,
        status="pending",
    )
    db.add(row)
    await db.run_sync(lambda sync: security.audit(
        sync, actor_id, "transport.staged", row.id,
    ))
    await db.commit()
    return row


async def stage(
    db: AsyncSession, *, actor_id: int, values: dict, version: int,
) -> ShopTelegramTransportChange:
    """Verify all input types, resolve kept credentials, then stage."""
    _, previous, _ = await _current(db)
    spec = from_submission(values, previous)
    return await _stage_spec(
        db, actor_id=actor_id, spec=spec,
        version=version, operation="switch",
    )


async def stage_rollback(
    db: AsyncSession, *, actor_id: int, source_id: str, version: int,
) -> ShopTelegramTransportChange:
    """Create a new stage from a previously verified previous configuration."""
    source = await db.get(ShopTelegramTransportChange, source_id)
    if (
        source is None or source.status != "succeeded"
        or not source.previous_ciphertext
    ):
        raise security.SecurityRejected("transport_history_not_found", 404)
    return await _stage_spec(
        db, actor_id=actor_id,
        spec=decrypted(source.previous_ciphertext),
        version=version, operation="rollback",
    )


async def cancel(
    db: AsyncSession, *, actor_id: int, change_id: str,
) -> None:
    """Cancel only a pending change, never an already-applied network switch."""
    await _lease(db)
    row = await db.scalar(select(ShopTelegramTransportChange).where(
        ShopTelegramTransportChange.id == change_id,
    ).with_for_update())
    if row is None or row.status != "pending":
        raise security.SecurityRejected("invalid_operation_state", 409)
    row.status = "cancelled"
    row.updated_at = security.clock()
    await db.run_sync(lambda sync: security.audit(
        sync, actor_id, "transport.cancelled", change_id,
    ))
    await db.commit()


async def mark_interrupted_on_boot(db: AsyncSession) -> None:
    """Quarantine interrupted apply attempts; never replay a network change."""
    rows = (await db.scalars(select(ShopTelegramTransportChange).where(
        ShopTelegramTransportChange.status == "applying",
    ).with_for_update())).all()
    for row in rows:
        row.status = "needs_review"
        row.error_code = "transport_interrupted"
        row.updated_at = security.clock()
    if rows:
        await db.commit()


async def load_verified_on_boot(bot) -> int | None:
    """Install last committed settings before the first live Bot API call."""
    from db import session_maker

    if not isinstance(bot.session, RotatingTelegramSession):
        raise RuntimeError("Telegram Bot must use a managed session")
    async with session_maker() as db:
        await mark_interrupted_on_boot(db)
        active, spec, _ = await _current(db)
        if active is None:
            bot.session._fingerprint = config_fingerprint(spec)
            return None
        candidate = make_session(spec)
        try:
            previous = await bot.session.replace(
                candidate, fingerprint=config_fingerprint(spec),
            )
        except BaseException:
            await candidate.close()
            raise
        await previous.close()
        return active.verified_bot_id


async def _record_error(
    change_id: str, *, uncertain: bool,
    error_code: str = "transport_probe_failed",
) -> None:
    """Store a safe failure code after a provider failure or ambiguous swap."""
    from db import session_maker

    try:
        async with session_maker() as db:
            row = await db.get(
                ShopTelegramTransportChange, change_id,
                with_for_update=True,
            )
            if row is not None and row.status == "applying":
                row.status = "needs_review" if uncertain else "failed"
                row.error_code = (
                    "transport_reconciliation_required" if uncertain
                    else error_code
                )
                row.updated_at = security.clock()
                await db.commit()
    except Exception:
        # Startup detects any remaining 'applying' state and quarantines it.
        pass


async def apply(
    db: AsyncSession, *, actor_id: int, change_id: str, bot,
) -> dict:
    """Probe getMe through candidate, drain current calls and commit new route.

    Uses no Telegram webhook mutation, no token rotation and no retry of
    payment-changing operations. Returning success requires a database commit.
    """
    from utils.telegram import create_bot

    if not config.TOKEN:
        raise security.SecurityRejected("provider_not_configured", 409)
    if not isinstance(bot.session, RotatingTelegramSession):
        raise security.SecurityRejected("transport_worker_unavailable", 503)

    async with _LOCAL_APPLY_LOCK:
        await _lease(db)
        row = await db.scalar(select(ShopTelegramTransportChange).where(
            ShopTelegramTransportChange.id == change_id,
        ).with_for_update())
        if row is None:
            raise security.SecurityRejected("operation_not_found", 404)
        if row.status == "succeeded":
            return {"ok": True, "status": "succeeded"}
        if row.status != "pending":
            raise security.SecurityRejected("invalid_operation_state", 409)
        if security.utc(row.created_at) + CHANGE_LIFETIME <= security.clock():
            row.status = "failed"
            row.error_code = "transport_stage_expired"
            row.updated_at = security.clock()
            await db.commit()
            raise security.SecurityRejected("transport_stage_expired", 410)
        active, _, current_version = await _current(db, lock=True)
        if row.expected_version != current_version:
            raise security.SecurityRejected("configuration_changed", 409)
        proposed_ciphertext = row.proposed_ciphertext
        identity = active.verified_bot_id if active else None
        expected_profile = await db.get(ShopBotProfile, "telegram")
        if expected_profile and expected_profile.provider_bot_id:
            identity = expected_profile.provider_bot_id
        row.status = "applying"
        row.updated_at = security.clock()
        await db.run_sync(lambda sync: security.audit(
            sync, actor_id, "transport.applying", change_id,
        ))
        await db.commit()

        candidate = None
        old_session = None
        swapped = False
        try:
            spec = decrypted(proposed_ciphertext)
            candidate = make_session(spec)
            probe_bot = create_bot(config.TOKEN, candidate)
            result = await asyncio.wait_for(probe_bot.get_me(), timeout=15)
            if type(result.id) is not int or result.id <= 0:
                raise security.SecurityRejected("provider_state_unavailable", 503)
            if identity is not None and result.id != identity:
                raise security.SecurityRejected("bot_identity_mismatch", 409)

            # Snapshot replacement does not close the old session until the
            # persisted optimistic-version update is durably committed.
            old_fingerprint = bot.session.fingerprint
            old_session = await asyncio.wait_for(
                bot.session.replace(
                    candidate, fingerprint=config_fingerprint(spec),
                ),
                timeout=30,
            )
            swapped = True

            active = await db.get(
                ShopTelegramTransport, 1, with_for_update=True,
            )
            if active is None:
                active = ShopTelegramTransport(
                    id=1, version=1,
                    config_ciphertext=proposed_ciphertext,
                    verified_bot_id=result.id,
                    verified_at=security.clock(),
                    updated_by=actor_id,
                )
                db.add(active)
            if active.version != row.expected_version:
                raise security.SecurityRejected("configuration_changed", 409)
            active.version += 1
            active.config_ciphertext = proposed_ciphertext
            active.verified_bot_id = result.id
            active.verified_at = security.clock()
            active.updated_by = actor_id

            row = await db.get(
                ShopTelegramTransportChange, change_id, with_for_update=True,
            )
            row.status = "succeeded"
            row.error_code = None
            row.verified_bot_id = result.id
            row.updated_at = security.clock()
            await db.run_sync(lambda sync: security.audit(
                sync, actor_id, "transport.succeeded", change_id,
            ))
            await db.commit()
            try:
                await old_session.close()
            except Exception:
                # Once the new row is verified and committed, cleanup cannot
                # change the business outcome or roll back the active route.
                pass
            return {
                "ok": True, "status": "succeeded",
                "version": active.version, "verified_bot_id": str(result.id),
            }
        except BaseException as error:
            reason = (
                error.code if isinstance(error, security.SecurityRejected)
                else "transport_probe_failed"
            )
            uncertain = swapped
            if swapped and old_session is not None:
                try:
                    replaced = await bot.session.replace(
                        old_session, fingerprint=old_fingerprint,
                    )
                    await replaced.close()
                    uncertain = False
                except BaseException:
                    uncertain = True
            elif candidate is not None:
                await candidate.close()
            await db.rollback()
            await _record_error(
                change_id, uncertain=uncertain, error_code=reason,
            )
            if uncertain:
                raise security.SecurityRejected(
                    "transport_reconciliation_required", 503,
                ) from None
            raise security.SecurityRejected(
                reason,
                error.status if isinstance(error, security.SecurityRejected)
                else 503,
            ) from None


async def sync_broadcast_session(bot) -> bool:
    """Align the separate broadcast process with the verified DB transport.

    Unlike API startup this function never reclassifies an in-progress admin
    operation. It runs before each recipient is claimed and each outbound step,
    so newly queued broadcasts never rely on a stale Deployment-only route.
    """
    from db import session_maker
    from utils.telegram import create_bot

    if not isinstance(bot.session, RotatingTelegramSession):
        raise RuntimeError("Broadcast Telegram session must be managed")
    async with session_maker() as db:
        active, spec, _ = await _current(db)
        fingerprint = config_fingerprint(spec)
        expected_id = active.verified_bot_id if active else None
    if bot.session.fingerprint == fingerprint:
        return False
    if active is None:
        # This is the initial Deployment transport, already constructed at
        # worker startup. No network request is needed for an unchanged route.
        bot.session._fingerprint = fingerprint
        return False

    candidate = make_session(spec)
    try:
        probing = create_bot(config.TOKEN, candidate)
        observed = await asyncio.wait_for(probing.get_me(), timeout=15)
        if observed.id != expected_id:
            raise security.SecurityRejected("bot_identity_mismatch", 409)
        old = await asyncio.wait_for(
            bot.session.replace(
                candidate, fingerprint=fingerprint,
            ), timeout=30,
        )
    except BaseException:
        await candidate.close()
        raise
    try:
        await old.close()
    except Exception:
        # A retired session may already have closed during shutdown.
        pass
    return True


async def reconcile(
    db: AsyncSession, *, actor_id: int, change_id: str, bot,
) -> dict:
    """Resolve an uncertain receipt only when the verified old route is active.

    The operation NEVER sends the staged transport through a new probe.
    It compares the live session fingerprint against the durable configuration
    and verifies the current bot identity through that already active route.
    """
    if not isinstance(bot.session, RotatingTelegramSession):
        raise security.SecurityRejected("transport_worker_unavailable", 503)
    await _lease(db)
    row = await db.get(
        ShopTelegramTransportChange, change_id, with_for_update=True,
    )
    if row is None or row.status != "needs_review":
        raise security.SecurityRejected("invalid_operation_state", 409)
    active, current, _ = await _current(db, lock=True)
    if bot.session.fingerprint != config_fingerprint(current):
        raise security.SecurityRejected(
            "transport_reconciliation_required", 409,
        )
    try:
        observed = await asyncio.wait_for(bot.get_me(), timeout=12)
    except Exception:
        raise security.SecurityRejected(
            "transport_reconciliation_required", 503,
        ) from None
    if active and observed.id != active.verified_bot_id:
        raise security.SecurityRejected("bot_identity_mismatch", 409)

    row.status = "failed"
    row.error_code = "transport_restored_to_verified"
    row.updated_at = security.clock()
    await db.run_sync(lambda sync: security.audit(
        sync, actor_id, "transport.reconciled", change_id,
    ))
    await db.commit()
    return {"ok": True, "status": "failed", "current_verified": True}
