"""Exercise digital authorization against real local payment and asset rows."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import config
import db
from models.shop_checkout import ShopOrderLine
from models.shop_content import Product, ShopOrder
from models.shop_customer_support import ShopOrderFulfillment
from models.shop_digital_delivery import ShopDigitalAsset, ShopDigitalDelivery
from models.shop_multibot import ShopBot, ShopStore
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
from services.shop_digital_fulfillment import claim_one_delivery
from tests.schema_support import create_shop_schema, seed_test_units


class OfflineSession:
    """Run the production authorization queries in a disposable SQL database."""

    def __init__(self, session: Session) -> None:
        """Keep one local session for the claim transaction."""
        self.session = session

    async def scalar(self, query):
        """Evaluate the real ORM authorization query."""
        return self.session.scalar(query)

    async def get(self, model, key, **kwargs):
        """Load an actual order, asset, owner or payment-related row."""
        return self.session.get(model, key, **kwargs)

    async def commit(self) -> None:
        """Make the claimed or blocked delivery durable locally."""
        self.session.commit()

    async def flush(self) -> None:
        """Flush a confirmed receipt before aggregate fulfillment checks."""
        self.session.flush()

    def add(self, record) -> None:
        """Stage the real append-only fulfillment event."""
        self.session.add(record)


@pytest.fixture
def purchase(monkeypatch, tmp_path):
    """Provide one exact paid order bound to an older private asset version."""
    private = tmp_path / "private"
    private.mkdir()
    monkeypatch.setattr(config, "SHOP_DIGITAL_ROOT", str(private))
    monkeypatch.setattr(config, "SHOP_MEDIA_ROOT", str(tmp_path / "public"))
    content = b"%PDF-1.4 paid digital document"
    key = "b" * 32 + ".pdf"
    (private / key).write_bytes(content)
    store_id, bot_id, asset_id = (str(uuid4()) for _ in range(3))
    paid_at = datetime.now(timezone.utc)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_shop_schema(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(ShopStore(
            id=store_id, slug="digital-store", name="Store", state="active",
        ))
        bot = ShopBot(
            id=bot_id, store_id=store_id, slug="digital-bot", name="Bot",
            platform="telegram", runtime_owner="registry", status="active",
            version=1, credential_version=1,
        )
        session.add(bot)
        session.flush()
        seed_test_units(session)
        product = Product(
            store_id=store_id, sku="PRIVATE-DOCUMENT", name="Document",
            description="Paid private file", price=10000, price_stars=25,
            stock_quantity=1, requires_shipping=False,
            product_type="digital", digital_delivery_mode="file",
            is_published=True,
        )
        session.add(product)
        session.flush()
        order = ShopOrder(
            store_id=store_id, bot_id=bot_id, platform="telegram",
            platform_user_id=101, chat_id=101, product_id=product.id,
            product_name_snapshot="Document", quantity=1,
            unit_price_irr=10000, total_irr=10000,
            total_stars_snapshot=25, provider="telegram_stars", status="paid",
            invoice_payload="paid-private-file-payload",
            payment_currency="XTR", payment_amount=25,
            paid_at=paid_at, telegram_payment_charge_id="verified-charge",
        )
        asset = ShopDigitalAsset(
            id=asset_id, store_id=store_id, product_id=product.id,
            storage_key=key, original_filename="purchased.pdf",
            mime_type="application/pdf", size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(), active=False,
        )
        session.add_all([order, asset])
        session.flush()
        line = ShopOrderLine(
            order_id=order.id, product_id=product.id,
            product_name_snapshot="Document", sku_snapshot=product.sku,
            quantity=1, unit_price_irr=10000, total_irr=10000,
            unit_price_stars_snapshot=25,
            digital_asset_id_snapshot=asset_id,
        )
        session.add(line)
        session.flush()
        receipt = ShopPaymentAttempt(
            store_id=store_id, bot_id=bot_id, order_id=order.id,
            platform="telegram", provider="telegram_stars", currency="XTR",
            amount=25, payload="paid-private-file-payload", status="paid",
            completed_at=paid_at,
        )
        delivery = ShopDigitalDelivery(
            id=str(uuid4()), store_id=store_id, bot_id=bot_id,
            order_id=order.id, order_line_id=line.id, product_id=product.id,
            platform_user_id=101, chat_id=101, unit_index=0,
            kind="file", asset_id=asset_id, state="queued",
        )
        session.add_all([receipt, delivery])
        fulfillment = ShopOrderFulfillment(
            store_id=store_id, order_id=order.id,
            kind="digital", status="processing", version=1,
        )
        session.add(fulfillment)
        session.commit()
        yield SimpleNamespace(
            session=session, db=OfflineSession(session), bot=bot,
            order=order, receipt=receipt, delivery=delivery,
            line=line, asset=asset, path=private / key,
            fulfillment=fulfillment,
        )
    engine.dispose()


@pytest.mark.asyncio
async def test_exact_paid_receipt_can_claim_the_purchased_private_version(purchase):
    """Replacing an active catalog file cannot break the old paid snapshot."""
    send = await claim_one_delivery(purchase.db, bot_id=purchase.bot.id)
    assert send is not None
    assert send.asset_path == purchase.path
    assert send.chat_id == 101
    assert purchase.delivery.state == "sending"
    assert purchase.delivery.claimed_at is not None
    assert await claim_one_delivery(purchase.db, bot_id=purchase.bot.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", 24),
        ("currency", "IRR"),
        ("platform", "bale"),
        ("payload", "another-invoice-payload"),
        ("completed_at", None),
    ],
)
async def test_mismatched_paid_receipt_cannot_claim_private_file(
    purchase, field, value,
):
    """A paid flag alone never substitutes for the exact settled invoice."""
    setattr(purchase.receipt, field, value)
    purchase.session.commit()
    assert await claim_one_delivery(purchase.db, bot_id=purchase.bot.id) is None
    assert purchase.delivery.state == "blocked"
    assert purchase.delivery.claimed_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["tampered", "symlink", "wrong_version"])
async def test_invalid_private_asset_is_blocked_before_worker_send(
    purchase, tmp_path, mutation,
):
    """Integrity, direct-file ownership and the purchased version stay required."""
    if mutation == "tampered":
        # Keep the size unchanged so this specifically exercises SHA-256.
        purchase.path.write_bytes(b"x" * purchase.asset.size_bytes)
    elif mutation == "symlink":
        outside = tmp_path / "outside-private-file.pdf"
        outside.write_bytes(purchase.path.read_bytes())
        purchase.path.unlink()
        purchase.path.symlink_to(outside)
    else:
        purchase.line.digital_asset_id_snapshot = str(uuid4())
        purchase.session.commit()

    assert await claim_one_delivery(purchase.db, bot_id=purchase.bot.id) is None
    assert purchase.delivery.state == "blocked"
    assert purchase.delivery.claimed_at is None


@pytest.fixture
def worker(monkeypatch, purchase):
    """Use the real digital worker with a disposable local session factory."""
    monkeypatch.setattr(db, "engine", SimpleNamespace(), raising=False)
    module = importlib.import_module("workers.shop_digital_delivery")

    @asynccontextmanager
    async def session_maker():
        """Model AsyncSession context cleanup after failed completion writes."""
        try:
            yield purchase.db
        finally:
            purchase.session.rollback()

    monkeypatch.setattr(module, "session_maker", session_maker)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "expected_state"),
    [
        ("confirmed", "delivered"),
        ("timeout", "needs_review"),
        ("cancelled", "sending"),
        ("invalid_receipt", "sending"),
    ],
)
async def test_worker_commits_before_send_and_never_replays_unknown_outcomes(
    purchase, worker, monkeypatch, outcome, expected_state,
):
    """Only a confirmed receipt completes fulfillment; all claims stay one-shot."""
    sends = []

    class Provider:
        """A provider boundary fake that can accept before losing its response."""

        async def deliver_digital(self, payload):
            """Observe a committed claim before simulating the remote result."""
            with Session(purchase.session.bind) as observer:
                claim = observer.get(ShopDigitalDelivery, payload.delivery_id)
                assert claim.state == "sending"
                assert claim.claimed_at is not None
            assert payload.asset_path.read_bytes().startswith(b"%PDF-")
            sends.append(payload.delivery_id)
            if outcome == "timeout":
                raise asyncio.TimeoutError("Fake provider accepted, reply lost.")
            if outcome == "cancelled":
                raise asyncio.CancelledError()
            return "202" if outcome == "confirmed" else ""

    @asynccontextmanager
    async def transport_for_bot(bot_id):
        """Keep the worker's server-selected Bot bound to the fake provider."""
        assert bot_id == purchase.bot.id
        yield Provider()

    monkeypatch.setattr(worker, "_transport_for_bot", transport_for_bot)
    if outcome == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await worker._deliver_one(purchase.bot.id)
    else:
        assert await worker._deliver_one(purchase.bot.id) is True

    purchase.session.refresh(purchase.delivery)
    purchase.session.refresh(purchase.fulfillment)
    assert purchase.delivery.state == expected_state
    if outcome == "confirmed":
        assert purchase.delivery.provider_message_id == "202"
        assert purchase.fulfillment.status == "delivered"
        assert purchase.fulfillment.version == 2
    else:
        assert purchase.delivery.provider_message_id is None
        assert purchase.fulfillment.status == "processing"
        assert purchase.fulfillment.version == 1
    assert await worker._deliver_one(purchase.bot.id) is False
    assert sends == [purchase.delivery.id]


