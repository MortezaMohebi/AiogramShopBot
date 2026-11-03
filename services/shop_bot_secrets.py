"""Server-only, purpose-isolated secret handling for multi-bot credentials.

Never put bot tokens in URLs, audit logs, API JSON responses, filenames, or
non-secret configuration tables. New credentials are staged only: Phase 1
does not hot-swap running Telegram/Bale transports or enable a draft bot.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.shop_multibot import (
    ENV_TOKEN_KEYS,
    ShopBot,
    ShopBotCredential,
    ShopBotRegistryEvent,
)
from services.shop_admin_security import SecurityRejected, clock

# HKDF-like purpose isolation: the existing 256-bit Fernet deployment key
# cannot be used directly for both MFA and independent Bot API credentials.
_DERIVATION_CONTEXT = b"aiogramshopbot:bot-token-storage:v1"
_TELEGRAM_TOKEN = re.compile(r"^[1-9][0-9]{5,19}:[A-Za-z0-9_-]{20,}$")
_ASCII_TOKEN = re.compile(r"^[\x21-\x7e]{24,512}$")


def _key_bytes() -> bytes:
    """Derive the purpose-isolated encryption/HMAC key from Deployment."""
    raw = os.environ.get("SHOP_BOT_SECRET_KEY")
    if raw:
        try:
            secret = base64.b64decode(
                raw.encode("ascii"), altchars=b"-_", validate=True,
            )
        except (ValueError, UnicodeError, binascii.Error):
            raise SecurityRejected("bot_secret_key_invalid", 503) from None
    else:
        base = os.environ.get("SHOP_SECURITY_ENCRYPTION_KEY", "")
        try:
            decoded = base64.b64decode(
                base.encode("ascii"), altchars=b"-_", validate=True,
            )
        except (ValueError, UnicodeError, binascii.Error):
            raise SecurityRejected("bot_secret_key_unavailable", 503) from None
        if len(decoded) != 32:
            raise SecurityRejected("bot_secret_key_unavailable", 503)
        secret = hmac.new(
            decoded, _DERIVATION_CONTEXT, hashlib.sha256,
        ).digest()
    if len(secret) != 32:
        raise SecurityRejected("bot_secret_key_invalid", 503)
    return secret


def _cipher() -> Fernet:
    """Construct a purpose-isolated, authenticated Fernet cipher."""
    return Fernet(base64.urlsafe_b64encode(_key_bytes()))


def fingerprint_token(platform: str, token: str) -> str:
    """HMAC a bot token for deduplication without a reversible public digest."""
    if not _valid_token(token, platform):
        raise SecurityRejected("invalid_bot_token_format", 422)
    return hmac.new(
        _key_bytes(),
        ("bot-identity:v1:" + platform + ":" + token).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _valid_token(value: str, platform: str) -> bool:
    """Reject empty, malformed and control-character credentials."""
    if not isinstance(value, str) or not _ASCII_TOKEN.fullmatch(value):
        return False
    if platform == "telegram":
        return bool(_TELEGRAM_TOKEN.fullmatch(value))
    return platform == "bale"


def encrypt_for_bot(bot_id: str, platform: str, token: str) -> str:
    """Bind an encrypted secret to the exact bot identity and provider."""
    if not _valid_token(token, platform):
        raise SecurityRejected("invalid_bot_token_format", 422)
    document = json.dumps({
        "schema": 1,
        "bot_id": bot_id,
        "platform": platform,
        "token": token,
    }, separators=(",", ":"), ensure_ascii=True)
    return _cipher().encrypt(document.encode("utf-8")).decode("ascii")


def decrypt_for_bot(
    bot_id: str, platform: str, ciphertext: str,
) -> str:
    """Fail closed when a ciphertext is copied between unrelated bot rows."""
    try:
        raw = _cipher().decrypt(ciphertext.encode("ascii"))
        data = json.loads(raw)
    except (InvalidToken, UnicodeError, TypeError, ValueError):
        raise SecurityRejected("bot_secret_unreadable", 503) from None
    if (
        not isinstance(data, dict)
        or data.get("schema") != 1
        or data.get("bot_id") != bot_id
        or data.get("platform") != platform
        or not _valid_token(data.get("token"), platform)
    ):
        raise SecurityRejected("bot_secret_binding_mismatch", 409)
    return data["token"]


def stage_bot_token(
    db: Session, *, bot_id: str, token: str, actor_id: int,
) -> ShopBotCredential:
    """Stage a new encrypted credential, without enabling the bot.

    The bot row lock serializes concurrent versions. The latest active
    credential, if any, is never modified by a failed or staged change.
    """
    bot = db.scalar(select(ShopBot).where(ShopBot.id == bot_id).with_for_update())
    if bot is None:
        raise SecurityRejected("bot_not_found", 404)
    if bot.runtime_owner == "legacy":
        raise SecurityRejected("legacy_bot_credential_locked", 409)
    if bot.status != "draft":
        raise SecurityRejected("bot_credential_stage_requires_draft", 409)
    ciphertext = encrypt_for_bot(bot.id, bot.platform, token)
    fingerprint = fingerprint_token(bot.platform, token)
    # A draft must never silently reuse the active legacy bot identity.
    previous_env = os.environ.get(ENV_TOKEN_KEYS[bot.platform], "")
    if previous_env and hmac.compare_digest(token, previous_env):
        raise SecurityRejected("duplicate_bot_credential", 409)
    duplicate = db.scalar(select(ShopBotCredential.id).where(
        ShopBotCredential.token_fingerprint == fingerprint,
        ShopBotCredential.state.in_(("staged", "active")),
    ))
    if duplicate is not None:
        raise SecurityRejected("duplicate_bot_credential", 409)
    version = int(db.scalar(
        select(func.max(ShopBotCredential.version)).where(
            ShopBotCredential.bot_id == bot.id,
        )
    ) or 0) + 1
    pending = db.scalars(
        select(ShopBotCredential).where(
            ShopBotCredential.bot_id == bot.id,
            ShopBotCredential.state == "staged",
        ).with_for_update()
    ).all()
    for old in pending:
        old.state = "revoked"
        old.revoked_at = clock()
    row = ShopBotCredential(
        id=str(uuid4()), bot_id=bot.id,
        version=version, source="encrypted", state="staged",
        ciphertext=ciphertext, token_fingerprint=fingerprint,
        created_by=actor_id,
    )
    db.add(row)
    db.add(ShopBotRegistryEvent(
        id=str(uuid4()), bot_id=bot.id, actor_id=actor_id,
        action="credential_staged", credential_version=version,
    ))
    # A superseding staged token invalidates the latest getMe timestamp,
    # while retaining the previously verified immutable provider identity
    # to reject accidental or malicious credential swaps.
    bot.verified_at = None
    bot.version += 1
    db.flush()
    return row


def revoke_staged_token(
    db: Session, *, bot_id: str, version: int, actor_id: int,
) -> None:
    """Revoke only an unused proposed secret, never the active one."""
    bot = db.scalar(select(ShopBot).where(ShopBot.id == bot_id).with_for_update())
    if bot is None:
        raise SecurityRejected("bot_not_found", 404)
    row = db.scalar(select(ShopBotCredential).where(
        ShopBotCredential.bot_id == bot.id,
        ShopBotCredential.version == version,
    ).with_for_update())
    if row is None or row.state != "staged":
        raise SecurityRejected("invalid_credential_state", 409)
    row.state = "revoked"
    row.revoked_at = clock()
    bot.version += 1
    db.add(ShopBotRegistryEvent(
        id=str(uuid4()), bot_id=bot.id, actor_id=actor_id,
        action="credential_revoked", credential_version=version,
    ))


def resolve_active_token(db: Session, *, bot_id: str) -> str:
    """Retrieve a token only for a trusted internal runtime path.

    Call this service AFTER the inbound route has authenticated the bot.
    Never call it directly from a public webhook using a client-supplied ID.
    """
    bot = db.get(ShopBot, bot_id)
    if bot is None or bot.status not in {"legacy", "active"}:
        raise SecurityRejected("bot_not_active", 409)
    if bot.credential_version is None:
        raise SecurityRejected("bot_credential_missing", 409)
    row = db.scalar(select(ShopBotCredential).where(
        ShopBotCredential.bot_id == bot.id,
        ShopBotCredential.version == bot.credential_version,
        ShopBotCredential.state == "active",
    ))
    if row is None:
        raise SecurityRejected("bot_credential_missing", 409)
    if row.source == "environment":
        if (
            bot.runtime_owner != "legacy"
            or row.environment_key != ENV_TOKEN_KEYS.get(bot.platform)
        ):
            raise SecurityRejected("bot_secret_binding_mismatch", 409)
        token = os.environ.get(row.environment_key, "")
        if not _valid_token(token, bot.platform):
            raise SecurityRejected("bot_secret_unavailable", 503)
        return token
    if row.source != "encrypted" or not row.ciphertext:
        raise SecurityRejected("bot_secret_unavailable", 503)
    return decrypt_for_bot(bot.id, bot.platform, row.ciphertext)


def credential_status(db: Session, *, bot_id: str) -> list[dict]:
    """Return opaque credential metadata without hashes or encrypted bytes."""
    entries = db.scalars(select(ShopBotCredential).where(
        ShopBotCredential.bot_id == bot_id,
    ).order_by(ShopBotCredential.version.desc()).limit(30)).all()
    return [{
        "version": row.version,
        "source": row.source,
        "state": row.state,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "has_secret": bool(row.ciphertext or row.environment_key),
        "verified_at": (
            row.verified_at.isoformat() if row.verified_at else None
        ),
        "verified_bot_id": (
            str(row.verified_bot_id) if row.verified_bot_id else None
        ),
    } for row in entries]
