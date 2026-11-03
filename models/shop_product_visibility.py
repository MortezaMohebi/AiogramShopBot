"""Merchant-controlled optional customer display fields for each product.

No columns are added to existing product or order tables. Missing policy rows
mean visible, preserving customer experience for existing catalogue records.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopProductVisibility(Base):
    """Four independent optional public-facing display choices."""

    __tablename__ = "shop_product_visibility"

    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shop_products.id", ondelete="CASCADE"),
        primary_key=True,
    )
    show_description: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    show_stock: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    show_media: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    show_reviews: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
