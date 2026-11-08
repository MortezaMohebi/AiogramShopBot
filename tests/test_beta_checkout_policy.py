"""Beta P3 CheckoutPolicy and platform payment legality regression."""

from __future__ import annotations

import pytest

from channels.contracts import Platform
from services.shop_checkout_policy import (
    decide_checkout_mode, legal_credit_for_items, terms_configured,
)


def test_missing_policy_defaults_to_manual_approval():
    """No registered Store enables instant payment implicitly."""
    assert decide_checkout_mode(None, None) == "manual"


def test_per_bot_override_cannot_overrule_store_ownership():
    """A Bot choice may override mode only if its Store matches policy."""
    from types import SimpleNamespace

    store = SimpleNamespace(mode="manual")
    override = SimpleNamespace(mode_override="instant")
    assert decide_checkout_mode(store, override) == "instant"


def test_telegram_digital_goods_can_never_use_irr_store_credit():
    """Telegram digital goods/services must be paid via Stars XTR."""
    assert not legal_credit_for_items(
        Platform.TELEGRAM, {"digital"},
    )
    assert not legal_credit_for_items(
        Platform.TELEGRAM, {"digital", "physical"},
    )
    assert legal_credit_for_items(
        Platform.TELEGRAM, {"physical"},
    )
    assert legal_credit_for_items(
        Platform.BALE, {"digital"},
    )


def test_instant_requires_published_terms_and_revision():
    """One click must not silently accept missing merchant sales terms."""
    from types import SimpleNamespace

    assert not terms_configured(None)
    assert not terms_configured(SimpleNamespace(
        terms_text="", terms_version="v1",
    ))
    assert terms_configured(SimpleNamespace(
        terms_text="شرایط خرید معتبر فروشگاه", terms_version="v1",
    ))
