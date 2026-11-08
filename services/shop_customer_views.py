"""Bounded customer view state and per-conversation ordering."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from channels.contracts import BotReply
from models.shop_customer_navigation import ShopCustomerChatState

_CONTROL = re.compile(r"v1:([A-Za-z0-9_-]{12}):(0|[1-9]|[12][0-9]|3[01])\Z")
VIEW_TTL = timedelta(minutes=30)
_WAIT_SECONDS = 6
_MAX_CHATS = 256
_MAX_WAITERS = 8
_MAX_STATE_BYTES = 16 * 1024
_locks: dict[tuple[str, int], tuple[asyncio.Lock, int]] = {}


class ChatBusy(RuntimeError):
    """A conversation cannot be processed safely within its queue budget."""


def envelope(state: ShopCustomerChatState) -> dict:
    """Read the known metadata version without treating legacy rows as proofs."""
    value = state.view_state
    if isinstance(value, dict) and type(value.get("version")) is int and value["version"] == 1:
        return dict(value)
    return {"version": 1}


def persist(state: ShopCustomerChatState, value: dict) -> None:
    """Replace the JSON value so the ORM detects nested changes."""
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > _MAX_STATE_BYTES:
        raise ValueError("Customer view state exceeds its storage budget")
    state.view_state = value


def active_view(state: ShopCustomerChatState) -> dict | None:
    """Return only a current, confirmed view with well-formed action slots."""
    data = envelope(state)
    view = data.get("active")
    if data.get("pending") or not isinstance(view, dict) or view.get("consumed"):
        return None
    expires = view.get("expires")
    actions = view.get("actions")
    if not (
        type(state.ui_message_id) is int and state.ui_message_id > 0
        and isinstance(expires, str)
        and isinstance(actions, list) and len(actions) <= 32
        and all(isinstance(action, str) and 1 <= len(action.encode()) <= 64 for action in actions)
    ):
        return None
    try:
        expiry = datetime.fromisoformat(expires)
    except ValueError:
        return None
    return view if expiry.tzinfo is not None and expiry > datetime.now(UTC) else None


def resolve_action(
    state: ShopCustomerChatState | None, data: str, message_id: int | None,
) -> str | None:
    """Resolve a callback only against its confirmed generation and message."""
    match = _CONTROL.fullmatch(data)
    if state is None or match is None or state.ui_message_id != message_id:
        return None
    view = active_view(state)
    if view is None or view.get("generation") != match[1]:
        return None
    index = int(match[2])
    actions = view["actions"]
    return actions[index] if index < len(actions) else None


def prepare_reply(reply: BotReply) -> tuple[BotReply, dict]:
    """Encode only the active view's bounded inline controls."""
    generation = secrets.token_urlsafe(9)
    actions: list[str] = []
    rows = []
    for row in reply.rows:
        controls = []
        for button in row:
            if len(actions) == 32:
                raise ValueError("Too many customer view actions")
            controls.append(replace(button, callback_data=f"v1:{generation}:{len(actions)}"))
            actions.append(button.callback_data)
        rows.append(tuple(controls))
    record = {
        "generation": generation,
        "actions": actions,
        "expires": (datetime.now(UTC) + VIEW_TTL).isoformat(),
        "signature": hashlib.sha256(repr(reply).encode("utf-8")).hexdigest(),
    }
    return replace(reply, rows=tuple(rows)), record


def consume(state: ShopCustomerChatState) -> None:
    """Make the confirmed controls inert before a consequential handler runs."""
    data = envelope(state)
    view = data.get("active")
    if isinstance(view, dict):
        data["active"] = {**view, "consumed": True}
        persist(state, data)


def commerce_callback(payload) -> bool:
    """Identify reserved commerce namespaces before Runtime fallback."""
    from collections.abc import Mapping

    if not isinstance(payload, Mapping):
        return False
    query = payload.get("callback_query")
    action = query.get("data") if isinstance(query, Mapping) else None
    return isinstance(action, str) and action.startswith(("v1:", "shop:", "ux:", "g:", "d:"))


@asynccontextmanager
async def _chat_slot(key: tuple[str, int]):
    """Limit queued work and preserve ordering within the receiver process."""
    slot = _locks.get(key)
    if slot is None:
        if len(_locks) >= _MAX_CHATS:
            raise ChatBusy()
        slot = (asyncio.Lock(), 0)
    lock, waiters = slot
    if waiters >= _MAX_WAITERS:
        raise ChatBusy()
    _locks[key] = (lock, waiters + 1)
    acquired = False
    try:
        try:
            async with asyncio.timeout(_WAIT_SECONDS):
                await lock.acquire()
                acquired = True
        except TimeoutError as error:
            raise ChatBusy() from error
        yield
    finally:
        if acquired:
            lock.release()
        _, waiters = _locks[key]
        if waiters == 1:
            del _locks[key]
        else:
            _locks[key] = (lock, waiters - 1)


@asynccontextmanager
async def _locked_connection(engine: AsyncEngine, key: tuple[str, int]):
    """Keep a PostgreSQL session lock across handler commits and lease handoff."""
    digest = hashlib.blake2b(f"{key[0]}:{key[1]}".encode(), digest_size=8, person=b"shop-view").digest()
    params = {"key": int.from_bytes(digest, "big", signed=True)}
    connection = None
    locked = False
    try:
        try:
            async with asyncio.timeout(_WAIT_SECONDS):
                connection = await engine.connect()
                while True:
                    locked = await connection.scalar(
                        text("SELECT pg_try_advisory_lock(:key)"), params
                    )
                    await connection.commit()
                    if locked:
                        break
                    await asyncio.sleep(0.05)
        except TimeoutError as error:
            if connection is not None:
                await connection.invalidate()
            raise ChatBusy() from error
        except BaseException:
            # Cancellation can land after PostgreSQL acquired the session lock
            # but before the driver returned the result. Do not pool that socket.
            if connection is not None:
                await connection.invalidate()
            raise
        async with AsyncSession(bind=connection, expire_on_commit=False) as db:
            yield db
    finally:
        if connection is not None:
            try:
                if locked and not connection.invalidated:
                    async with asyncio.timeout(_WAIT_SECONDS):
                        unlocked = await connection.scalar(
                            text("SELECT pg_advisory_unlock(:key)"), params
                        )
                        await connection.commit()
                    if unlocked is not True:
                        await connection.invalidate()
            except BaseException:
                await connection.invalidate()
                raise
            finally:
                await connection.close()


@asynccontextmanager
async def guarded_chat(sessions, key: tuple[str, int]):
    """Use one checked-out ORM connection, or the local SQLite test session."""
    async with _chat_slot(key):
        async with sessions() as probe:
            engine = getattr(probe, "bind", None)
            if not isinstance(engine, AsyncEngine) or engine.dialect.name != "postgresql":
                yield probe
                return
        async with _locked_connection(engine, key) as db:
            yield db