@pytest.mark.asyncio
async def test_disabled_worker_waits_for_activation_without_claiming_or_sending(
    worker, monkeypatch, purchase,
):
    """The idle worker watches controls but never claims or sends a delivery."""
    monkeypatch.setattr(config, "SHOP_DIGITAL_DELIVERY_ENABLED", False)

    async def forbidden(*args, **kwargs):
        """Fail if disabled startup crosses an external boundary."""
        raise AssertionError("Disabled worker must not start work.")

    started = []

    async def prepare():
        started.append("schema")

    @asynccontextmanager
    async def watch(_factory):
        started.append("controls")
        yield

    async def stop_after_idle(waiter, *, timeout):
        waiter.close()
        raise asyncio.CancelledError

    async def dispose():
        started.append("disposed")

    monkeypatch.setattr(worker, "create_db_and_tables", prepare)
    monkeypatch.setattr(worker, "watch_controls", watch)
    monkeypatch.setattr(worker, "engine", SimpleNamespace(dispose=dispose))
    monkeypatch.setattr(worker.asyncio, "wait_for", stop_after_idle)
    monkeypatch.setattr(worker, "_pending_bot_ids", forbidden)
    monkeypatch.setattr(worker, "_deliver_one", forbidden)
    with pytest.raises(asyncio.CancelledError):
        await worker.main()
    assert started == ["schema", "controls", "disposed"]
    assert purchase.delivery.claimed_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["invoice_sent", "refunded"])
async def test_unsettled_or_refunded_receipt_cannot_claim_private_file(
    purchase, status,
):
    """Invoice dispatch and a previously paid refund never unlock the file."""
    purchase.receipt.status = status
    purchase.session.commit()
    assert await claim_one_delivery(purchase.db, bot_id=purchase.bot.id) is None
    assert purchase.delivery.state == "blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["provider_pending", "confirmed"])
async def test_pending_or_confirmed_provider_refund_blocks_delivery(
    purchase, status,
):
    """An already attempted provider refund blocks a new private-file claim."""
    purchase.session.add(ShopRefundCase(
        order_id=purchase.order.id, status=status,
        reason="Provider refund in progress", actor="staff:1",
    ))
    purchase.session.commit()
    assert await claim_one_delivery(purchase.db, bot_id=purchase.bot.id) is None
    assert purchase.delivery.state == "blocked"
