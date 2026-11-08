"""Three-step, owner-confirmed cross-provider identity linking.

Commands run only after Telegram/Bale has authenticated the inbound message.
A short-lived bearer alone cannot link identities: the source must approve
after the other provider's account claims it.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_content import ShopIdentity
from models.shop_scope import require_bot_id, require_registry_bot
from services import shop_admin_security as security
from services.shop_store_commerce import link_confirmed_identities
from models.shop_customer_links import ShopCustomerLinkRequest
from services.shop_admin_security import clock, utc

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
LINK_LIFETIME = timedelta(minutes=10)


class LinkRejected(ValueError):
    """Safe user-facing refusal, without raw secrets or SQL content."""


async def begin(
    db: AsyncSession, *, platform: str, user_id: int,
    bot_id: str | None = None,
) -> str:
    """Start from one verified platform identity; issue a 256-bit secret."""
    bot_id = require_bot_id(bot_id)
    await require_registry_bot(db, bot_id, platform)
    identity = await db.scalar(select(ShopIdentity).where(
        ShopIdentity.bot_id == bot_id,
        ShopIdentity.platform == platform,
        ShopIdentity.platform_user_id == user_id,
    ).with_for_update())
    if identity is None:
        raise LinkRejected("ابتدا /start را اجرا کنید.")
    # Multiple independently verified bot identities may belong to one
    # StoreCustomer; an existing identity link does not grant others access.
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    now = clock()
    # Revoke prior challenges from the same source without guessing tokens.
    pending = (await db.scalars(select(ShopCustomerLinkRequest).where(
        ShopCustomerLinkRequest.source_id == identity.id,
        ShopCustomerLinkRequest.state.in_(("pending", "awaiting_confirmation")),
    ).with_for_update())).all()
    for item in pending:
        item.state = "cancelled"
    db.add(ShopCustomerLinkRequest(
        id=str(uuid4()), token_hash=digest, source_id=identity.id,
        state="pending", created_at=now,
        expires_at=now + LINK_LIFETIME,
    ))
    await db.commit()
    return token


async def _request(
    db: AsyncSession, token: str,
) -> ShopCustomerLinkRequest:
    """Resolve and lock a valid one-use challenge."""
    if not TOKEN_PATTERN.fullmatch(token):
        raise LinkRejected("کد اتصال معتبر نیست.")
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    item = await db.scalar(select(ShopCustomerLinkRequest).where(
        ShopCustomerLinkRequest.token_hash == digest,
    ).with_for_update())
    if (
        item is None or item.state in {"confirmed", "cancelled"}
        or utc(item.expires_at) <= clock()
    ):
        raise LinkRejected("درخواست اتصال منقضی، لغو یا مصرف شده است.")
    return item


async def claim(
    db: AsyncSession, *, platform: str, user_id: int, token: str,
    bot_id: str | None = None,
) -> None:
    """Prove control of the second provider and await source confirmation."""
    bot_id = require_bot_id(bot_id)
    await require_registry_bot(db, bot_id, platform)
    item = await _request(db, token)
    if item.state != "pending":
        raise LinkRejected("درخواست قبلاً ثبت شده؛ تأیید حساب اول لازم است.")
    target = await db.scalar(select(ShopIdentity).where(
        ShopIdentity.bot_id == bot_id,
        ShopIdentity.platform == platform,
        ShopIdentity.platform_user_id == user_id,
    ).with_for_update())
    source = await db.get(ShopIdentity, item.source_id)
    if (
        source is None or target is None
        or source.bot_id == target.bot_id
        or source.store_id != target.store_id
    ):
        raise LinkRejected("اتصال فقط میان دو بات یک فروشگاه مجاز است.")
    item.target_id = target.id
    item.state = "awaiting_confirmation"
    await db.commit()


async def approve(
    db: AsyncSession, *, platform: str, user_id: int, token: str,
    bot_id: str | None = None,
) -> None:
    """Require a fresh command from the initiating provider to finalize."""
    bot_id = require_bot_id(bot_id)
    await require_registry_bot(db, bot_id, platform)
    item = await _request(db, token)
    if item.state != "awaiting_confirmation" or item.target_id is None:
        raise LinkRejected("ابتدا کد را در پیام‌رسان دوم وارد کنید.")
    source = await db.scalar(select(ShopIdentity).where(
        ShopIdentity.id == item.source_id,
        ShopIdentity.bot_id == bot_id,
        ShopIdentity.platform == platform,
        ShopIdentity.platform_user_id == user_id,
    ).with_for_update())
    target = await db.scalar(select(ShopIdentity).where(
        ShopIdentity.id == item.target_id,
    ).with_for_update())
    if (
        source is None or target is None
        or source.bot_id == target.bot_id
        or source.store_id != target.store_id
    ):
        raise LinkRejected("مالکیت حساب‌های این فروشگاه تأیید نشد.")
    try:
        await link_confirmed_identities(
            db, source=source, target=target, request_id=item.id,
        )
    except security.SecurityRejected as error:
        raise LinkRejected(
            "اشتراک حساب نیازمند بررسی مالکیت یا ماندهٔ اعتبار است."
        ) from None
    item.state = "confirmed"
    await db.commit()


async def cancel(
    db: AsyncSession, *, platform: str, user_id: int, token: str,
    bot_id: str | None = None,
) -> None:
    """Allow only the first platform account to cancel a pending challenge."""
    bot_id = require_bot_id(bot_id)
    await require_registry_bot(db, bot_id, platform)
    item = await _request(db, token)
    owner = await db.get(ShopIdentity, item.source_id)
    if (
        owner is None or owner.platform != platform
        or owner.bot_id != bot_id
        or owner.platform_user_id != user_id
    ):
        raise LinkRejected("فقط حساب آغازکننده می‌تواند درخواست را لغو کند.")
    item.state = "cancelled"
    await db.commit()
