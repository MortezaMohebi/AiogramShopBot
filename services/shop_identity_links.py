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

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_content import ShopIdentity
from models.shop_scope import legacy_id
from models.shop_customer_links import (
    ShopCustomerIdentityLink, ShopCustomerLinkRequest,
)
from services.shop_admin_security import clock, utc

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
LINK_LIFETIME = timedelta(minutes=10)


class LinkRejected(ValueError):
    """Safe user-facing refusal, without raw secrets or SQL content."""


async def _linked(db: AsyncSession, identity_id: int) -> bool:
    """Deny linking an identity already associated with a different provider."""
    return await db.scalar(select(ShopCustomerIdentityLink.id).where(
        or_(
            ShopCustomerIdentityLink.source_id == identity_id,
            ShopCustomerIdentityLink.target_id == identity_id,
        )
    )) is not None


async def begin(
    db: AsyncSession, *, platform: str, user_id: int,
    bot_id: str | None = None,
) -> str:
    """Start from one verified platform identity; issue a 256-bit secret."""
    identity = await db.scalar(select(ShopIdentity).where(
        ShopIdentity.bot_id == (bot_id or legacy_id(platform)),
        ShopIdentity.platform == platform,
        ShopIdentity.platform_user_id == user_id,
    ).with_for_update())
    if identity is None:
        raise LinkRejected("ابتدا /start را اجرا کنید.")
    if await _linked(db, identity.id):
        raise LinkRejected("این حساب قبلاً به حساب پیام‌رسان دیگر متصل شده است.")
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
    item = await _request(db, token)
    if item.state != "pending":
        raise LinkRejected("درخواست قبلاً ثبت شده؛ تأیید حساب اول لازم است.")
    target = await db.scalar(select(ShopIdentity).where(
        ShopIdentity.bot_id == (bot_id or legacy_id(platform)),
        ShopIdentity.platform == platform,
        ShopIdentity.platform_user_id == user_id,
    ).with_for_update())
    source = await db.get(ShopIdentity, item.source_id)
    if source is None or target is None or source.platform == target.platform:
        raise LinkRejected("اتصال باید بین دو پیام‌رسان متفاوت انجام شود.")
    if await _linked(db, target.id) or await _linked(db, source.id):
        raise LinkRejected("یکی از حساب‌ها قبلاً به حساب دیگری متصل شده است.")
    item.target_id = target.id
    item.state = "awaiting_confirmation"
    await db.commit()


async def approve(
    db: AsyncSession, *, platform: str, user_id: int, token: str,
    bot_id: str | None = None,
) -> None:
    """Require a fresh command from the initiating provider to finalize."""
    item = await _request(db, token)
    if item.state != "awaiting_confirmation" or item.target_id is None:
        raise LinkRejected("ابتدا کد را در پیام‌رسان دوم وارد کنید.")
    source = await db.scalar(select(ShopIdentity).where(
        ShopIdentity.id == item.source_id,
        ShopIdentity.bot_id == (bot_id or legacy_id(platform)),
        ShopIdentity.platform == platform,
        ShopIdentity.platform_user_id == user_id,
    ).with_for_update())
    target = await db.scalar(select(ShopIdentity).where(
        ShopIdentity.id == item.target_id,
    ).with_for_update())
    if source is None or target is None or source.platform == target.platform:
        raise LinkRejected("مالکیت حساب تأیید نشد.")
    if await _linked(db, source.id) or await _linked(db, target.id):
        raise LinkRejected("یکی از حساب‌ها قبلاً متصل شده است.")
    db.add(ShopCustomerIdentityLink(
        source_id=source.id, target_id=target.id, approved_at=clock(),
    ))
    item.state = "confirmed"
    await db.commit()


async def cancel(
    db: AsyncSession, *, platform: str, user_id: int, token: str,
    bot_id: str | None = None,
) -> None:
    """Allow only the first platform account to cancel a pending challenge."""
    item = await _request(db, token)
    owner = await db.get(ShopIdentity, item.source_id)
    if (
        owner is None or owner.platform != platform
        or owner.bot_id != (bot_id or legacy_id(platform))
        or owner.platform_user_id != user_id
    ):
        raise LinkRejected("فقط حساب آغازکننده می‌تواند درخواست را لغو کند.")
    item.state = "cancelled"
    await db.commit()
