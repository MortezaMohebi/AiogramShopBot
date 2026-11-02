"""Harden SQLAdmin's unrestricted AJAX model lookup endpoint.

SQLAdmin 0.22.0 implements `ajax_lookup` without `@login_required` and
without a ModelView permission check. This subclass protects that endpoint
and preserves the upstream's normal create/edit/list behavior.
"""

from __future__ import annotations

from sqladmin import Admin
from sqladmin.authentication import login_required
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response


class SecureShopAdmin(Admin):
    """Deny anonymous or cross-role AJAX lookups into protected model data."""

    @login_required
    async def ajax_lookup(self, request: Request) -> Response:
        """Authenticate first, then enforce the requested model's role."""
        identity = request.path_params.get("identity", "")
        view = self._find_model_view(identity)
        if not view.is_accessible(request):
            raise HTTPException(status_code=403, detail="دسترسی مجاز نیست.")
        return await super().ajax_lookup(request)
