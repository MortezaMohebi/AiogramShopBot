"""Bound raw Bot API input, private evidence and one-attempt Runtime sends.

Receivers supply the authenticated BotContext. Neither input nor persisted
outbound payloads can choose credentials, filesystem paths or download URLs.

Provider contracts checked 2026-11-05: https://core.telegram.org/bots/api and
https://docs.bale.ai/ (getFile, File, sendMediaGroup and keyboard types).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
import hashlib
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select

from channels.contracts import Platform
from channels.telegram import TelegramTransport
from db import session_maker
from models.shop_content import Product, ProductMedia
from models.shop_workflow_runtime import WorkflowUpload
from services import shop_admin_security as security
from services.shop_actions.context import refresh_principal
from services.shop_actions.contracts import ActionRejected
from services.shop_bot_secrets import resolve_active_token
from services.shop_multibot_client import provider_client
from services.shop_platform_capabilities import CAPABILITIES
from services.shop_runtime.contracts import FileInput, RuntimeInput, RuntimeRejected

_MAX_IDENTIFIER = 9_223_372_036_854_775_807
_FILE_ID = re.compile(r"[A-Za-z0-9_-]{1,512}\Z")
_FILE_PATH = re.compile(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)*\Z")
_COMMAND = re.compile(r"/[A-Za-z][A-Za-z0-9_]{0,31}(?:@[A-Za-z0-9_]{1,32})?(?:\s|$)")
_MIMES = frozenset({"image/png", "image/jpeg", "application/pdf"})


@dataclass(frozen=True, slots=True)
class RuntimeMedia:
    """One server-resolved private original, never an input-supplied path."""

    path: Path
    kind: str
    mime_type: str


@dataclass(frozen=True, slots=True)
class RuntimeMessage:
    """Prepared content delivered by exactly one provider send operation."""

    kind: str
    text: str
    reply_markup: dict | None = None
    media: tuple[RuntimeMedia, ...] = ()


def _identifier(value) -> int | None:
    """Read a positive bounded integer without coercing booleans or strings."""
    return value if type(value) is int and 0 < value <= _MAX_IDENTIFIER else None


def _clean_text(value, *, limit: int, empty: bool = False) -> bool:
    """Bound exact UTF-8 text without truncation or invisible control payloads."""
    if not isinstance(value, str) or not (0 if empty else 1) <= len(value) <= limit:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return not any(ord(char) < 32 and char not in "\n\r\t" for char in value)


def _file_input(raw, *, kind: str) -> FileInput | None:
    """Accept supported opaque provider metadata while deferring byte verification."""
    if not isinstance(raw, Mapping):
        return None
    file_id, size = raw.get("file_id"), raw.get("file_size")
    mime = raw.get("mime_type", "image/jpeg" if kind == "photo" else None)
    if (
        not isinstance(file_id, str)
        or _FILE_ID.fullmatch(file_id) is None
        or type(size) is not int
        or not 1 <= size <= 20_000_000
        or mime not in _MIMES
        or (kind == "photo" and mime == "application/pdf")
    ):
        return None
    return FileInput(file_id=file_id, kind=kind, size=size, mime_type=mime)


def normalize(context, payload) -> RuntimeInput | None:
    """Normalize one raw Telegram/Bale private update with its exact sender.

    Missing update IDs, ambiguous envelopes, foreign contacts, SDK aliases and
    unsupported files fail closed. File text remains empty until verification.
    """
    if not isinstance(payload, Mapping):
        return None
    update_id = payload.get("update_id")
    if type(update_id) is not int or not 0 <= update_id <= _MAX_IDENTIFIER:
        return None
    if any(
        key in payload
        for key in (
            "pre_checkout_query",
            "edited_message",
            "channel_post",
            "edited_channel_post",
        )
    ):
        return None
    callback, message = payload.get("callback_query"), payload.get("message")
    if (callback is not None) == (message is not None):
        return None
    source = callback if callback is not None else message
    if not isinstance(source, Mapping):
        return None
    if callback is not None:
        message = callback.get("message")
    if not isinstance(message, Mapping) or "successful_payment" in message:
        return None
    sender, chat = source.get("from"), message.get("chat")
    if not isinstance(sender, Mapping) or not isinstance(chat, Mapping):
        return None
    user_id, chat_id = _identifier(sender.get("id")), _identifier(chat.get("id"))
    if (
        not user_id
        or chat_id != user_id
        or chat.get("type") != "private"
        or sender.get("is_bot") is True
    ):
        return None
    try:
        platform = Platform(context.platform).value
        values = {
            "platform": platform,
            "update_id": str(update_id),
            "user_id": user_id,
            "chat_id": chat_id,
        }
        if callback is not None:
            query, data = callback.get("id"), callback.get("data")
            if (
                not _clean_text(query, limit=256)
                or not _clean_text(data, limit=64)
                or len(data.encode("utf-8")) > 64
            ):
                return None
            return RuntimeInput(**values, kind="callback", callback=data)
        content = [
            key for key in ("text", "contact", "photo", "document") if key in message
        ]
        if len(content) != 1:
            return None
        kind = content[0]
        if kind == "text":
            text = message["text"]
            if not _clean_text(text, limit=4096):
                return None
            return RuntimeInput(
                **values, kind="command" if _COMMAND.match(text) else "text", text=text
            )
        if kind == "contact":
            contact = message["contact"]
            if (
                not isinstance(contact, Mapping)
                or _identifier(contact.get("user_id")) != user_id
            ):
                return None
            phone = contact.get("phone_number")
            if not _clean_text(phone, limit=24) or not re.fullmatch(
                r"\+?[0-9]{9,15}", phone
            ):
                return None
            return RuntimeInput(
                **values, kind="contact", text=phone, contact_owner=user_id
            )
        raw = message[kind]
        if kind == "photo":
            if not isinstance(raw, list) or not 1 <= len(raw) <= 10:
                return None
            candidates = [_file_input(item, kind=kind) for item in raw]
            if any(item is None for item in candidates):
                return None
            file = max(candidates, key=lambda item: item.size)
        else:
            file = _file_input(raw, kind=kind)
        return RuntimeInput(**values, kind=kind, file=file) if file else None
    except (AttributeError, TypeError, ValueError, ValidationError):
        return None


def safe_download_path(value) -> str:
    """Reject provider paths that could address URLs, local files or traversal."""
    if (
        not isinstance(value, str)
        or len(value) > 512
        or _FILE_PATH.fullmatch(value) is None
        or any(part in {".", ".."} for part in value.split("/"))
    ):
        raise RuntimeRejected("runtime_upload_path_invalid")
    return value


class _BoundedBytes(BytesIO):
    """Stop provider streaming before the allocated evidence budget is exceeded."""

    def __init__(self, maximum: int):
        """Bind the exact declared, platform-capped byte budget."""
        super().__init__()
        self.maximum = maximum

    def write(self, value):
        """Reject excess bytes before growing the backing memory buffer."""
        if self.tell() + len(value) > self.maximum:
            raise RuntimeRejected("runtime_upload_size_invalid")
        return super().write(value)


async def _download(context, event, client) -> bytes:
    """Fetch actual bytes through the authenticated Bot's existing provider session."""
    maximum = min(event.file.size, CAPABILITIES[event.platform]["download_bytes"])
    if context.platform == Platform.BALE:
        return await client.download_runtime(event.file.file_id, max_bytes=maximum)
    bot = client.bot if isinstance(client, TelegramTransport) else client
    remote = await bot.get_file(event.file.file_id)
    remote_size = getattr(remote, "file_size", None)
    remote_id = getattr(remote, "file_id", None)
    if remote_id not in (None, event.file.file_id) or (
        remote_size is not None
        and (type(remote_size) is not int or remote_size != event.file.size)
    ):
        raise RuntimeRejected("runtime_upload_size_invalid")
    path = safe_download_path(getattr(remote, "file_path", None))
    with _BoundedBytes(maximum) as destination:
        await bot.download_file(
            path, destination=destination, timeout=30, chunk_size=64 * 1024
        )
        return destination.getvalue()


