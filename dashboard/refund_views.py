"""Authenticated refund review with explicit, non-automatic provider decisions."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqladmin import BaseView, expose
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse

import config
from db import session_maker
from models.shop_content import ShopOrder
from models.shop_payment import ShopRefundCase
from services.shop_payments import PaymentRejected
from services.shop_refunds import ShopRefundService
from utils.utils import decode_token


class ShopRefundReviewView(BaseView):
    """Expose finance review without editable paid-state model fields."""

    name = "بررسی بازپرداخت"
    icon = "fa-solid fa-rotate-left"
    category = "مالی"

    @expose("/refund-review", methods=["GET", "POST"])
    async def refund_review(self, request: Request):
        """Display cases or process one authorized CSRF-protected decision."""
        if request.method == "POST":
            return await self._handle_decision(request)
        token = secrets.token_urlsafe(32)
        request.session["shop_refund_csrf"] = token
        async with session_maker() as session:
            rows = await session.execute(
                select(ShopRefundCase, ShopOrder)
                .join(ShopOrder, ShopOrder.id == ShopRefundCase.order_id)
                .order_by(ShopRefundCase.id.desc())
                .limit(100)
            )
            cases = list(rows.all())
        return await self.templates.TemplateResponse(
            request,
            "shop/refund-review.html",
            context={
                "cases": cases,
                "csrf": token,
                "stars_enabled": config.TELEGRAM_STARS_REFUNDS_ENABLED,
                "notice": request.query_params.get("result"),
            },
        )

    async def _handle_decision(self, request: Request) -> RedirectResponse:
        """Execute an operator-approved provider refund or record its proof."""
        form = await request.form(max_files=0, max_fields=12)
        csrf = form.get("csrf")
        saved = request.session.pop("shop_refund_csrf", None)
        if not (
            isinstance(csrf, str) and isinstance(saved, str)
            and secrets.compare_digest(csrf, saved)
        ):
            raise HTTPException(status_code=403, detail="درخواست تأیید نشد.")
        claims = decode_token(request.session.get("token"))
        if not isinstance(claims, dict) or claims.get("sub") != "ADMIN":
            raise HTTPException(status_code=403, detail="دسترسی مجاز نیست.")
        try:
            case_id = int(form.get("case_id", "0"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="شناسه نامعتبر است.") from None
        if case_id <= 0:
            raise HTTPException(status_code=400, detail="شناسه نامعتبر است.")
        action = form.get("action")
        reviewer = "admin"
        if form.get("confirmation") != "REFUND_VERIFIED":
            raise HTTPException(
                status_code=400,
                detail="بدون تأیید صریحِ بررسی سند بازپرداخت امکان اقدام نیست.",
            )
        async with session_maker() as session:
            try:
                if action == "stars":
                    await ShopRefundService.refund_stars(
                        session,
                        case_id=case_id,
                        bot=request.app.state.telegram_bot,
                        enabled=config.TELEGRAM_STARS_REFUNDS_ENABLED,
                        reviewer=reviewer,
                    )
                elif action == "manual":
                    reference = str(form.get("provider_reference") or "").strip()
                    await ShopRefundService.confirm_manual(
                        session,
                        case_id=case_id,
                        provider_reference=reference,
                        reviewer=reviewer,
                    )
                else:
                    raise PaymentRejected("نوع درخواست بازپرداخت مشخص نیست.")
            except PaymentRejected as error:
                raise HTTPException(
                    status_code=409, detail=str(error)
                ) from None
        return RedirectResponse(
            "/admin/refund-review?result=confirmed",
            status_code=303,
        )
