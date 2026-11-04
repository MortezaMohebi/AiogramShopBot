"""Request-scoped SQLAlchemy Store record rules for signed admin requests.

Normal provider updates do NOT receive an admin StoreContext; their existing
authenticated BotContext remains authoritative. Administrative ORM reads are
restricted to the session's active Store set, and every write targets its
single current Store. No sudo flag or client-supplied Store ID bypass exists.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from models.shop_checkout import ShopCart, ShopCoupon, ShopShippingMethod
from models.shop_content import Product, ShopCategory, ShopIdentity, ShopOrder
from models.shop_engagement import ShopCampaign, ShopWalletAccount
from models.shop_multibot import ShopBot
from models.shop_payment import ShopPaymentAttempt
from models.shop_store_commerce import (
    ShopPaymentAccount, ShopStoreCustomer, ShopStoreSettings,
)
from models.shop_customer_navigation import (
    ShopStoreMenuPolicy, ShopBotMenuPolicy, ShopCustomerChatState,
)
from models.shop_customer_account_data import (
    ShopCustomerAddress, ShopCustomerWishlist, ShopCustomerPreference,
)
from models.shop_checkout_policy import ShopStoreCheckoutPolicy, ShopBotCheckoutPolicy
from models.shop_customer_support import (
    ShopSupportTicket, ShopSupportMessage,
    ShopOrderFulfillment, ShopFulfillmentEvent,
)
from models.shop_customer_notifications import (
    ShopStockAlert, ShopCustomerNotificationOutbox,
)
from models.shop_checkout_batch import ShopCheckoutBatch
from models.shop_digital_delivery import (
    ShopDigitalAsset, ShopDigitalDelivery, ShopDigitalLicenseKey,
)
from services import shop_admin_security as security
from services.shop_store_context import current_context

# Only models with an explicitly checked, non-nullable Store ownership column.
# Do NOT add membership/preference/session tables: those are managed by
# superadmin under a separate authorization path across the allowed set.
STORE_OWNED_MODELS = (
    ShopBot, ShopCategory, Product, ShopShippingMethod, ShopCoupon,
    ShopIdentity, ShopCart, ShopOrder, ShopWalletAccount, ShopCampaign,
    ShopPaymentAttempt, ShopStoreCustomer, ShopPaymentAccount,
    ShopStoreSettings,
    ShopStoreMenuPolicy, ShopBotMenuPolicy, ShopCustomerChatState,
    ShopCustomerAddress, ShopCustomerWishlist, ShopCustomerPreference,
    ShopStoreCheckoutPolicy, ShopBotCheckoutPolicy,
    ShopSupportTicket, ShopSupportMessage,
    ShopOrderFulfillment, ShopFulfillmentEvent,
    ShopStockAlert, ShopCustomerNotificationOutbox,
    ShopCheckoutBatch, ShopDigitalAsset, ShopDigitalDelivery,
    ShopDigitalLicenseKey,
)


@event.listens_for(Session, "do_orm_execute")
def restrict_admin_select(execute_state) -> None:
    """Apply active-Store row-level filters to all admin ORM SELECT queries."""
    ctx = current_context()
    if ctx is None or not execute_state.is_select:
        return
    allowed = ctx.active_store_ids
    statement = execute_state.statement
    for model in STORE_OWNED_MODELS:
        statement = statement.options(
            with_loader_criteria(
                model,
                lambda cls: cls.store_id.in_(allowed),
                include_aliases=True,
            )
        )
    execute_state.statement = statement


@event.listens_for(Session, "before_flush")
def require_current_store_for_writes(
    session: Session, flush_context, instances,
) -> None:
    """Reject cross-Store mutations, including indirectly loaded ORM objects."""
    ctx = current_context()
    if ctx is None:
        return
    models = STORE_OWNED_MODELS
    for item in list(session.new) + list(session.dirty) + list(session.deleted):
        if not isinstance(item, models):
            continue
        owner = getattr(item, "store_id", None)
        if item in session.new and not owner:
            # Source models have a legacy default store ID. A new admin
            # record MUST inherit the verified current Store instead.
            item.store_id = ctx.current_store_id
            owner = ctx.current_store_id
        ctx.require(owner, write=True)
