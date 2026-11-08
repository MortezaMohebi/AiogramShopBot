"""Store-owned admin refunds with real credentials and offline providers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from models.shop_content import Product, ShopIdentity, ShopOrder
from models.shop_engagement import ShopWalletAccount, ShopWalletEntry
from models.shop_multibot import (
    DEFAULT_STORE_ID,
    ShopBot,
    ShopBotCredential,
    ShopStore,
)
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
from models.shop_store_commerce import ShopPaymentAccount
from services import shop_multibot_client
from services.shop_admin_security import SecurityRejected
from services.shop_bot_secrets import encrypt_for_bot
from services.shop_payments import PaymentRejected
from services.shop_store_context import AuthorizedStore, StoreContext
from tests.schema_support import seed_test_units
from tests.test_beta_digital_fulfillment import OfflineSession, purchase  # noqa: F401


def store_scope(
    store_id: str, *, access_level: str = "manager"
) -> StoreContext:
    """Build a trusted current Store with an explicit membership level."""
    return StoreContext(
        staff_id=1,
        session_id="offline-admin-refund",
        allowed_stores=(
            AuthorizedStore(
                id=store_id,
                slug="test-store",
                name="Store",
                state="active",
                access_level=access_level,
            ),
        ),
        active_store_ids=(store_id,),
        current_store_id=store_id,
        default_store_id=store_id,
        version=1,
    )


class AdminSession(OfflineSession):
    """Expose real credential decryption and wallet writes on the local ORM."""

    async def run_sync(self, operation):
        """Run the production token resolver against the local ORM."""
        return operation(self.session)


class RefundBot:
    """Record provider calls after observing the durable pending receipt."""

    def __init__(
        self, session: Session, case_id: int, provider_id: int
    ) -> None:
        """Retain only the fake provider identity and disposable database."""
        self.session = session
        self.case_id = case_id
        self.id = provider_id
        self.calls = []

    async def refund_star_payment(self, **payload):
        """Confirm one simulated refund without an HTTP client."""
        with Session(self.session.bind) as observer:
            assert (
                observer.get(ShopRefundCase, self.case_id).status
                == "provider_pending"
            )
        self.calls.append(payload)
        return True


@pytest.fixture
def admin_refund(purchase, monkeypatch):  # noqa: F811
    """Add verified origin credentials and a private Stars payment account."""
    monkeypatch.setenv(
        "SHOP_SECURITY_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    monkeypatch.delenv("SHOP_BOT_SECRET_KEY", raising=False)
    monkeypatch.setattr(config, "TELEGRAM_STARS_REFUNDS_ENABLED", True)
    token = "12345678:" + "A" * 35
    purchase.bot.provider_bot_id = 12345678
    purchase.bot.verified_at = datetime.now(timezone.utc)
    credential = ShopBotCredential(
        id=str(uuid4()),
        bot_id=purchase.bot.id,
        version=1,
        source="encrypted",
        state="active",
        ciphertext=encrypt_for_bot(purchase.bot.id, "telegram", token),
        verified_bot_id=12345678,
        verified_at=datetime.now(timezone.utc),
    )
    account = ShopPaymentAccount(
        id=str(uuid4()),
        store_id=purchase.order.store_id,
        platform="telegram",
        rail_type="telegram_stars",
        currency="XTR",
        name="Stars account",
        state="active",
    )
    case = ShopRefundCase(
        order_id=purchase.order.id,
        status="requested",
        actor="staff:1",
        reason="Customer refund request",
    )
    purchase.session.add_all([credential, account, case])
    purchase.session.flush()
    purchase.receipt.payment_account_id = account.id
    purchase.session.commit()
    primary = RefundBot(purchase.session, case.id, 12345678)
    lifecycle = []

    @asynccontextmanager
    async def provider(platform, secret, *, bot_id):
        """Replace only the external connection and retain exact selection."""
        lifecycle.append(("opened", platform, secret, bot_id))
        try:
            yield primary
        finally:
            lifecycle.append(("closed", platform, secret, bot_id))

    monkeypatch.setattr(shop_multibot_client, "provider_client", provider)
    return SimpleNamespace(
        purchase=purchase,
        db=AdminSession(purchase.session),
        case=case,
        credential=credential,
        account=account,
        token=token,
        scope=store_scope(purchase.order.store_id),
        provider=primary,
        lifecycle=lifecycle,
    )


async def resolve(refund, *, action="stars", scope=None, reference=""):
    """Call the production admin boundary with the trusted server context."""
    from services.shop_admin_refunds import resolve_admin_refund

    return await resolve_admin_refund(
        refund.db,
        scope=scope if scope is not None else refund.scope,
        case_id=refund.case.id,
        action=action,
        provider_reference=reference,
    )


@pytest.mark.asyncio
async def test_disabled_stars_refunds_never_decrypt_or_open_client(
    admin_refund,
    monkeypatch,
):
    """The deployment switch is checked before secret or provider setup."""
    monkeypatch.setattr(config, "TELEGRAM_STARS_REFUNDS_ENABLED", False)
    secret_reads = []

    def forbidden_secret_read(session, *, bot_id):
        """Observe any secret resolution even if its exception is sanitized."""
        secret_reads.append(bot_id)
        raise AssertionError("Disabled refunds must not resolve credentials.")

    monkeypatch.setattr(
        "services.shop_admin_refunds.resolve_active_token",
        forbidden_secret_read,
    )
    with pytest.raises(PaymentRejected):
        await resolve(admin_refund)
    assert secret_reads == []
    assert admin_refund.lifecycle == []
    assert admin_refund.provider.calls == []
    assert admin_refund.case.status == "requested"


@pytest.mark.asyncio
@pytest.mark.parametrize("account_state", ["active", "disabled"])
async def test_registry_refund_preserves_origin_and_account_history(
    admin_refund,
    account_state,
):
    """A disabled checkout account does not revoke an already-paid refund."""
    refund = admin_refund
    refund.account.state = account_state
    refund.purchase.session.commit()
    result = await resolve(refund)
    assert result.status == "confirmed"
    assert refund.purchase.order.status == "refunded"
    assert refund.provider.calls == [
        {
            "user_id": 101,
            "telegram_payment_charge_id": "verified-charge",
        }
    ]
    assert refund.lifecycle == [
        ("opened", "telegram", refund.token, refund.purchase.bot.id),
        ("closed", "telegram", refund.token, refund.purchase.bot.id),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["foreign", "not_current", "viewer"])
@pytest.mark.parametrize("action", ["stars", "manual", "store_credit"])
async def test_every_refund_action_requires_the_authorized_current_store(
    admin_refund,
    denial,
    action,
):
    """A read grant or active selection cannot authorize cross-Store writes."""
    current = admin_refund.scope
    foreign_id = str(uuid4())
    if denial == "foreign":
        scope = store_scope(foreign_id)
    elif denial == "not_current":
        foreign = store_scope(foreign_id).current_store
        scope = replace(
            current,
            allowed_stores=current.allowed_stores + (foreign,),
            active_store_ids=(current.current_store_id, foreign_id),
            current_store_id=foreign_id,
        )
    else:
        scope = store_scope(current.current_store_id, access_level="viewer")
    with pytest.raises(SecurityRejected):
        await resolve(admin_refund, action=action, scope=scope)
    assert admin_refund.lifecycle == []
    assert admin_refund.provider.calls == []
    assert admin_refund.case.status == "requested"
    assert admin_refund.purchase.order.status == "paid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        "paused",
        "disabled",
        "maintenance",
        "draft",
        "wrong_store",
        "wrong_platform",
        "unverified_bot",
        "revoked_credential",
        "wrong_version",
        "unverified_credential",
        "wrong_provider_id",
        "wrong_client_id",
    ],
)
async def test_unavailable_or_wrong_origin_bot_never_marks_refund_pending(
    admin_refund,
    invalid,
):
    """Invalid Registry origins cannot fall back to another provider client."""
    refund = admin_refund
    bot = refund.purchase.bot
    if invalid in {"paused", "disabled", "maintenance", "draft"}:
        bot.status = invalid
    elif invalid == "wrong_store":
        other = ShopStore(
            id=str(uuid4()), slug="foreign", name="Foreign", state="active"
        )
        refund.purchase.session.add(other)
        bot.store_id = other.id
    elif invalid == "wrong_platform":
        bot.platform = "bale"
    elif invalid == "unverified_bot":
        bot.verified_at = None
    elif invalid == "revoked_credential":
        refund.credential.state = "revoked"
    elif invalid == "wrong_version":
        bot.credential_version = 2
    elif invalid == "unverified_credential":
        refund.credential.verified_at = None
    elif invalid == "wrong_provider_id":
        refund.credential.verified_bot_id = 87654321
    elif invalid == "wrong_client_id":
        refund.provider.id = 87654321
    refund.purchase.session.commit()
    with pytest.raises(PaymentRejected):
        await resolve(refund)
    assert refund.provider.calls == []
    assert refund.case.status == "requested"
    assert refund.purchase.order.status == "paid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "binding", ["foreign_store", "wrong_rail", "missing_account"]
)
async def test_paid_stars_account_binding_is_validated_before_provider(
    admin_refund,
    binding,
):
    """An unrelated invoice account cannot authorize a Stars refund."""
    refund = admin_refund
    if binding == "foreign_store":
        other = ShopStore(
            id=str(uuid4()),
            slug="foreign-account",
            name="Other",
            state="active",
        )
        refund.purchase.session.add(other)
        refund.account.store_id = other.id
    elif binding == "wrong_rail":
        refund.account.platform = "bale"
        refund.account.rail_type = "bale_wallet"
        refund.account.currency = "IRR"
        refund.account.credential_ciphertext = (
            "sealed-fake-bale-provider-token"
        )
    else:
        refund.purchase.receipt.payment_account_id = str(uuid4())
    refund.purchase.session.commit()
    with pytest.raises(PaymentRejected):
        await resolve(refund)
    assert refund.lifecycle == []
    assert refund.case.status == "requested"


@pytest.mark.asyncio
async def test_client_setup_failure_leaves_requested_case_and_hides_secret(
    admin_refund,
    monkeypatch,
):
    """A failed client setup cannot create an ambiguous financial attempt."""

    @asynccontextmanager
    async def unavailable(*args, **kwargs):
        """Model a setup failure containing a secret that must stay private."""
        raise RuntimeError(admin_refund.token)
        yield  # pragma: no cover

    monkeypatch.setattr(shop_multibot_client, "provider_client", unavailable)
    with pytest.raises(PaymentRejected) as error:
        await resolve(admin_refund)
    assert admin_refund.token not in str(error.value)
    assert admin_refund.case.status == "requested"
    assert admin_refund.provider.calls == []


@pytest.mark.asyncio
async def test_manual_bale_refund_records_proof_without_provider_setup(
    admin_refund,
    monkeypatch,
):
    """Manual external evidence remains scoped and requires no live Bot."""
    refund = admin_refund
    monkeypatch.setattr(config, "TELEGRAM_STARS_REFUNDS_ENABLED", False)
    refund.purchase.order.platform = refund.purchase.receipt.platform = "bale"
    refund.purchase.bot.platform = "bale"
    refund.purchase.order.provider = refund.purchase.receipt.provider = (
        "bale_wallet"
    )
    refund.purchase.order.payment_currency = (
        refund.purchase.receipt.currency
    ) = "IRR"
    refund.purchase.order.payment_amount = refund.purchase.receipt.amount = (
        10000
    )
    refund.purchase.receipt.payment_account_id = None
    refund.purchase.session.commit()
    result = await resolve(
        refund, action="manual", reference="verified-bale-bank-proof"
    )
    assert result.status == "confirmed"
    assert refund.purchase.order.status == "refunded"
    assert refund.lifecycle == []
    assert refund.provider.calls == []


@pytest.mark.asyncio
async def test_store_credit_refund_credits_only_original_scoped_wallet(
    admin_refund,
):
    """The shared helper delegates the real audited wallet ledger operation."""
    refund = admin_refund
    session = refund.purchase.session
    refund.purchase.order.provider = refund.purchase.receipt.provider = (
        "store_credit"
    )
    refund.purchase.order.payment_currency = (
        refund.purchase.receipt.currency
    ) = "IRR"
    refund.purchase.order.payment_amount = refund.purchase.receipt.amount = (
        10000
    )
    refund.purchase.order.telegram_payment_charge_id = None
    refund.purchase.receipt.payment_account_id = None
    identity = ShopIdentity(
        store_id=refund.scope.current_store_id,
        bot_id=refund.purchase.bot.id,
        platform="telegram",
        platform_user_id=101,
    )
    session.add(identity)
    session.flush()
    account = ShopWalletAccount(
        store_id=identity.store_id,
        scope="identity",
        identity_id=identity.id,
        bot_id=identity.bot_id,
        balance_irr=0,
    )
    session.add(account)
    session.flush()
    session.add(
        ShopWalletEntry(
            account_id=account.id,
            source_identity_id=identity.id,
            bot_id=identity.bot_id,
            operation_key=f"store-credit-pay-order:{refund.purchase.order.id}",
            delta_irr=-10000,
            balance_after_irr=0,
            reason="Original debit",
            actor="customer",
        )
    )
    session.commit()
    result = await resolve(refund, action="store_credit")
    assert result.status == "confirmed"
    assert account.balance_irr == 10000
    entry = session.scalar(
        select(ShopWalletEntry).where(
            ShopWalletEntry.operation_key
            == f"store-credit-refund-order:{refund.purchase.order.id}",
        )
    )
    assert entry.account_id == account.id and entry.delta_irr == 10000
    assert refund.lifecycle == []


@pytest.mark.asyncio
async def test_missing_store_context_is_rejected_without_financial_work(
    admin_refund,
):
    """A direct service caller cannot omit the trusted Store authorization."""
    from services.shop_admin_refunds import resolve_admin_refund

    with pytest.raises(SecurityRejected):
        await resolve_admin_refund(
            admin_refund.db,
            scope=None,
            case_id=admin_refund.case.id,
            action="stars",
        )
    assert admin_refund.lifecycle == []
    assert admin_refund.case.status == "requested"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["telegram_stars", "store_credit"])
async def test_manual_proof_does_not_bypass_stars_or_credit_refund_path(
    admin_refund,
    provider,
):
    """Manual bank evidence cannot replace a provider or wallet refund."""
    admin_refund.purchase.order.provider = provider
    admin_refund.purchase.session.commit()
    with pytest.raises(PaymentRejected):
        await resolve(
            admin_refund, action="manual", reference="some-bank-proof"
        )
    assert admin_refund.case.status == "requested"
    assert admin_refund.lifecycle == []


@pytest.mark.asyncio
async def test_origin_client_closes_when_unknown_digital_send_blocks_refund(
    admin_refund,
):
    """An existing sending claim rejects refunds and closes the client."""
    refund = admin_refund
    refund.purchase.delivery.state = "sending"
    refund.purchase.session.commit()
    with pytest.raises(PaymentRejected):
        await resolve(refund)
    assert refund.provider.calls == []
    assert refund.case.status == "requested"
    assert [entry[0] for entry in refund.lifecycle] == ["opened", "closed"]
