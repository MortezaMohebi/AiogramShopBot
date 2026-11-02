"""Read-only, platform-separated sales and engagement metrics for staff.

Stars and merchant-issued store credit are reported separately from rial
payments. No external-wallet balance, invented exchange rate or fictional
sales performance is included in these aggregates.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqladmin import BaseView, expose
from starlette.exceptions import HTTPException
from starlette.requests import Request

from dashboard.permissions import require_role
from db import session_maker
from models.shop_content import ShopIdentity, ShopOrder
from models.shop_engagement import (
    ShopCampaignDelivery, ShopReferralReward, ShopWalletAccount,
)
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
from services.shop_money import format_rials

_ALLOWED_DAYS = {7, 30, 90, 0}


class ShopAnalyticsView(BaseView):
    """Show actual shop records without mixing providers or currencies."""

    name = "گزارش فروشگاه"
    icon = "fa-solid fa-chart-line"
    category = "گزارش‌ها"

    @staticmethod
    def is_visible(request: Request) -> bool:
        """Let authorized readers open analytics, but not edit money."""
        return getattr(request.state, "shop_role", None) in (
            "superadmin", "sales", "content", "finance",
            "marketing", "viewer",
        )

    @expose("/shop-analytics", methods=["GET"])
    async def shop_analytics(self, request: Request):
        """Return real platform and currency totals within a selected window."""
        require_role(
            request, "sales", "content", "finance", "marketing", "viewer"
        )
        try:
            days = int(request.query_params.get("days", "30"))
        except ValueError:
            raise HTTPException(status_code=400, detail="بازه گزارش معتبر نیست.") from None
        if days not in _ALLOWED_DAYS:
            raise HTTPException(status_code=400, detail="بازه گزارش معتبر نیست.")
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
            if days else None
        )

        async with session_maker() as session:
            identity_query = select(
                ShopIdentity.platform, func.count(ShopIdentity.id)
            ).group_by(ShopIdentity.platform)
            order_query = select(
                ShopOrder.platform, ShopOrder.status, func.count(ShopOrder.id)
            ).group_by(ShopOrder.platform, ShopOrder.status)
            payment_query = (
                select(
                    ShopPaymentAttempt.platform,
                    ShopPaymentAttempt.provider,
                    ShopPaymentAttempt.currency,
                    ShopPaymentAttempt.status,
                    func.count(ShopPaymentAttempt.id),
                    func.coalesce(func.sum(ShopPaymentAttempt.amount), 0),
                )
                .group_by(
                    ShopPaymentAttempt.platform,
                    ShopPaymentAttempt.provider,
                    ShopPaymentAttempt.currency,
                    ShopPaymentAttempt.status,
                )
            )
            refund_query = select(
                ShopRefundCase.status, func.count(ShopRefundCase.id)
            ).group_by(ShopRefundCase.status)
            if cutoff is not None:
                identity_query = identity_query.where(
                    ShopIdentity.registered_at >= cutoff
                )
                order_query = order_query.where(
                    ShopOrder.created_at >= cutoff
                )
                payment_query = payment_query.where(
                    ShopPaymentAttempt.created_at >= cutoff
                )
                refund_query = refund_query.where(
                    ShopRefundCase.created_at >= cutoff
                )
            identities = (await session.execute(identity_query)).all()
            order_states = (await session.execute(order_query)).all()
            payments = (await session.execute(payment_query)).all()
            refunds = (await session.execute(refund_query)).all()

            # These are current all-time account/outbox states, not
            # artificially attributed to a 7/30/90-day sales window.
            wallet_total = await session.scalar(
                select(func.coalesce(
                    func.sum(ShopWalletAccount.balance_irr), 0
                ))
            )
            referral_total = await session.scalar(
                select(func.coalesce(
                    func.sum(ShopReferralReward.bonus_irr), 0
                ))
            )
            deliveries = (await session.execute(
                select(
                    ShopCampaignDelivery.status,
                    func.count(ShopCampaignDelivery.id)
                ).group_by(ShopCampaignDelivery.status)
            )).all()

        order_matrix = {
            platform: {} for platform in ("telegram", "bale")
        }
        for platform, status, qty in order_states:
            order_matrix.setdefault(platform, {})[status] = qty

        aggregates = {
            platform: {
                "provider_irr_collected": 0,
                "store_credit_redeemed": 0,
                "stars_xtr": 0,
                "payment_count": 0,
            }
            for platform in ("telegram", "bale")
        }
        for platform, provider, currency, status, count, amount in payments:
            # Refunded records remain in gross history, not net revenue.
            if status not in ("paid", "refunded"):
                continue
            stats = aggregates.setdefault(platform, {})
            stats["payment_count"] = stats.get("payment_count", 0) + count
            if currency == "XTR":
                stats["stars_xtr"] = stats.get("stars_xtr", 0) + amount
            elif provider == "store_credit":
                stats["store_credit_redeemed"] = (
                    stats.get("store_credit_redeemed", 0) + amount
                )
            elif currency == "IRR":
                stats["provider_irr_collected"] = (
                    stats.get("provider_irr_collected", 0) + amount
                )

        return await self.templates.TemplateResponse(
            request,
            "shop/shop-analytics.html",
            context={
                "days": days,
                "identities": dict(identities),
                "orders": order_matrix,
                "payments": aggregates,
                "refunds": dict(refunds),
                "wallet_total": format_rials(wallet_total or 0),
                "referral_total": format_rials(referral_total or 0),
                "delivery_status": dict(deliveries),
                "format_rials": format_rials,
            },
        )
