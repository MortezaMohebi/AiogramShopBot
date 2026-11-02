"""Sanity checks for the Persian SQLAdmin integration."""

from pathlib import Path

from dashboard.persian import localize_model_view


ROOT = Path(__file__).resolve().parents[1]


def test_localized_model_view_does_not_add_unknown_columns():
    """Avoid attaching translated labels for nonexistent database fields."""
    class Example:
        name = object()
        price = object()

    class ItemAdmin:
        model = Example
        column_labels = {"name": "عنوان اختصاصی"}

    result = localize_model_view(ItemAdmin)
    assert result.name == "واحد موجودی"
    assert result.column_labels["name"] == "عنوان اختصاصی"
    assert result.column_labels["price"] == "قیمت"
    assert "status" not in result.column_labels


def test_persian_rtl_template_is_available():
    """Verify that SQLAdmin is provided a right-to-left document shell."""
    base = (ROOT / "templates/sqladmin/base.html").read_text(encoding="utf-8")
    assert '<html lang="fa" dir="rtl">' in base
    assert '/shop-assets/admin-rtl.css' in base


def test_persian_login_is_available():
    """Verify that the built-in login form is localized."""
    login = (ROOT / "templates/sqladmin/login.html").read_text(encoding="utf-8")
    assert "نام کاربری" in login
    assert "گذرواژه" in login
