"""Digital SKU configuration and paid-only delivery schema invariants."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models.base import Base
from models.shop_digital_delivery import (
    ShopDigitalAsset, ShopDigitalLicense, ShopDigitalDelivery,
)


def test_digital_tables_have_nonnullable_store_and_bot_owner_columns():
    """File access and claim receipts must be tenant- and Bot-owned."""
    for model in (ShopDigitalAsset, ShopDigitalLicense, ShopDigitalDelivery):
        assert not model.__table__.c.store_id.nullable
    assert not ShopDigitalDelivery.__table__.c.bot_id.nullable
    assert not ShopDigitalDelivery.__table__.c.order_id.nullable
    assert not ShopDigitalDelivery.__table__.c.order_line_id.nullable


def test_delivery_kind_never_accepts_both_file_and_license():
    """A single message must have exactly one authorized asset source."""
    names = {item.name for item in ShopDigitalDelivery.__table__.constraints}
    assert "ck_shop_digital_delivery_source" in names
    assert "uq_shop_digital_one_delivery_per_unit" in names
