"""Customer search and chat FSM regression cases for both Bot adapters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from channels.contracts import Platform
from models.shop_customer_navigation import ShopCustomerChatState
from services.shop_customer_search import search_text_valid, search_key, permitted_search_fields


def test_query_validation_handles_persian_and_rejects_empty_or_control():
    """Customer product search accepts Persian strings but not unsafe input."""
    assert search_text_valid("فیلتر روغن ۲۰۲۶")
    assert search_text_valid("SKU-AB_2026")
    for invalid in ("", " ", "a", "\n", "a\x00b", "x" * 101):
        assert not search_text_valid(invalid)


def test_search_owner_scoped_per_bot_even_with_same_numeric_user_id():
    """A bot/user pair is a unique FSM owner; provider IDs never suffice."""
    a, b = "bot-a", "bot-b"
    assert search_key(bot_id=a, user_id=55) != search_key(bot_id=b, user_id=55)


def test_customer_search_only_allows_published_fields():
    """Admin-only ORM/finance attributes are not valid bot search fields."""
    assert set(permitted_search_fields()) == {"all", "name", "sku", "description"}
    assert "store_id" not in permitted_search_fields()
    assert "customer_id" not in permitted_search_fields()
    assert "provider_token" not in permitted_search_fields()
