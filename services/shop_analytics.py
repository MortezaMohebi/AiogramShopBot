"""Read-only cross-platform reporting for the independent shop schema.

Money is grouped by actual payment currency and method; never sum nominal
rial product prices with Telegram Stars or pretend promotional store credit
is newly received external cash.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_content import ShopIdentity, ShopOrder
from models.shop_checkout import ShopOrderLine
from models.shop_engagement import (
    ShopCampaign, ShopCampaignDelivery, ShopWalletAccount, ShopWalletEntry,
)
from services.shop_store_context import current_context
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase


_ALLOWED_PERIODS = frozenset({0, 7, 30, 90, 365})
_EXTERNAL_IRR_PROVIDERS = ("bale_wallet", "telegram_fiat")
_REVENUE_STATUSES = ("paid",)


@dataclass(frozen=True, slots=True)
class ChannelSummary:
    """Counts and financial totals separated by channel and real currency."""

    platform: str
    customers: int
    opted_in: int
    orders: int
    paid_orders: int
    review_orders: int
    paid_unfulfilled: int
    refunded: int
    gross_paid_irr: int
    store_credit_irr: int
    telegram_stars_xtr: int


@dataclass(frozen=True, slots=True)
class CampaignSummary:
    """Campaign outbox states returned without exposing customer identifiers."""

    queued: int
    sent: int
    unknown: int
    skipped: int


@dataclass(frozen=True, slots=True)
class ProductSummary:
    """Best-selling paid item and count; no fake product statistics."""

    product_id: int
    name: str
    quantity: int


@dataclass(frozen=True, slots=True)
class ShopAnalytics:
    """Report data for the administrator's selected UTC time window."""

    days: int
    since: datetime | None
    channels: tuple[ChannelSummary, ...]
    campaigns: CampaignSummary
    open_refund_cases: int
    credit_issued_irr: int
    credit_spent_irr: int
    top_products: tuple[ProductSummary, ...]


