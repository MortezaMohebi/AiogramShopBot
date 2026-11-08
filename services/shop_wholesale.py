"""Persist wholesale forms with live customer and private-evidence checks.

The caller owns transaction commit and authorization. Runtime callers use the
Action Registry so its customer confirmation and idempotency remain atomic with
the application. This service never downloads evidence or calls a provider.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_content import ShopIdentity
from models.shop_store_commerce import ShopStoreCustomer
from models.shop_wholesale import ShopWholesaleApplication
from services import shop_admin_security as security
from services.shop_actions.schemas import WholesaleInput
from services.shop_bot_context import BotContext, resolve_bot_context
from services.shop_customer_account import customer_for_bot


class WholesaleRejected(ValueError):
    """Expose stable domain failures without private customer values."""

    def __init__(self, code: str) -> None:
        """Retain only the allowlisted code consumed by the Action adapter."""
        super().__init__(code)
        self.code = code


async def validate_application(
    db: AsyncSession,
    context: BotContext,
    *,
    platform_user_id: int,
    data: dict,
) -> tuple[ShopIdentity, ShopStoreCustomer, WholesaleInput]:
    """Validate the bounded form and its ownership without SQL writes."""
    try:
        form = WholesaleInput.model_validate(data)
    except (TypeError, ValueError):
        raise WholesaleRejected("wholesale_invalid_input") from None
    try:
        current = await resolve_bot_context(
            db,
            authenticated_bot_id=context.bot_id,
            authenticated_platform=context.platform,
        )
        if current.store_id != context.store_id:
            raise ValueError("wholesale_customer_unavailable")
        identity, customer = await customer_for_bot(
            db,
            current,
            platform_user_id=platform_user_id,
        )
    except (security.SecurityRejected, ValueError):
        raise WholesaleRejected("wholesale_customer_unavailable") from None
    if form.document_handle is not None:
        # Import evidence only when needed; never dereference caller URLs.
        from models.shop_workflow_runtime import WorkflowUpload

        evidence = await db.scalar(
            select(WorkflowUpload)
            .where(
                WorkflowUpload.id == form.document_handle,
                WorkflowUpload.store_id == current.store_id,
                WorkflowUpload.bot_id == current.bot_id,
                WorkflowUpload.customer_id == customer.id,
                WorkflowUpload.user_id == identity.platform_user_id,
                WorkflowUpload.kind.in_(("photo", "document")),
                WorkflowUpload.verified.is_(True),
                WorkflowUpload.expires_at > security.clock(),
            )
            .execution_options(populate_existing=True)
        )
        if evidence is None:
            raise WholesaleRejected("wholesale_document_unavailable")
    return identity, customer, form


async def create_application(
    db: AsyncSession,
    context: BotContext,
    *,
    platform_user_id: int,
    data: dict,
) -> ShopWholesaleApplication:
    """Flush one owned form within the caller's confirmed transaction."""
    identity, customer, form = await validate_application(
        db,
        context,
        platform_user_id=platform_user_id,
        data=data,
    )
    application = ShopWholesaleApplication(
        store_id=identity.store_id,
        bot_id=identity.bot_id,
        customer_id=customer.id,
        origin_identity_id=identity.id,
        platform=identity.platform,
        platform_user_id=identity.platform_user_id,
        **form.model_dump(),
    )
    db.add(application)
    await db.flush()
    return application
