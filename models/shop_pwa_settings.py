"""Deployment-wide installation appearance for the administrative PWA."""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopPwaSettings(Base):
    """Keep the public install identity separate from Store-owned bot branding."""

    __tablename__ = "shop_pwa_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    short_name: Mapped[str] = mapped_column(String(24), nullable=False)
    theme_color: Mapped[str] = mapped_column(String(7), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