async def build_shop_analytics(
    session: AsyncSession, *, days: int = 30
) -> ShopAnalytics:
    """Aggregate only authoritative DB rows without platform API requests.

    Order counts use the order's creation timestamp. Paid revenue and Stars
    use the payment's settlement timestamp. Reports intentionally exclude
    legacy Telegram `Buy` and `Deposit` rows until migration is reviewed.
    """
    if type(days) is not int or days not in _ALLOWED_PERIODS:
        raise ValueError("Reporting period must be 0, 7, 30, 90 or 365 days.")
    since = (
        datetime.now(timezone.utc) - timedelta(days=days)
        if days else None
    )
    ctx = current_context()
    selected = ctx.active_store_ids if ctx is not None else None

    identities_clause = (
        [ShopIdentity.registered_at >= since] if since else []
    )
    if selected is not None:
        identities_clause.append(ShopIdentity.store_id.in_(selected))
    identities = await session.execute(
        select(
            ShopIdentity.platform,
            func.count(ShopIdentity.id),
            func.coalesce(
                func.sum(
                    case(
                        (ShopIdentity.allow_announcements.is_(True), 1),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .where(*identities_clause)
        .group_by(ShopIdentity.platform)
    )
    customer_counts = {
        platform: (int(total), int(opted_in))
        for platform, total, opted_in in identities.all()
    }

    order_clause = [ShopOrder.created_at >= since] if since else []
    if selected is not None:
        order_clause.append(ShopOrder.store_id.in_(selected))
    order_results = await session.execute(
        select(
            ShopOrder.platform, ShopOrder.status, func.count(ShopOrder.id)
        )
        .where(*order_clause)
        .group_by(ShopOrder.platform, ShopOrder.status)
    )
    order_counts: dict[str, dict[str, int]] = {
        "telegram": {}, "bale": {},
    }
    for platform, status, count in order_results.all():
        order_counts.setdefault(platform, {})[status] = int(count)

    revenue_clause = [ShopOrder.paid_at >= since] if since else []
    if selected is not None:
        revenue_clause.append(ShopOrder.store_id.in_(selected))
    payment_rows = await session.execute(
        select(
            ShopOrder.platform,
            ShopPaymentAttempt.provider,
            ShopPaymentAttempt.currency,
            func.coalesce(func.sum(ShopPaymentAttempt.amount), 0),
            func.coalesce(func.sum(ShopOrder.total_irr), 0),
        )
        .join(ShopOrder, ShopOrder.id == ShopPaymentAttempt.order_id)
        .where(
            ShopOrder.status.in_(_REVENUE_STATUSES),
            ShopPaymentAttempt.status == "paid",
            *revenue_clause,
        )
        .group_by(
            ShopOrder.platform,
            ShopPaymentAttempt.provider,
            ShopPaymentAttempt.currency,
        )
    )
    totals: dict[str, dict[str, int]] = {
        "telegram": {"external": 0, "credit": 0, "stars": 0},
        "bale": {"external": 0, "credit": 0, "stars": 0},
    }
    for platform, provider, currency, amount, nominal_rials in payment_rows.all():
        group = totals.setdefault(
            platform, {"external": 0, "credit": 0, "stars": 0}
        )
        if provider in _EXTERNAL_IRR_PROVIDERS and currency == "IRR":
            # An API minor amount is NOT the same unit as a rial in Telegram.
            group["external"] += int(nominal_rials)
        elif provider == "store_credit" and currency == "IRR":
            group["credit"] += int(nominal_rials)
        elif provider == "telegram_stars" and currency == "XTR":
            group["stars"] += int(amount)

    channels = []
    for platform in ("telegram", "bale"):
        counts = order_counts.get(platform, {})
        total_orders = sum(counts.values())
        customers, opted_in = customer_counts.get(platform, (0, 0))
        amounts = totals[platform]
        channels.append(
            ChannelSummary(
                platform=platform,
                customers=customers,
                opted_in=opted_in,
                orders=total_orders,
                paid_orders=counts.get("paid", 0),
                review_orders=(
                    counts.get("pending_review", 0)
                    + counts.get("approved_unpaid", 0)
                ),
                paid_unfulfilled=counts.get("paid_unfulfilled", 0),
                refunded=counts.get("refunded", 0),
                gross_paid_irr=amounts["external"],
                store_credit_irr=amounts["credit"],
                telegram_stars_xtr=amounts["stars"],
            )
        )

    # Campaign approval and sending are events without a `created_at`
    # on the recipient outbox; all pending states remain visible to prevent
    # old unresolved deliveries disappearing from operational reports.
    campaign_query = select(
        ShopCampaignDelivery.status,
        func.count(ShopCampaignDelivery.id),
    )
    if selected is not None:
        campaign_query = campaign_query.join(
            ShopCampaign, ShopCampaign.id == ShopCampaignDelivery.campaign_id,
        ).where(ShopCampaign.store_id.in_(selected))
    campaign_result = await session.execute(
        campaign_query.group_by(ShopCampaignDelivery.status)
    )
    campaign_counts = dict(campaign_result.all())

    refund_query = select(func.count()).select_from(ShopRefundCase).where(
        ShopRefundCase.status.in_(("requested", "provider_pending"))
    )
    if selected is not None:
        refund_query = refund_query.join(
            ShopOrder, ShopOrder.id == ShopRefundCase.order_id,
        ).where(ShopOrder.store_id.in_(selected))
    pending_refunds = int((await session.scalar(refund_query)) or 0)

    wallet_clause = (
        [ShopWalletEntry.created_at >= since] if since else []
    )
    wallet_query = select(
        func.coalesce(func.sum(
            case(
                (ShopWalletEntry.delta_irr > 0, ShopWalletEntry.delta_irr),
                else_=0,
            )
        ), 0),
        func.coalesce(func.sum(
            case(
                (ShopWalletEntry.delta_irr < 0, -ShopWalletEntry.delta_irr),
                else_=0,
            )
        ), 0),
    ).where(*wallet_clause)
    if selected is not None:
        wallet_query = wallet_query.join(
            ShopWalletAccount,
            ShopWalletAccount.id == ShopWalletEntry.account_id,
        ).where(ShopWalletAccount.store_id.in_(selected))
    wallet_result = await session.execute(wallet_query)
    issued, spent = wallet_result.one()

    line_clause = (
        [ShopOrder.paid_at >= since] if since else []
    )
    if selected is not None:
        line_clause.append(ShopOrder.store_id.in_(selected))
    best_products = await session.execute(
        select(
            ShopOrderLine.product_id,
            func.max(ShopOrderLine.product_name_snapshot),
            func.sum(ShopOrderLine.quantity).label("units"),
        )
        .join(ShopOrder, ShopOrder.id == ShopOrderLine.order_id)
        .where(
            ShopOrder.status == "paid",
            *line_clause,
        )
        .group_by(ShopOrderLine.product_id)
        .order_by(func.sum(ShopOrderLine.quantity).desc())
        .limit(10)
    )
    return ShopAnalytics(
        days=days,
        since=since,
        channels=tuple(channels),
        campaigns=CampaignSummary(
            queued=int(campaign_counts.get("queued", 0)),
            sent=int(campaign_counts.get("sent", 0)),
            unknown=(
                int(campaign_counts.get("unknown", 0))
                + int(campaign_counts.get("sending", 0))
            ),
            skipped=int(campaign_counts.get("skipped", 0)),
        ),
        open_refund_cases=pending_refunds,
        credit_issued_irr=int(issued),
        credit_spent_irr=int(spent),
        top_products=tuple(
            ProductSummary(int(product_id), name, int(quantity))
            for product_id, name, quantity in best_products.all()
        ),
    )