def _signature(content: bytes) -> str | None:
    """Identify supported evidence from bytes rather than extensions or claimed MIME."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    return None


async def verify_upload(db, context, event, principal, *, client=None) -> str:
    """Download and verify private evidence, stage its UUID, and never commit.

    The coordinator calls this only after committing its durable Inbox row.
    Raw bytes are inspected in bounded memory and discarded; the private row
    retains the Bot-scoped provider handle and its verified digest.
    """
    if (
        event.file is None
        or event.kind not in {"photo", "document"}
        or event.file.kind != event.kind
        or event.platform != context.platform.value
        or principal.actor_kind != "customer"
        or principal.customer_id is None
        or principal.store_id != context.store_id
        or principal.bot_id != context.bot_id
        or principal.platform != event.platform
        or principal.platform_user_id != event.user_id
        or event.chat_id != event.user_id
    ):
        raise RuntimeRejected("runtime_upload_owner_invalid", 403)
    try:
        await refresh_principal(db, principal)
    except ActionRejected:
        raise RuntimeRejected("runtime_upload_owner_invalid", 403) from None
    try:
        if client is None:
            token = await db.run_sync(
                lambda sync: resolve_active_token(sync, bot_id=context.bot_id)
            )
            async with provider_client(
                event.platform, token, bot_id=context.bot_id
            ) as provider:
                content = await _download(context, event, provider)
        else:
            client_bot = getattr(client, "bot_id", None)
            if client_bot is not None and client_bot != context.bot_id:
                raise RuntimeRejected("runtime_upload_owner_invalid", 403)
            provider_bot = (
                client.bot if isinstance(client, TelegramTransport) else client
            )
            provider_id = getattr(provider_bot, "id", None)
            if (
                context.provider_bot_id is not None
                and type(provider_id) is int
                and provider_id != context.provider_bot_id
            ):
                raise RuntimeRejected("runtime_upload_owner_invalid", 403)
            content = await _download(context, event, client)
    except RuntimeRejected:
        raise
    except Exception:
        # SDK exception strings and tracebacks can include credential URLs.
        raise RuntimeRejected("runtime_upload_download_failed") from None
    mime = _signature(content) if isinstance(content, bytes) else None
    if (
        not isinstance(content, bytes)
        or len(content) != event.file.size
        or not 1 <= len(content) <= CAPABILITIES[event.platform]["download_bytes"]
        or mime is None
        or (event.kind == "document" and mime != event.file.mime_type)
        or (event.kind == "photo" and mime not in {"image/png", "image/jpeg"})
    ):
        raise RuntimeRejected("runtime_upload_content_invalid")
    upload = WorkflowUpload(
        id=str(uuid4()),
        store_id=context.store_id,
        bot_id=context.bot_id,
        customer_id=principal.customer_id,
        user_id=event.user_id,
        kind=event.kind,
        file_id=event.file.file_id,
        size=len(content),
        mime_type=mime,
        sha256=hashlib.sha256(content).hexdigest(),
        verified=True,
        expires_at=security.clock() + timedelta(hours=24),
    )
    db.add(upload)
    await db.flush()
    return upload.id


def _markup(payload) -> dict | None:
    """Render real contact/reply controls or bounded inline URL/callback buttons."""
    keyboard = payload.get("keyboard", "inline")
    if (
        keyboard not in {"inline", "reply"}
        or type(payload.get("request_contact", False)) is not bool
    ):
        raise RuntimeRejected("runtime_keyboard_invalid")
    buttons = payload.get("buttons", [])
    if not isinstance(buttons, list) or len(buttons) > 100:
        raise RuntimeRejected("runtime_buttons_invalid")
    rows, reply_labels = {}, set()
    for button in buttons:
        if not isinstance(button, Mapping) or not _clean_text(
            button.get("label"), limit=64
        ):
            raise RuntimeRejected("runtime_buttons_invalid")
        row = button.get("row", 0)
        if type(row) is not int or not 0 <= row <= 19:
            raise RuntimeRejected("runtime_buttons_invalid")
        entry = {"text": button["label"]}
        callback, url = button.get("callback_data"), button.get("url")
        if bool(callback) == bool(url):
            raise RuntimeRejected("runtime_buttons_invalid")
        if callback:
            if (
                not _clean_text(callback, limit=64)
                or not 1 <= len(callback.encode("utf-8")) <= 64
            ):
                raise RuntimeRejected("runtime_callback_limit")
            entry["callback_data"] = callback
        else:
            try:
                parsed = urlsplit(url)
                if (
                    not _clean_text(url, limit=2048)
                    or parsed.scheme != "https"
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                ):
                    raise ValueError
            except (ValueError, TypeError):
                raise RuntimeRejected("runtime_button_url_invalid") from None
            entry["url"] = url
        if keyboard == "reply":
            if url:
                raise RuntimeRejected("runtime_reply_button_unsupported")
            command = button.get("command")
            if command is not None and command not in {
                "/back",
                "/skip",
                "/cancel",
                "/menu",
            }:
                raise RuntimeRejected("runtime_reply_button_unsupported")
            label = command or button["label"]
            if label in reply_labels:
                raise RuntimeRejected("runtime_reply_button_ambiguous")
            reply_labels.add(label)
            entry = {"text": label}
        rows.setdefault(row, []).append(entry)
        if len(rows[row]) > 8:
            raise RuntimeRejected("runtime_buttons_invalid")
    if payload.get("request_contact") is True:
        # Reply controls submit literal commands; they never claim to send an
        # opaque callback capability through an unsupported contact button.
        commands = [button.get("command") for button in buttons]
        if any(
            button.get("url") or command not in {"/back", "/skip", "/cancel", "/menu"}
            for button, command in zip(buttons, commands)
        ):
            raise RuntimeRejected("runtime_contact_keyboard_invalid")
        return {
            "keyboard": [[{"text": "📱 اشتراک شمارهٔ تماس", "request_contact": True}]]
            + [
                [{"text": command}]
                for command in ("/back", "/skip", "/cancel")
                if command in commands or command == "/cancel"
            ],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }
    if keyboard == "reply":
        if not rows:
            raise RuntimeRejected("runtime_reply_keyboard_empty")
        return {
            "keyboard": [rows[row] for row in sorted(rows)],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }
    return {"inline_keyboard": [rows[row] for row in sorted(rows)]} if rows else None


async def _prepare(db, context, payload) -> RuntimeMessage:
    """Resolve all render/media validation before any physical provider call."""
    if not isinstance(payload, Mapping) or any(
        key in payload for key in ("token", "bot_token", "url", "path", "file_id")
    ):
        raise RuntimeRejected("runtime_payload_invalid")
    kind, text = payload.get("kind"), payload.get("text", "")
    if kind not in {"text", "photo", "video", "document", "media_group"}:
        raise RuntimeRejected("runtime_media_kind_invalid")
    if not _clean_text(
        text, limit=4096 if kind == "text" else 1024, empty=kind != "text"
    ):
        raise RuntimeRejected("runtime_text_limit")
    markup = _markup(payload)
    if kind == "text":
        if payload.get("media_ids"):
            raise RuntimeRejected("runtime_media_invalid")
        return RuntimeMessage(kind=kind, text=text, reply_markup=markup)
    ids = payload.get("media_ids")
    if (
        not isinstance(ids, list)
        or not all(type(key) is int and key > 0 for key in ids)
        or not (2 <= len(ids) <= 10 if kind == "media_group" else len(ids) == 1)
    ):
        raise RuntimeRejected("runtime_media_invalid")
    if kind == "media_group" and markup:
        raise RuntimeRejected("runtime_album_keyboard_unsupported")
    rows = (
        await db.scalars(
            select(ProductMedia)
            .join(Product, Product.id == ProductMedia.product_id)
            .where(
                Product.store_id == context.store_id,
                ProductMedia.id.in_(ids),
            )
        )
    ).all()
    indexed = {row.id: row for row in rows}
    if set(indexed) != set(ids):
        raise RuntimeRejected("runtime_media_unavailable")
    from dashboard.media_storage import safe_media_path
    import config

    prepared = []
    for key in ids:
        row = indexed[key]
        if row.kind not in {"photo", "video", "document"} or (
            kind != "media_group" and row.kind != kind
        ):
            raise RuntimeRejected("runtime_media_kind_invalid")
        try:
            path = safe_media_path(config.SHOP_MEDIA_ROOT, row.storage_key)
            size = path.stat().st_size
        except (OSError, ValueError):
            raise RuntimeRejected("runtime_media_unavailable") from None
        limit = CAPABILITIES[context.platform.value][
            "photo_bytes" if row.kind == "photo" else "file_bytes"
        ]
        if not path.is_file() or not 0 < size <= limit or size != row.size_bytes:
            raise RuntimeRejected("runtime_media_size_invalid")
        prepared.append(RuntimeMedia(path=path, kind=row.kind, mime_type=row.mime_type))
    if (
        kind == "media_group"
        and any(item.kind == "document" for item in prepared)
        and any(item.kind != "document" for item in prepared)
    ):
        raise RuntimeRejected("runtime_album_media_incompatible")
    return RuntimeMessage(
        kind=kind, text=text, reply_markup=markup, media=tuple(prepared)
    )


async def deliver(context, chat_id: int, payload) -> list[str]:
    """Make one physical provider send and return all confirmed message IDs.

    Known pre-send validation failures are safe rejections. Unknown provider
    exceptions are sanitized and left uncertain for the outbox worker.
    """
    from services.shop_runtime import sessions
    from services.shop_runtime.contracts import DeliveryRejected

    try:
        if _identifier(chat_id) is None:
            raise RuntimeRejected("runtime_chat_invalid")
        async with session_maker() as db:
            if not await sessions.enabled(db, context):
                raise RuntimeRejected("runtime_disabled")
            prepared = await _prepare(db, context, payload)
            token = await db.run_sync(
                lambda sync: resolve_active_token(sync, bot_id=context.bot_id)
            )
    except RuntimeRejected as error:
        raise DeliveryRejected(error.code, retryable=False) from None
    except Exception:
        raise DeliveryRejected(
            "runtime_delivery_unavailable", retryable=False
        ) from None
    try:
        async with provider_client(
            context.platform.value, token, bot_id=context.bot_id
        ) as provider:
            transport = (
                TelegramTransport(provider, bot_id=context.bot_id)
                if context.platform == Platform.TELEGRAM
                else provider
            )
            return await transport.send_runtime(chat_id, prepared)
    except DeliveryRejected:
        raise
    except Exception:
        raise RuntimeError("runtime_delivery_uncertain") from None
