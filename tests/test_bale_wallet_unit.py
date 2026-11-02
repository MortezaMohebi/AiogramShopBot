"""Provider-independent Bale payment behavior against isolated SQLite data.

These tests use a fake transport and database. No actual payment is made.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models.base import Base
from models.shop_content import Product, ShopCategory, ShopOrder
from services.bale_wallet import BaleWalletService, CheckoutRejected
from services.shop_money import to_rials


class AsyncSessionAdapter:
    """Adapt isolated synchronous SQLAlchemy sessions for async service tests."""

    def __init__(self, session: Session):
        """Keep a session owning a disposable in-memory database."""
        self.session = session

    def add(self, record):
        """Stage a new database record."""
        self.session.add(record)

    async def scalar(self, statement):
        """Return a scalar from a real SQLite query."""
        return self.session.scalar(statement)

    async def execute(self, statement):
        """Execute one statement in the current transaction."""
        return self.session.execute(statement)

    async def refresh(self, record):
        """Reload the committed order."""
        self.session.refresh(record)

    async def commit(self):
        """Commit a test transaction."""
        self.session.commit()


class FakeBaleWallet:
    """Record native invoices and simulate verified Bale transactions."""

    def __init__(self):
        """Initialize empty calls and an unset transaction receipt."""
        self.invoices = []
        self.evidence = None

    async def send_invoice(self, **kwargs):
        """Record the invoice without contacting the payment provider."""
        self.invoices.append(kwargs)

    async def inquire_transaction(self, transaction_id):
        """Return a fixture representing a paid provider transaction."""
        return self.evidence


@pytest.fixture
def db():
    """Create only the relevant new shop tables in disposable SQLite memory."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ShopCategory.__table__,
            Product.__table__,
            ShopOrder.__table__,
        ],
    )
    with Session(engine) as session:
        yield AsyncSessionAdapter(session)
    engine.dispose()


@pytest.mark.asyncio
async def test_invoice_is_in_integer_rials_and_never_paid_on_send(db):
    """A successful sendInvoice is not evidence of payment."""
    product = Product(
        name="محصول تست", sku="TEST", description="توضیح", price=125000,
        stock_quantity=2, is_published=True,
    )
    db.add(product)
    await db.commit()
    gateway = FakeBaleWallet()
    order = await BaleWalletService.create_invoice(
        db, gateway, product_id=product.id,
        platform_user_id=101, chat_id=101,
        provider_token="WALLET-TEST-1111111111111111",
    )
    assert order.status == "pending_payment"
    assert gateway.invoices[0]["amount_irr"] == 125000
    assert gateway.invoices[0]["payload"] == order.invoice_payload
    assert len(order.invoice_payload.encode()) <= 128


@pytest.mark.asyncio
async def test_precheckout_checks_exact_user_amount_and_currency(db):
    """Reject wrong currency, wrong payer and mismatched totals."""
    db.add(Product(
        name="محصول", sku="PR", description="توضیح", price=1000,
        stock_quantity=1, is_published=True,
    ))
    await db.commit()
    gateway = FakeBaleWallet()
    order = await BaleWalletService.create_invoice(
        db, gateway, product_id=1, platform_user_id=101, chat_id=101,
        provider_token="demo",
    )
    query = {
        "from": {"id": 101},
        "currency": "IRR",
        "total_amount": 1000,
        "invoice_payload": order.invoice_payload,
    }
    assert (await BaleWalletService.validate_pre_checkout(db, query))[0]
    assert not (await BaleWalletService.validate_pre_checkout(
        db, {**query, "currency": "USD"}
    ))[0]
    assert not (await BaleWalletService.validate_pre_checkout(
        db, {**query, "total_amount": 999}
    ))[0]
    assert not (await BaleWalletService.validate_pre_checkout(
        db, {**query, "from": {"id": 202}}
    ))[0]


@pytest.mark.asyncio
async def test_paid_receipt_is_idempotent_and_stock_deducted_once(db):
    """Verify provider evidence and ignore replayed successful_payment."""
    db.add(Product(
        name="محصول", sku="P1", description="متن", price=100,
        stock_quantity=2, is_published=True,
    ))
    await db.commit()
    gateway = FakeBaleWallet()
    order = await BaleWalletService.create_invoice(
        db, gateway, product_id=1,
        platform_user_id=101, chat_id=101,
        provider_token="demo",
    )
    gateway.evidence = {
        "id": "transaction-1",
        "status": "paid",
        "userID": 101,
        "amount": 100,
    }
    receipt = {
        "currency": "IRR",
        "total_amount": 100,
        "invoice_payload": order.invoice_payload,
        "telegram_payment_charge_id": "transaction-1",
        "provider_payment_charge_id": "provider-charge-1",
    }
    record, changed = await BaleWalletService.confirm_success(
        db, gateway, payer_id=101, chat_id=101, payment=receipt
    )
    assert changed
    assert record.status == "paid"
    assert (await db.scalar(
        __import__("sqlalchemy").select(Product.stock_quantity)
    )) == 1
    repeat, changed = await BaleWalletService.confirm_success(
        db, gateway, payer_id=101, chat_id=101, payment=receipt
    )
    assert not changed
    assert repeat.id == record.id
    assert (await db.scalar(
        __import__("sqlalchemy").select(Product.stock_quantity)
    )) == 1
    with pytest.raises(CheckoutRejected):
        await BaleWalletService.confirm_success(
            db, gateway, payer_id=101, chat_id=101,
            payment={**receipt, "total_amount": 99}
        )


@pytest.mark.asyncio
async def test_payer_cannot_see_other_platform_orders(db):
    """Never match Telegram and Bale users by raw numeric ID alone."""
    db.add(Product(
        name="محصول", sku="P2", description="متن", price=100,
        stock_quantity=3, is_published=True,
    ))
    await db.commit()
    wallet = FakeBaleWallet()
    await BaleWalletService.create_invoice(
        db, wallet, product_id=1, platform_user_id=101, chat_id=101,
        provider_token="demo",
    )
    assert "در انتظار پرداخت" in await BaleWalletService.list_orders(
        db, platform="bale", platform_user_id=101
    )
    assert "هنوز سفارشی" in await BaleWalletService.list_orders(
        db, platform="telegram", platform_user_id=101
    )
