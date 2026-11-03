"""Offline regression for Next.js admin mutations and permission invariants.

All database records are disposable SQLite objects. No bot is started, no
provider is called, no migration is applied, and no real media is uploaded.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from dashboard.admin_control_api import StaffUpdate, change_staff
from services.shop_admin_security import SecurityRejected
from dashboard.next_operations import (
    BaleMediaPrepareDecision,
    MediaPatch,
    OrderReviewDecision,
    ReferralPolicyPatch,
    TestimonialPatch,
    WalletAdjustment,
    bounded_number,
    positive_id,
    prepare_bale_broadcast_media,
    review_unpaid_order,
    upload_media,
)
from models.base import Base
from models.shop_checkout import ShopCoupon, ShopOrderLine, ShopOrderReviewAudit
from models.shop_content import Product, ShopCategory, ShopOrder
from models.shop_staff import ShopStaff


class OfflineDB:
    """Expose only the async-compatible SQLAlchemy operations under test."""

    def __init__(self, session: Session) -> None:
        """Keep a single isolated SQLite transaction."""
        self.session = session

    async def scalar(self, statement):
        """Execute one ORM scalar expression."""
        return self.session.scalar(statement)

    async def execute(self, statement):
        """Execute one SQL statement."""
        return self.session.execute(statement)

    async def scalars(self, statement):
        """Return ORM scalar rows, preserving the backing SQLite session."""
        return self.session.scalars(statement)

    async def commit(self):
        """Commit the disposable SQLite transaction."""
        self.session.commit()

    def add(self, entity) -> None:
        """Enlist one SQLAlchemy record."""
        self.session.add(entity)


@pytest.fixture
def db():
    """Create isolated tables for admin actions without external services."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ShopCategory.__table__,
            Product.__table__,
            ShopCoupon.__table__,
            ShopOrder.__table__,
            ShopOrderLine.__table__,
            ShopOrderReviewAudit.__table__,
            ShopStaff.__table__,
        ],
    )
    with Session(engine) as session:
        yield OfflineDB(session)
    engine.dispose()


def test_positive_ids_and_position_validation() -> None:
    """Reject paths and invalid numbers before database access."""
    assert positive_id("12") == 12
    assert bounded_number("1000000") == 1_000_000
    for value in ("0", "-4", "whatever", None):
        with pytest.raises(HTTPException) as denied:
            positive_id(value)
        assert denied.value.status_code == 422
    for value in ("-1", "1000001", "not-a-number"):
        with pytest.raises(HTTPException):
            bounded_number(value)


def test_sensitive_payload_validation() -> None:
    """Reject malformed paid controls, approval flags and media metadata."""
    with pytest.raises(ValidationError):
        WalletAdjustment.model_validate({
            "platform": "bale", "user_id": 5, "amount_irr": 0,
            "direction": "credit", "reason": "Valid reason 12 letters",
            "operation_id": str(uuid4()), "confirmation": "CREDIT_CONFIRMED",
        })
    with pytest.raises(ValidationError):
        ReferralPolicyPatch.model_validate({
            "is_enabled": True, "percent": 31,
            "min_order_irr": 100, "max_bonus_irr": 200,
        })
    with pytest.raises(ValidationError):
        MediaPatch(position=1_000_001)
    with pytest.raises(ValidationError):
        TestimonialPatch(text="x" * 2001)
    with pytest.raises(ValidationError):
        StaffUpdate(password="weak", confirmation="UPDATE_STAFF")


@pytest.mark.asyncio
async def test_upload_and_bale_prepare_reject_unprivileged_role() -> None:
    """Neither a signed HMAC nor an allowed path confers marketing powers."""
    with pytest.raises(HTTPException) as denied:
        await upload_media(
            "campaign", request=object(), staff=SimpleNamespace(role="content"),
            session=object(),
        )
    assert denied.value.status_code == 403

    with pytest.raises(HTTPException) as denied:
        await prepare_bale_broadcast_media(
            1, BaleMediaPrepareDecision(confirmation="PREPARE_BALE_MEDIA"),
            request=object(), staff=SimpleNamespace(role="sales"),
            session=object(),
        )
    assert denied.value.status_code == 403


