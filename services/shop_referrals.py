"""One-time referral attribution and optional merchant-funded IRR rewards.

Referrals never credit external Bale balances or the legacy crypto wallet.
Policy defaults to disabled. Only a verified first paid IRR transaction can
earn credit, and the ledger and reward record commit in one transaction.
"""

from __future__ import annotations

import re
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import Platform
from models.shop_content import ShopOrder
from models.shop_engagement import (
    ShopReferralAttribution,
    ShopReferralPolicy,
    ShopReferralProfile,
    ShopReferralReward,
)
from services.shop_wallet import ShopWalletService


_CODE = re.compile(r"R-[A-F0-9]{12}\Z")


class ReferralRejected(ValueError):
    """An invalid referral action has no financial side effects."""


class ShopReferralService:
    """Provide equal invitation and reward rules for both messaging platforms."""

    @staticmethod
    async def code(
        session: AsyncSession, platform: Platform, user_id: int
    ) -> str:
        """Return or create an owner's unique referral code on demand."""
        identity = await ShopWalletService.find_identity(
            session, platform, user_id
        )
        if identity is None:
            raise ReferralRejected("ابتدا ربات فروشگاه را با /start آغاز کنید.")
        profile = await session.scalar(
            select(ShopReferralProfile).where(
                ShopReferralProfile.identity_id == identity.id
            )
        )
        if profile is not None:
            return profile.code

        # Collision probability is tiny and DB uniqueness enforces correctness.
        code = "R-" + secrets.token_hex(6).upper()
        session.add(
            ShopReferralProfile(identity_id=identity.id, code=code)
        )
        await session.commit()
        return code

    @staticmethod
    async def claim(
        session: AsyncSession,
        *,
        platform: Platform,
        user_id: int,
        code: str,
    ) -> str:
        """Accept only an unambiguous first-purchase, same-platform invite."""
        normalized = code.strip().upper()
        if _CODE.fullmatch(normalized) is None:
            raise ReferralRejected("کد معرفی معتبر نیست.")
        referee = await ShopWalletService.find_identity(
            session, platform, user_id
        )
        if referee is None:
            raise ReferralRejected("ابتدا با /start ثبت‌نام کنید.")
        existing = await session.scalar(
            select(ShopReferralAttribution).where(
                ShopReferralAttribution.referee_identity_id == referee.id
            )
        )
        if existing:
            if existing.code_snapshot == normalized:
                return "این کد معرفی قبلاً برای حساب شما ثبت شده است."
            raise ReferralRejected("معرف حساب شما قبلاً تعیین شده است.")

        sponsor = await session.scalar(
            select(ShopReferralProfile).where(
                ShopReferralProfile.code == normalized
            )
        )
        if sponsor is None or sponsor.identity_id == referee.id:
            raise ReferralRejected("کد معرفی نامعتبر است یا متعلق به خود شماست.")
        # Without verified cross-platform account linking, block a user from
        # collecting referral credit by inviting their own alternate app ID.
        inviter = await session.get(type(referee), sponsor.identity_id)
        if inviter is None or inviter.platform != referee.platform:
            raise ReferralRejected(
                "کد معرفی باید متعلق به همین پیام‌رسان باشد."
            )
        previous_purchase = await session.scalar(
            select(ShopOrder.id).where(
                ShopOrder.platform == platform.value,
                ShopOrder.platform_user_id == user_id,
                ShopOrder.status.in_(
                    ("paid", "paid_unfulfilled", "refunded")
                ),
            ).limit(1)
        )
        if previous_purchase is not None:
            raise ReferralRejected(
                "معرف تنها پیش از اولین خرید موفق قابل ثبت است."
            )
        session.add(
            ShopReferralAttribution(
                referee_identity_id=referee.id,
                inviter_identity_id=sponsor.identity_id,
                code_snapshot=normalized,
            )
        )
        await session.commit()
        return "✅ کد معرفی برای اولین خرید شما ثبت شد."

    @staticmethod
    async def award_for_paid_order(
        session: AsyncSession, order_id: int
    ) -> int:
        """Award sponsor store-credit once after external IRR payment settles.

        This should run *after* payment settlement commits; a referral failure
        must never roll back an already received external payment.
        """
        order = await session.scalar(
            select(ShopOrder).where(ShopOrder.id == order_id)
        )
        if (
            order is None
            or order.status != "paid"
            or order.provider not in ("bale_wallet", "telegram_fiat")
            or order.payment_currency != "IRR"
        ):
            return 0
        policy = await session.get(ShopReferralPolicy, 1)
        if (
            policy is None or not policy.is_enabled
            or policy.percent <= 0 or policy.max_bonus_irr <= 0
            or order.total_irr < policy.min_order_irr
        ):
            return 0

        referee = await ShopWalletService.find_identity(
            session, Platform(order.platform), order.platform_user_id
        )
        if referee is None:
            return 0
        attribution = await session.scalar(
            select(ShopReferralAttribution).where(
                ShopReferralAttribution.referee_identity_id == referee.id
            ).with_for_update()
        )
        if attribution is None:
            return 0
        if await session.scalar(
            select(ShopReferralReward.id).where(
                ShopReferralReward.referee_identity_id == referee.id
            )
        ) is not None:
            return 0

        # Promotional rewards apply only to the *first* paid purchase. A
        # previously refunded order is also treated as an earlier purchase.
        previous = await session.scalar(
            select(ShopOrder.id).where(
                ShopOrder.platform == order.platform,
                ShopOrder.platform_user_id == order.platform_user_id,
                ShopOrder.id != order.id,
                ShopOrder.status.in_(
                    ("paid", "paid_unfulfilled", "refunded")
                ),
            ).limit(1)
        )
        if previous is not None:
            return 0
        bonus = min(
            order.total_irr * policy.percent // 100,
            policy.max_bonus_irr,
        )
        if bonus < 1:
            return 0
        entry, changed = await ShopWalletService.apply(
            session,
            identity_id=attribution.inviter_identity_id,
            delta_irr=bonus,
            operation_key=f"referral-paid-order:{order.id}",
            reason=f"Referral reward on order #{order.id}",
            actor="system:referrals",
        )
        if not changed:
            return 0
        session.add(
            ShopReferralReward(
                referee_identity_id=referee.id,
                inviter_identity_id=attribution.inviter_identity_id,
                order_id=order.id,
                bonus_irr=bonus,
                wallet_entry_id=entry.id,
            )
        )
        await session.commit()
        return bonus
