"""Reconcile an uncredited, provider-confirmed referral for a paid order.

No background worker is created. The command is read-only unless the operator
passes --apply and confirms a specific order ID on the private application host.
Rewards remain idempotent and limited by the merchant's active referral policy.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from db import session_maker
from models.shop_content import ShopOrder
from models.shop_payment import ShopPaymentAttempt
from services.shop_referrals import ShopReferralService


async def reconcile(order_id: int, *, apply: bool) -> None:
    """Review provider evidence and optionally apply a missing IRR reward."""
    if order_id <= 0:
        raise ValueError("Order ID must be positive.")

    async with session_maker() as session:
        result = await session.execute(
            select(ShopOrder, ShopPaymentAttempt)
            .outerjoin(
                ShopPaymentAttempt,
                ShopPaymentAttempt.order_id == ShopOrder.id,
            )
            .where(ShopOrder.id == order_id)
        )
        row = result.one_or_none()
        if row is None:
            raise ValueError("Order was not found.")
        order, intent = row
        eligible_receipt = bool(
            order.status == "paid"
            and order.payment_currency == "IRR"
            and order.provider in ("bale_wallet", "telegram_fiat")
            and intent is not None
            and intent.status == "paid"
            and intent.provider == order.provider
            and intent.currency == "IRR"
            and intent.platform == order.platform
        )
        print(
            f"Order ID: {order.id}; platform: {order.platform}; "
            f"provider: {order.provider}; paid receipt: {eligible_receipt}"
        )
        if not eligible_receipt:
            print("No eligible provider-confirmed IRR receipt; refusing award.")
            return
        if not apply:
            print("Read-only review complete. No store credit was changed.")
            return

        confirmation = input(
            "Type the order ID again to authorize idempotent reward: "
        ).strip()
        if confirmation != str(order.id):
            raise ValueError("Explicit order ID confirmation did not match.")

        amount = await ShopReferralService.award_for_paid_order(
            session, order.id
        )
        print(
            f"Referral reconciliation committed. "
            f"Newly credited amount: {amount} IRR."
        )


def main() -> None:
    """Read command arguments; require an explicit choice to issue credit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-id", type=int, required=True)
    parser.add_argument(
        "--apply", action="store_true",
        help="Credit a missing eligible reward after interactive confirmation.",
    )
    args = parser.parse_args()
    asyncio.run(reconcile(args.order_id, apply=args.apply))


if __name__ == "__main__":
    main()
