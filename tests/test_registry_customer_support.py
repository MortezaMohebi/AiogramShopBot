"""Registry operation gates preserve bounded after-sale help and settlement."""

from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from channels.contracts import Platform
from services.shop_multibot_dispatch import dispatch
from tests.test_beta_paused_customer_support import NativeClient, account, raw
from tests.test_shared_cart import db


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("state", ["paused", "maintenance", "disabled"])
async def test_registry_payment_callback_obeys_operation_gate(
    db, monkeypatch, platform, state,
):
    """A stale payment button never issues an invoice while shopping is off."""
    context, _ = await account(db, platform)

    @asynccontextmanager
    async def sessions():
        """Use real scoped identity queries and no configured database."""
        yield db

    async def forbidden_invoice(*_args, **_kwargs):
        """Fail if a denied callback reaches the external invoice boundary."""
        pytest.fail("Paused customer callback issued an invoice")

    monkeypatch.setattr("services.shop_multibot_dispatch.session_maker", sessions)
    monkeypatch.setattr("services.shop_multibot_dispatch.send_order_invoice", forbidden_invoice)
    native = NativeClient()
    await dispatch(replace(context, status=state), native, raw(callback="shop:pay:1"))
    assert native.acks == ["cb"]
    assert bool(native.messages) is (state != "disabled")


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("requested", ["ux:support", "shop:refundorder:1"])
async def test_disabled_registry_bot_keeps_chat_fail_closed(
    db, monkeypatch, platform, requested,
):
    """Revocation cannot acquire a support or refund-prefix bypass."""
    context, _ = await account(db, platform)

    @asynccontextmanager
    async def sessions():
        """Retain the isolated identity and customer ledger."""
        yield db

    monkeypatch.setattr("services.shop_multibot_dispatch.session_maker", sessions)
    native = NativeClient()
    await dispatch(replace(context, status="disabled"), native, raw(callback=requested))
    assert native.messages == []
    assert native.acks == ["cb"]
