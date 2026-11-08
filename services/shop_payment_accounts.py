"""Versioned, store-owned native payment connection management.

Only documented platform rails are accepted; Telegram Stars needs no provider
token, whereas Bale Wallet and Telegram fiat require purpose-bound encrypted
credentials. A connection never becomes available to a bot without a separate
explicit, enabled assignment.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_multibot import ShopBot, ShopStore
from models.shop_store_commerce import ShopBotPaymentAccess, ShopPaymentAccount
from services import shop_admin_security as security
from services.shop_bot_secrets import _key_bytes

_VALID_TOKEN = re.compile(r"^[\x21-\x7e]{20,512}$")
_PURPOSE = b"aiogramshopbot:payment-account-storage:v1"
_SUPPORTED = {
    ("telegram", "telegram_fiat"): "IRR",
    ("telegram", "telegram_stars"): "XTR",
    ("bale", "bale_wallet"): "IRR",
}


def _cipher() -> Fernet:
    """Derive separate payment credential protection from the bot key."""
    digest = hmac.new(_key_bytes(), _PURPOSE, hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt(
    *, account_id: str, platform: str, rail_type: str, token: str,
) -> str:
    """Authenticate the immutable account and provider against token swaps."""
    if not isinstance(token, str) or not _VALID_TOKEN.fullmatch(token):
        raise security.SecurityRejected("payment_token_invalid", 422)
    data = json.dumps({
        "schema": 1, "account_id": account_id,
        "platform": platform, "rail_type": rail_type, "token": token,
    }, ensure_ascii=True, separators=(",", ":"))
    return _cipher().encrypt(data.encode("ascii")).decode("ascii")


def decrypt_provider_token(account: ShopPaymentAccount) -> str:
    """Return the private key only to the trusted invoice dispatcher."""
    if account.rail_type == "telegram_stars":
        return ""
    try:
        data = json.loads(_cipher().decrypt(
            account.credential_ciphertext.encode("ascii"),
        ))
    except (InvalidToken, ValueError, TypeError, UnicodeError, AttributeError):
        raise security.SecurityRejected("payment_token_unavailable", 503) from None
    if (
        not isinstance(data, dict)
        or data.get("schema") != 1
        or data.get("account_id") != account.id
        or data.get("platform") != account.platform
        or data.get("rail_type") != account.rail_type
        or not isinstance(data.get("token"), str)
        or not _VALID_TOKEN.fullmatch(data["token"])
    ):
        raise security.SecurityRejected("payment_token_binding_mismatch", 409)
    return data["token"]


def safe_account(account: ShopPaymentAccount) -> dict:
    """Return only merchant-editable and audit-safe metadata."""
    return {
        "id": account.id, "store_id": account.store_id,
        "platform": account.platform, "rail_type": account.rail_type,
        "currency": account.currency, "name": account.name,
        "state": account.state, "version": account.version,
        "has_credential": bool(account.credential_ciphertext),
    }


async def list_accounts(
    db: AsyncSession, *, store_id: str,
) -> dict:
    """Expose all payment providers for one specific Store only."""
    records = (await db.scalars(select(ShopPaymentAccount).where(
        ShopPaymentAccount.store_id == store_id,
    ).order_by(ShopPaymentAccount.platform, ShopPaymentAccount.name))).all()
    return {"store_id": store_id, "items": [safe_account(a) for a in records]}


async def create_account(
    db: AsyncSession, *, store_id: str, platform: str,
    rail_type: str, name: str, token: str | None, actor_id: int,
) -> dict:
    """Create a disabled-by-default account and never start a live payment."""
    if (
        _SUPPORTED.get((platform, rail_type)) is None
        or not isinstance(name, str) or not 1 <= len(name.strip()) <= 100
    ):
        raise security.SecurityRejected("payment_account_invalid", 422)
    store = await db.get(ShopStore, store_id)
    if store is None:
        raise security.SecurityRejected("store_not_found", 404)
    if rail_type == "telegram_stars":
        if token:
            raise security.SecurityRejected("payment_token_not_supported", 422)
    elif not token or not _VALID_TOKEN.fullmatch(token):
        raise security.SecurityRejected("payment_token_invalid", 422)
    account_id = str(uuid4())
    account = ShopPaymentAccount(
        id=account_id, store_id=store_id, platform=platform,
        rail_type=rail_type, name=name.strip(),
        currency=_SUPPORTED[(platform, rail_type)], state="draft",
        credential_ciphertext=(
            _encrypt(
                account_id=account_id, platform=platform,
                rail_type=rail_type, token=token,
            ) if token else None
        ), updated_by=actor_id,
    )
    db.add(account)
    await db.commit()
    return safe_account(account)


async def change_account_state(
    db: AsyncSession, *, account_id: str, expected_version: int,
    state: str, actor_id: int,
) -> dict:
    """Toggle an account after explicit operator MFA without touching receipts."""
    if state not in {"active", "disabled"}:
        raise security.SecurityRejected("payment_account_invalid", 422)
    row = await db.scalar(select(ShopPaymentAccount).where(
        ShopPaymentAccount.id == account_id,
    ).with_for_update())
    if row is None:
        raise security.SecurityRejected("payment_account_not_found", 404)
    if row.version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)
    if row.state == state:
        raise security.SecurityRejected("bot_state_unchanged", 409)
    row.state = state
    row.version += 1
    row.updated_by = actor_id
    await db.commit()
    return safe_account(row)


async def grant_bot_access(
    db: AsyncSession, *, bot_id: str, account_id: str,
    enabled: bool, priority: int,
) -> dict:
    """Authorize one payment account for one bot in the SAME Store."""
    if type(enabled) is not bool or type(priority) is not int or not (
        1 <= priority <= 1000
    ):
        raise security.SecurityRejected("payment_access_invalid", 422)
    bot = await db.get(ShopBot, bot_id)
    account = await db.get(ShopPaymentAccount, account_id)
    if (
        bot is None or account is None
        or bot.runtime_owner != "registry"
        or bot.store_id != account.store_id
        or bot.platform != account.platform
    ):
        raise security.SecurityRejected("payment_access_store_mismatch", 409)
    if enabled and account.state != "active":
        raise security.SecurityRejected("payment_account_not_active", 409)
    grant = await db.get(
        ShopBotPaymentAccess, (bot_id, account_id),
        with_for_update=True,
    )
    if grant is None:
        grant = ShopBotPaymentAccess(
            bot_id=bot_id, payment_account_id=account_id,
        )
        db.add(grant)
    grant.enabled = enabled
    grant.priority = priority
    await db.commit()
    return {
        "ok": True, "bot_id": bot_id,
        "account_id": account_id, "enabled": enabled,
        "priority": priority,
    }


async def list_bot_accounts(
    db: AsyncSession, *, bot_id: str,
) -> dict:
    """Show safe account metadata and grants, never plaintext provider tokens."""
    bot = await db.get(ShopBot, bot_id)
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    accounts = (await db.scalars(select(ShopPaymentAccount).where(
        ShopPaymentAccount.store_id == bot.store_id,
        ShopPaymentAccount.platform == bot.platform,
    ).order_by(ShopPaymentAccount.name))).all()
    grants = (await db.scalars(select(ShopBotPaymentAccess).where(
        ShopBotPaymentAccess.bot_id == bot_id,
    ))).all()
    enabled = {grant.payment_account_id: grant for grant in grants}
    return {
        "bot_id": bot_id,
        "items": [{
            **safe_account(item),
            "granted": (
                enabled[item.id].enabled if item.id in enabled else False
            ),
            "priority": (
                enabled[item.id].priority if item.id in enabled else 100
            ),
        } for item in accounts],
    }
