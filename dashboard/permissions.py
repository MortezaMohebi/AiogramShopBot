"""Role rules and request-level authorization for SQLAdmin views.

SQLAdmin ModelView uses synchronous `is_accessible`. Authentication backend
performs a live staff lookup first and sets `request.state.shop_role`.
"""

from __future__ import annotations

from typing import Any, TypeVar

from starlette.exceptions import HTTPException
from starlette.requests import Request


VIEW_PERMISSIONS: dict[str, frozenset[str]] = {
    "کاتالوگ": frozenset({"superadmin", "content"}),
    "محتوا": frozenset({"superadmin", "content"}),
    "فروش": frozenset({"superadmin", "sales"}),
    "مشتریان": frozenset({"superadmin", "sales"}),
    "مالی": frozenset({"superadmin", "finance"}),
    "بازاریابی": frozenset({"superadmin", "marketing"}),
    "گزارش‌ها": frozenset({
        "superadmin", "sales", "content", "finance", "marketing", "viewer"
    }),
    "تنظیمات": frozenset({"superadmin"}),
}
T = TypeVar("T")


def require_role(request: Request, *allowed: str) -> None:
    """Return HTTP 403 for any unauthenticated or unauthorized operator."""
    role = getattr(request.state, "shop_role", None)
    if not role or role not in set(allowed) | {"superadmin"}:
        raise HTTPException(status_code=403, detail="دسترسی مجاز نیست.")


def secure_model_view(view: type[T]) -> type[T]:
    """Apply deny-by-default role restrictions to a SQLAdmin ModelView.

    The model's category is static interface metadata; shop products and
    editable content remain database-driven.
    """
    category = getattr(view, "category", "")
    allowed = VIEW_PERMISSIONS.get(category, frozenset({"superadmin"}))

    def is_accessible(self: Any, request: Request) -> bool:
        """Check a role written by the authenticated staff session."""
        return getattr(request.state, "shop_role", None) in allowed

    def is_visible(self: Any, request: Request) -> bool:
        """Hide inaccessible sidebar entries, not just their endpoints."""
        return is_accessible(self, request)

    view.is_accessible = is_accessible
    view.is_visible = is_visible
    return view
