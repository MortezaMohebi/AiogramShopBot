"""Typed messages exchanged by the shop core and messaging adapters.

The contract intentionally contains no Telegram or Bale SDK objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class Platform(StrEnum):
    """Supported messaging platforms."""

    TELEGRAM = "telegram"
    BALE = "bale"


@dataclass(frozen=True, slots=True)
class InlineAction:
    """A single inline keyboard action usable on both platforms."""

    label: str
    callback_data: str

    def __post_init__(self) -> None:
        """Reject invalid callback payloads before API dispatch."""
        if not self.label.strip() or len(self.label) > 64:
            raise ValueError("Button label must contain 1–64 characters.")
        if not 1 <= len(self.callback_data.encode("utf-8")) <= 64:
            raise ValueError("Callback data must contain 1–64 UTF-8 bytes.")


@dataclass(frozen=True, slots=True)
class MediaAttachment:
    """Original privately stored media delivered by either messaging adapter."""

    storage_key: str
    kind: str
    mime_type: str
    caption: str = ""


@dataclass(frozen=True, slots=True)
class BotReply:
    """Plain text and an optional inline keyboard."""

    text: str
    rows: tuple[tuple[InlineAction, ...], ...] = ()
    attachments: tuple[MediaAttachment, ...] = ()
    # Preview is the replaceable card image; attachments are persistent
    # on-demand messages and must never be deleted during navigation.
    preview: MediaAttachment | None = None
    # Official Telegram/Bale ReplyKeyboard request_contact, never an inline button.
    request_contact: bool = False
    show_main_keyboard: bool = False

    def __post_init__(self) -> None:
        """Validate common limits before handing data to an adapter."""
        if not 1 <= len(self.text) <= 4096:
            raise ValueError("Bot message must contain 1–4096 characters.")
        if self.request_contact and self.rows:
            raise ValueError("Contact keyboard cannot mix with inline actions.")


@dataclass(frozen=True, slots=True)
class InboundEvent:
    """Incoming user message or callback normalized across platforms."""

    platform: Platform
    chat_id: int
    user_id: int
    text: str | None = None
    callback_data: str | None = None
    callback_query_id: str | None = None
    message_id: int | None = None
    contact_user_id: int | None = None
    contact_phone: str | None = None

    @property
    def is_callback(self) -> bool:
        """Return whether this update originated from an inline button."""
        return self.callback_data is not None


def _user_id(obj: object) -> int | None:
    """Read an unsigned platform user ID without accepting booleans."""
    if not isinstance(obj, Mapping):
        return None
    value = obj.get("id")
    return value if type(value) is int and value > 0 else None


def _private_chat_id(obj: object) -> int | None:
    """Accept only private chat events, not groups and channels."""
    if not isinstance(obj, Mapping) or obj.get("type") != "private":
        return None
    value = obj.get("id")
    return value if type(value) is int and value > 0 else None


def normalize_update(
    platform: Platform, payload: Mapping[str, object]
) -> InboundEvent | None:
    """Decode common Bot API fields into a platform-neutral event.

    Telegram and Bale both use `message` and `callback_query` structures.
    Unknown updates are ignored instead of being treated as messages.
    """
    callback = payload.get("callback_query")
    if isinstance(callback, Mapping):
        user_id = _user_id(callback.get("from"))
        message = callback.get("message")
        chat_id = (
            _private_chat_id(message.get("chat"))
            if isinstance(message, Mapping)
            else None
        )
        data, query_id = callback.get("data"), callback.get("id")
        if (
            user_id is not None
            and chat_id is not None
            and isinstance(data, str)
            and 1 <= len(data.encode("utf-8")) <= 64
            and isinstance(query_id, str)
            and query_id
        ):
            return InboundEvent(
                platform=platform,
                chat_id=chat_id,
                user_id=user_id,
                callback_data=data,
                callback_query_id=query_id,
                message_id=(
                    message.get("message_id")
                    if type(message.get("message_id")) is int else None
                ),
            )
        return None

    message = payload.get("message")
    if not isinstance(message, Mapping):
        return None
    user_id = _user_id(message.get("from"))
    chat_id = _private_chat_id(message.get("chat"))
    body = message.get("text")
    if user_id is None or chat_id is None:
        return None
    contact = message.get("contact")
    if isinstance(contact, Mapping) and not isinstance(body, str):
        phone, contact_id = contact.get("phone_number"), contact.get("user_id")
        if not isinstance(phone, str) or not 5 <= len(phone) <= 24:
            return None
        return InboundEvent(
            platform=platform, chat_id=chat_id, user_id=user_id,
            contact_phone=phone,
            contact_user_id=contact_id if type(contact_id) is int else None,
        )
    if not isinstance(body, str) or not body or len(body) > 4096:
        return None
    return InboundEvent(
        platform=platform, chat_id=chat_id, user_id=user_id, text=body
    )
