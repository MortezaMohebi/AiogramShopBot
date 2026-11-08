"""Deployment-wide operator choices for shared services."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopServiceControl(Base):
    """A versioned override of the deployment default for a known service."""

    __tablename__ = "shop_service_controls"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_shop_service_control_version"),
    )

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
