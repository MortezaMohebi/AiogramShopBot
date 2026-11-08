"""Sequential refund/claim behavior and emitted transaction orchestration.

SQLite does not implement PostgreSQL row locks. These tests check the real
service behavior, identity-map refresh and SQLAlchemy lock requests; actual
concurrent lock waiting is validated by the PostgreSQL acceptance scenario.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import event, update
from sqlalchemy.orm import Session

from models.shop_content import ShopOrder
from models.shop_digital_delivery import ShopDigitalDelivery
from models.shop_payment import ShopRefundCase
from services.shop_digital_fulfillment import claim_one_delivery
from services.shop_payments import PaymentRejected
from services.shop_refunds import ShopRefundService
from tests.test_beta_digital_fulfillment import purchase  # noqa: F401


class StarsProvider:
    """Record a refund boundary without constructing a Bot or network client."""

    def __init__(self, purchase, case_id, *, outcome=True) -> None:
        """Retain the local DB only to observe durable pending state."""
        self.purchase = purchase
        self.case_id = case_id
        self.outcome = outcome
        self.calls = []

    async def refund_star_payment(self, **kwargs):
        """Verify that provider-pending is committed before external work."""
        with Session(self.purchase.session.bind) as observer:
            case = observer.get(ShopRefundCase, self.case_id)
            assert case.status == "provider_pending"
        self.calls.append(kwargs)
        return self.outcome


@pytest.fixture
def refund_case(purchase):
    """Create a requested case while retaining its cached ORM identity."""
    case = ShopRefundCase(
        order_id=purchase.order.id, status="requested",
        actor="staff:1", reason="Customer-approved refund",
    )
    purchase.session.add(case)
    purchase.session.commit()
    return case


@contextmanager
def emitted_selects(session):
    """Capture actual ORM execution requests, including lock and refresh flags."""
    queries = []

    def record(execution):
        """Observe the query sent to the real local database."""
        if execution.is_select:
            statement = execution.statement
            queries.append((
                statement.column_descriptions[0].get("entity"),
                statement._for_update_arg is not None,
                execution.execution_options.get("populate_existing", False),
            ))

    event.listen(session, "do_orm_execute", record)
    try:
        yield queries
    finally:
        event.remove(session, "do_orm_execute", record)


@pytest.mark.asyncio
async def test_claim_locks_delivery_then_the_shared_order(purchase):
    """The claim transaction emits the same Order lock used by refunds."""
    with emitted_selects(purchase.session) as queries:
        send = await claim_one_delivery(purchase.db, bot_id=purchase.bot.id)
    assert send is not None
    locked = [entity for entity, lock, _ in queries if lock]
    assert locked[:2] == [ShopDigitalDelivery, ShopOrder]


@pytest.mark.asyncio
async def test_claim_reloads_order_state_after_an_earlier_paid_read(purchase):
    """A cached paid identity must not unlock a now-unfulfilled order."""
    assert purchase.order.status == "paid"
    with Session(purchase.session.bind) as writer:
        writer.execute(update(ShopOrder).where(
            ShopOrder.id == purchase.order.id,
        ).values(status="paid_unfulfilled"))
        writer.commit()

    # Retain the earlier ORM object deliberately: default SELECT/get behavior
    # does not refresh its attributes in an expire_on_commit=False session.
    assert purchase.order.status == "paid"
    assert await claim_one_delivery(purchase.db, bot_id=purchase.bot.id) is None
    assert purchase.delivery.state == "blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery_state", ["sending", "needs_review"])
async def test_unknown_digital_delivery_blocks_new_stars_refund(
    purchase, refund_case, delivery_state,
):
    """Never refund through the provider while its digital send is uncertain."""
    purchase.delivery.state = delivery_state
    purchase.session.commit()
    provider = StarsProvider(purchase, refund_case.id)
    with pytest.raises(PaymentRejected):
        await ShopRefundService.refund_stars(
            purchase.db, case_id=refund_case.id, bot=provider,
            enabled=True, reviewer="staff:1",
        )
    assert provider.calls == []
    assert refund_case.status == "requested"
    assert purchase.order.status == "paid"
    assert purchase.receipt.status == "paid"


@pytest.mark.asyncio
async def test_refund_after_committed_claim_stops_before_provider(
    purchase, refund_case,
):
    """A sequential claim-first handoff prevents a new refund request."""
    assert await claim_one_delivery(purchase.db, bot_id=purchase.bot.id)
    provider = StarsProvider(purchase, refund_case.id)
    with pytest.raises(PaymentRejected):
        await ShopRefundService.refund_stars(
            purchase.db, case_id=refund_case.id, bot=provider,
            enabled=True, reviewer="staff:1",
        )
    assert provider.calls == []
    assert purchase.delivery.state == "sending"
    assert refund_case.status == "requested"


@pytest.mark.asyncio
async def test_refund_refreshes_case_order_and_does_not_lock_delivery(
    purchase, refund_case,
):
    """Case -> Order locks and an unlocked delivery read avoid a lock cycle."""
    provider = StarsProvider(purchase, refund_case.id, outcome=False)
    with emitted_selects(purchase.session) as queries:
        with pytest.raises(PaymentRejected):
            await ShopRefundService.refund_stars(
                purchase.db, case_id=refund_case.id, bot=provider,
                enabled=True, reviewer="staff:1",
            )
    locked = [entity for entity, lock, _ in queries if lock]
    assert locked == [ShopRefundCase, ShopOrder]
    assert (ShopRefundCase, True, True) in queries
    assert (ShopOrder, True, True) in queries
    assert any(
        entity is ShopDigitalDelivery and lock is False
        for entity, lock, _ in queries
    )


@pytest.mark.asyncio
async def test_stale_requested_case_cannot_repeat_a_pending_provider_refund(
    purchase, refund_case,
):
    """Refresh a cached case before deciding whether a provider call is new."""
    with Session(purchase.session.bind) as writer:
        writer.execute(update(ShopRefundCase).where(
            ShopRefundCase.id == refund_case.id,
        ).values(status="provider_pending"))
        writer.commit()
    assert refund_case.status == "requested"
    provider = StarsProvider(purchase, refund_case.id)
    with pytest.raises(PaymentRejected):
        await ShopRefundService.refund_stars(
            purchase.db, case_id=refund_case.id, bot=provider,
            enabled=True, reviewer="staff:1",
        )
    assert provider.calls == []


@pytest.mark.asyncio
async def test_provider_pending_refund_prevents_a_later_claim(
    purchase, refund_case,
):
    """A sequential refund-first handoff blocks the still-queued document."""
    provider = StarsProvider(purchase, refund_case.id, outcome=False)
    with pytest.raises(PaymentRejected):
        await ShopRefundService.refund_stars(
            purchase.db, case_id=refund_case.id, bot=provider,
            enabled=True, reviewer="staff:1",
        )
    assert len(provider.calls) == 1
    assert refund_case.status == "provider_pending"
    assert await claim_one_delivery(purchase.db, bot_id=purchase.bot.id) is None
    assert purchase.delivery.state == "blocked"


@pytest.mark.asyncio
async def test_confirmed_delivery_can_be_explicitly_refunded(
    purchase, refund_case,
):
    """A known completed delivery does not prevent the approved refund flow."""
    purchase.delivery.state = "delivered"
    purchase.delivery.provider_message_id = "202"
    purchase.session.commit()
    provider = StarsProvider(purchase, refund_case.id)
    result = await ShopRefundService.refund_stars(
        purchase.db, case_id=refund_case.id, bot=provider,
        enabled=True, reviewer="staff:1",
    )
    assert result.status == "confirmed"
    assert purchase.order.status == "refunded"
    assert purchase.receipt.status == "refunded"
    assert provider.calls == [{
        "user_id": 101, "telegram_payment_charge_id": "verified-charge",
    }]


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery_state", ["sending", "needs_review"])
async def test_manual_external_refund_evidence_remains_recordable(
    purchase, refund_case, delivery_state,
):
    """Money already returned must stay auditable even with an unknown send."""
    purchase.order.provider = "telegram_fiat"
    purchase.order.payment_currency = "IRR"
    purchase.order.payment_amount = 10000
    purchase.receipt.provider = "telegram_fiat"
    purchase.receipt.currency = "IRR"
    purchase.receipt.amount = 10000
    purchase.delivery.state = delivery_state
    purchase.session.commit()
    result = await ShopRefundService.confirm_manual(
        purchase.db, case_id=refund_case.id,
        provider_reference="verified-external-refund", reviewer="staff:1",
    )
    assert result.status == "confirmed"
    assert result.provider_reference == "verified-external-refund"
    assert purchase.order.status == "refunded"
    assert purchase.receipt.status == "refunded"
    assert purchase.delivery.state == delivery_state