def _order(db: OfflineDB, *, stock: int, published: bool = True) -> ShopOrder:
    """Build one real, unpaid order with its immutable product snapshot."""
    product = Product(
        sku="MANUAL-STOCK", name="Catalog test", description="Safe item",
        price=1_000, stock_quantity=stock, is_published=published,
    )
    db.add(product)
    db.session.flush()
    order = ShopOrder(
        platform="bale", platform_user_id=42, chat_id=42,
        product_id=product.id, product_name_snapshot=product.name,
        quantity=2, unit_price_irr=1000, total_irr=2000,
        provider="manual_review", status="pending_review",
        invoice_payload=uuid4().hex,
    )
    db.add(order)
    db.session.flush()
    db.add(ShopOrderLine(
        order_id=order.id, product_id=product.id,
        product_name_snapshot=product.name, sku_snapshot=product.sku,
        unit_price_irr=1000, quantity=2, total_irr=2000,
    ))
    db.session.commit()
    return order


@pytest.mark.asyncio
async def test_manual_accept_remains_unpaid_and_is_audited(db: OfflineDB) -> None:
    """Only an unpaid decision changes; provider/stock remain unchanged."""
    order = _order(db, stock=10)
    actor = SimpleNamespace(id=7, role="sales")
    outcome = await review_unpaid_order(
        order.id,
        OrderReviewDecision(decision="accept", confirmation="ACCEPT_UNPAID_ORDER"),
        actor, db,
    )
    assert outcome["status"] == "approved_unpaid"
    assert order.provider == "manual_review"
    assert order.status == "approved_unpaid"
    assert db.session.get(Product, order.product_id).stock_quantity == 10

    with pytest.raises(HTTPException) as repeated:
        await review_unpaid_order(
            order.id,
            OrderReviewDecision(decision="accept", confirmation="ACCEPT_UNPAID_ORDER"),
            actor, db,
        )
    assert repeated.value.status_code == 409

    second = await review_unpaid_order(
        order.id,
        OrderReviewDecision(decision="reject", confirmation="REJECT_UNPAID_ORDER"),
        actor, db,
    )
    assert second["status"] == "cancelled"
    audits = db.session.scalars(
        select(ShopOrderReviewAudit).where(
            ShopOrderReviewAudit.order_id == order.id
        )
    ).all()
    assert [audit.action for audit in audits] == ["accept", "reject"]


@pytest.mark.asyncio
async def test_manual_order_denies_insufficient_stock(db: OfflineDB) -> None:
    """Do not accept an unpublished or understocked manual order."""
    order = _order(db, stock=1)
    with pytest.raises(HTTPException) as denied:
        await review_unpaid_order(
            order.id,
            OrderReviewDecision(decision="accept", confirmation="ACCEPT_UNPAID_ORDER"),
            SimpleNamespace(id=7, role="sales"), db,
        )
    assert denied.value.status_code == 409
    assert order.status == "pending_review"


@pytest.mark.asyncio
async def test_cannot_disable_last_superadmin(db: OfflineDB) -> None:
    """Protect the only active superadmin from accidental lockout."""
    member = ShopStaff(
        username="owner", role="superadmin",
        password_hash="offline-not-a-real-hash", is_active=True,
        session_version=1,
    )
    db.add(member)
    await db.commit()
    with pytest.raises(SecurityRejected) as denied:
        await change_staff(
            member.id,
            StaffUpdate(
                is_active=False,
            ),
            SimpleNamespace(id=member.id, role="superadmin"), db,
        )
    assert denied.value.status == 409
    assert member.is_active is True
    assert member.session_version == 1
