"""Catch syntax errors before importing transport dependencies or credentials."""

import ast
from pathlib import Path


def test_telegram_transport_source_compiles():
    """The runtime transport policy must remain importable Python source."""
    source = Path(__file__).resolve().parents[1] / "services/shop_telegram_transport.py"
    ast.parse(source.read_text(encoding="utf-8"), filename=str(source))


def test_customer_credit_index_is_registered():
    """Importing the credit ORM must preserve shared-customer uniqueness."""
    from models.shop_engagement import ShopWalletAccount

    indexes = {index.name: index for index in ShopWalletAccount.__table__.indexes}
    assert indexes["uq_shop_wallet_shared_customer"].unique is True


def test_registered_models_have_resolvable_relationships():
    """All application mappers must initialize together in full-suite runs."""
    from sqlalchemy.orm import configure_mappers

    configure_mappers()
