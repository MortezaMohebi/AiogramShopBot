"""Load only legacy entry functions without starting the application runtime."""

# The production function resolves these imports through its isolated globals.
# ruff: noqa: F401, S102

from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

import config
from channels.bale import BaleApiError, BaleTransport
from channels.contracts import BotReply, InboundEvent, Platform, normalize_update
from channels.shop_payment_dispatch import send_order_invoice
from channels.telegram import TelegramTransport
from models.shop_content import ShopOrder
from models.shop_multibot import LEGACY_BOT_IDS, LEGACY_TELEGRAM_BOT_ID
from models.shop_payment import ShopPaymentAttempt
from services import shop_multibot_dispatch
from services.bale_wallet import CheckoutRejected
from services.shop_bale_payments import (
    settle_bale_payment,
    validate_bale_precheckout,
)
from services.shop_bot_context import resolve_legacy_bot_context
from services.shop_bot_operations import legacy_state
from services.shop_bot_profiles import get_bot_options
from services.shop_cart import ShopCartFlow
from services.shop_channel_catalog import CatalogFlow
from services.shop_customer_experience import (
    CustomerExperienceFlow,
    clear_pending_on_navigation,
)
from services.shop_customer_notification_dispatch import deliver_order_paid_once
from services.shop_engagement_flow import ShopEngagementFlow
from services.shop_identity import is_blocked, register_customer
from services.shop_orders import ShopOrdersFlow
from services.shop_payments import PaymentRejected, ShopPaymentService
from services.shop_referrals import ShopReferralService


def legacy_function(path: str, name: str, **overrides: Any):
    """Execute the actual function body with isolated native dependencies.

    Importing bot.py constructs polling, Redis and provider clients. Compiling
    only the selected production function keeps offline tests independent of
    that application startup while exercising its original control flow.
    """
    source = Path(__file__).resolve().parents[1] / path
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    target = next(node for node in tree.body if (
        isinstance(node, ast.AsyncFunctionDef) and node.name == name
    ))
    definitions = [node for node in tree.body if (
        isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_shop_reply" and node is not target
    )] + [target]
    for node in definitions:
        node.decorator_list = []
    module = ast.Module(body=definitions, type_ignores=[])
    namespace = globals().copy()
    namespace.update({
        "Request": object, "Message": object, "CallbackQuery": object,
        "AsyncSession": object,
        "_flow": lambda: CatalogFlow(),
        "config": SimpleNamespace(**{
            "SHOP_DISPLAY_UNIT": "IRR", "SHOP_CURRENCY_LABEL": "ریال",
            **vars(config),
        }),
    })
    if hasattr(shop_multibot_dispatch, "paused_customer_reply"):
        namespace["paused_customer_reply"] = shop_multibot_dispatch.paused_customer_reply
    namespace.update(overrides)
    exec(compile(module, str(source), "exec"), namespace)
    return namespace[name]
