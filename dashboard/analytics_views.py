"""Read-only reporting for Telegram and Bale, preserving monetary units."""

from __future__ import annotations

from sqladmin import BaseView, expose
from starlette.exceptions import HTTPException
from starlette.requests import Request

from dashboard.permissions import require_role
from db import session_maker
from services.shop_analytics import build_shop_analytics


class ShopAnalyticsView(BaseView):
    """Expose aggregated, role-guarded reports from the shared shop database."""

    name = "گزارش عملکرد"
    icon = "fa-solid fa-chart-column"
    category = "گزارش‌ها"

    @staticmethod
    def is_visible(request: Request) -> bool:
        """Show the report to authenticated staff with reporting permissions."""
        return getattr(request.state, "shop_role", None) in (
            "superadmin", "sales", "finance", "marketing", "content", "viewer"
        )

    @expose("/shop-analytics", methods=["GET"])
    async def shop_analytics(self, request: Request):
        """Render a bounded time period and keep IRR, credit and XTR distinct."""
        require_role(
            request, "sales", "finance", "marketing", "content", "viewer"
        )
        try:
            days = int(request.query_params.get("days", "30"))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail="بازه گزارش معتبر نیست."
            ) from None
        async with session_maker() as session:
            try:
                report = await build_shop_analytics(session, days=days)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="بازه گزارش معتبر نیست."
                ) from None
        return await self.templates.TemplateResponse(
            request,
            "shop/shop-analytics.html",
            context={
                "report": report,
                "periods": (
                    (7, "۷ روز"),
                    (30, "۳۰ روز"),
                    (90, "۹۰ روز"),
                    (365, "یک سال"),
                    (0, "همه سوابق جدید"),
                ),
            },
        )
