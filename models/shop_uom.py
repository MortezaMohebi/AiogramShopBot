"""Reusable Store-scoped unit categories and exact rational UoM conversions.

Existing checkout and stock quantities are integral; Product sales units use
whole-unit increments until fractional cart/order quantities are migrated.
No floats are stored in conversion ratios or inventory accounting.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import (
    Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, String,
    UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


def default_unit_id(store_id: str) -> str:
    """Derive the stable default piece unit for one registered Store."""
    return str(uuid5(NAMESPACE_URL, f"aiogramshopbot:uom:{store_id}:piece"))


class ShopUomCategory(Base):
    """Units that can be converted only to others of the same dimension."""

    __tablename__ = "shop_uom_categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "store_id", "code", name="uq_shop_uom_category_store_code",
        ),
    )


class ShopUom(Base):
    """An exact ratio from one unit to its category reference unit.

    E.g. a pack of 12 pieces uses ratio_num=12, ratio_den=1; gram to
    kilogram uses 1/1000. A base unit always has ratio 1/1.
    """

    __tablename__ = "shop_uoms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_uom_categories.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    ratio_num: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    ratio_den: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    rounding: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=Decimal("1"),
        server_default="1",
    )
    is_reference: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )

    __table_args__ = (
        UniqueConstraint("store_id", "code", name="uq_shop_uom_store_code"),
        CheckConstraint(
            "ratio_num BETWEEN 1 AND 1000000000",
            name="ck_shop_uom_ratio_num",
        ),
        CheckConstraint(
            "ratio_den BETWEEN 1 AND 1000000000",
            name="ck_shop_uom_ratio_den",
        ),
        CheckConstraint("rounding > 0", name="ck_shop_uom_rounding"),
        CheckConstraint(
            "NOT is_reference OR (ratio_num = 1 AND ratio_den = 1)",
            name="ck_shop_uom_reference_ratio",
        ),
        Index(
            "uq_shop_uom_reference_category", "category_id", unique=True,
            postgresql_where=text("is_reference = true"),
            sqlite_where=text("is_reference = true"),
        ),
    )


def convert_quantity(
    quantity: Decimal, source: ShopUom, target: ShopUom,
    *, exact: bool = True,
) -> Decimal:
    """Convert safely within one Store and one UoM category.

    Reject nonrepresentable quantities instead of silently reducing stock
    or charging for fractional units unsupported by checkout.
    """
    if (
        source.store_id != target.store_id
        or source.category_id != target.category_id
    ):
        raise ValueError("UoM conversion requires the same Store/category.")
    try:
        value = Decimal(quantity)
        converted = (
            value * Decimal(source.ratio_num) * Decimal(target.ratio_den)
            / (Decimal(source.ratio_den) * Decimal(target.ratio_num))
        )
        increment = Decimal(target.rounding)
        multiple = converted / increment
    except (InvalidOperation, ZeroDivisionError, ValueError):
        raise ValueError("Invalid UoM quantity or conversion ratio.") from None
    if not converted.is_finite() or (exact and multiple != multiple.to_integral_value()):
        raise ValueError("Conversion loses required UoM precision.")
    return converted
