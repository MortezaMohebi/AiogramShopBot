"""Authenticated, CSRF-protected review of unpaid shop requests.

Only the prepayment administrative states may be changed here. This page
never marks an invoice paid and never deducts product inventory.
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqladmin import BaseView, expose
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse

from db import session_maker
from models.shop_checkout import ShopOrderLine, ShopOrderReviewAudit
from models.shop_content import Product, ShopOrder
from utils.utils import decode_token


class ShopOrderReviewView(BaseView):
    """Offer a guarded review queue in the existing Persian SQLAdmin."""

    name = "بررسی سفارش‌ها"
    icon = "fa-solid fa-clipboard-check"
    category = "فروش"

    @expose("/order-review", methods=["GET", "POST"])
    async def order_review(self, request: Request):
        """Review or reject unpaid orders without asserting payment success."""
        if request.method == "POST":
            return await self._decide(request)
        csrf = secrets.token_urlsafe(32)
        request.session["shop_order_csrf"] = csrf
        async with session_maker() as session:
            result = await session.execute(
                select(ShopOrder)
                .where(
                    ShopOrder.provider == "manual_review",
                    ShopOrder.status.in_(
                        ("pending_review", "approved_unpaid")
                    ),
                )
                .order_by(ShopOrder.id.desc())
                .limit(100)
            )
            orders = result.scalars().all()
        return await self.templates.TemplateResponse(
            request,
            "shop/order-review.html",
            context={
                "orders": orders,
                "csrf": csrf,
                "result": request.query_params.get("result"),
            },
        )

    async def _decide(self, request: Request) -> RedirectResponse:
        """Perform one validated state transition under an order row lock."""
        form = await request.form(max_fields=8, max_files=0)
        nonce = form.get("csrf")
        known = request.session.get("shop_order_csrf")
        if not (
            isinstance(nonce, str) and isinstance(known, str)
            and secrets.compare_digest(nonce, known)
        ):
            raise HTTPException(status_code=403, detail="تأیید فرم نامعتبر است.")
        request.session.pop("shop_order_csrf", None)

        try:
            order_id = int(form.get("order_id", "0"))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="شناسه سفارش نامعتبر است.") from None
        decision = form.get("decision")
        if order_id <= 0 or decision not in ("accept", "reject"):
            raise HTTPException(status_code=400, detail="تصمیم مدیریتی نامعتبر است.")

        claims = decode_token(request.session.get("token"))
        if not isinstance(claims, dict) or claims.get("sub") != "ADMIN":
            raise HTTPException(status_code=403, detail="اجازه لازم وجود ندارد.")
        async with session_maker() as session:
            order = await session.scalar(
                select(ShopOrder).where(
                    ShopOrder.id == order_id,
                    ShopOrder.provider == "manual_review",
                ).with_for_update()
            )
            if order is None:
                raise HTTPException(status_code=404, detail="سفارش پیدا نشد.")
            if order.status not in (
                "pending_review", "approved_unpaid"
            ):
                raise HTTPException(
                    status_code=409, detail="این سفارش قابل تغییر نیست."
                )
            if decision == "accept":
                if order.status != "pending_review":
                    raise HTTPException(
                        status_code=409, detail="سفارش قبلاً بررسی شده است."
                    )
                # Confirm that all requested lines still exist and have stock.
                result = await session.execute(
                    select(ShopOrderLine, Product)
                    .join(Product, ShopOrderLine.product_id == Product.id)
                    .where(ShopOrderLine.order_id == order.id)
                )
                lines = result.all()
                if not lines or any(
                    product.stock_quantity < line.quantity
                    or not product.is_published
                    for line, product in lines
                ):
                    raise HTTPException(
                        status_code=409, detail="موجودی کالا نیازمند بررسی است."
                    )
                next_status = "approved_unpaid"
            else:
                next_status = "cancelled"

            session.add(
                ShopOrderReviewAudit(
                    order_id=order.id,
                    actor=str(claims["sub"]),
                    action=decision,
                    old_status=order.status,
                    new_status=next_status,
                )
            )
            order.status = next_status
            await session.commit()
        return RedirectResponse(
            "/admin/order-review?result=" + decision,
            status_code=303,
        )
