"""Finance-only, CSRF-protected store-credit adjustment for staff."""

from __future__ import annotations

import secrets

from sqladmin import BaseView, expose
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse

import config
from channels.contracts import Platform
from dashboard.permissions import require_role
from db import session_maker
from services.shop_wallet import ShopWalletService, StoreCreditRejected


class ShopWalletAdjustmentView(BaseView):
    """Use a reviewable ledger entry, never a writable balance field."""

    name = "اصلاح اعتبار"
    icon = "fa-solid fa-wallet"
    category = "مالی"

    @staticmethod
    def is_visible(request: Request) -> bool:
        """Display only to explicitly authorized finance staff."""
        return getattr(request.state, "shop_role", None) in (
            "superadmin", "finance"
        )

    @expose("/wallet-adjust", methods=["GET", "POST"])
    async def wallet_adjust(self, request: Request):
        """Adjust a named identity with exact rial value and operation audit."""
        require_role(request, "finance")
        max_amount = config.SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR
        if request.method == "GET":
            nonce = secrets.token_urlsafe(32)
            request.session["shop_wallet_adjust_nonce"] = nonce
            return await self.templates.TemplateResponse(
                request,
                "shop/wallet-adjust.html",
                context={
                    "nonce": nonce,
                    "max_amount": max_amount,
                    "notice": request.query_params.get("result") == "saved",
                },
            )

        form = await request.form(max_fields=12, max_files=0)
        nonce = form.get("nonce")
        saved = request.session.pop("shop_wallet_adjust_nonce", None)
        if not (
            isinstance(nonce, str)
            and isinstance(saved, str)
            and secrets.compare_digest(nonce, saved)
        ):
            raise HTTPException(status_code=403, detail="درخواست تأیید نشد.")
        if max_amount <= 0:
            raise HTTPException(
                status_code=409,
                detail="تنظیم سقف اصلاح اعتبار توسط مدیر اصلی لازم است.",
            )
        if form.get("confirmation") != "CREDIT_CONFIRMED":
            raise HTTPException(
                status_code=400, detail="تأیید صریح عملیات لازم است."
            )
        try:
            platform = Platform(form.get("platform"))
            user_id = int(form.get("user_id"))
            amount = int(form.get("amount_irr"))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="شناسه یا مبلغ معتبر نیست.") from None
        if (
            type(user_id) is not int or user_id <= 0
            or not 1 <= amount <= max_amount
        ):
            raise HTTPException(status_code=400, detail="مبلغ بیش از سقف یا نامعتبر است.")
        direction = form.get("direction")
        if direction not in ("credit", "debit"):
            raise HTTPException(status_code=400, detail="نوع عملیات معتبر نیست.")
        reason = str(form.get("reason") or "").strip()
        if not 12 <= len(reason) <= 200:
            raise HTTPException(
                status_code=400, detail="توضیح عملیات باید حداقل ۱۲ نویسه باشد."
            )
        staff_id = getattr(request.state, "shop_staff_id", None)
        if type(staff_id) is not int:
            raise HTTPException(status_code=403, detail="شناسه مدیر معتبر نیست.")

        async with session_maker() as session:
            identity = await ShopWalletService.find_identity(
                session, platform, user_id
            )
            if identity is None:
                raise HTTPException(status_code=404, detail="کاربر پیدا نشد.")
            try:
                await ShopWalletService.apply(
                    session,
                    identity_id=identity.id,
                    delta_irr=amount if direction == "credit" else -amount,
                    operation_key=f"staff-adjust:{nonce}",
                    reason=reason,
                    actor=f"staff:{staff_id}",
                )
                await session.commit()
            except StoreCreditRejected as error:
                await session.rollback()
                raise HTTPException(status_code=409, detail=str(error)) from None
        return RedirectResponse(
            "/admin/wallet-adjust?result=saved", status_code=303
        )
