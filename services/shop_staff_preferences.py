"""Validated persistence for personal work-notification preferences."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.shop_staff_preferences import ShopStaffPreferences
from services import shop_admin_security as security


def for_user(db: Session, staff_id: int) -> ShopStaffPreferences:
    """Read the user's effective display preferences without creating a row."""
    row = db.scalar(select(ShopStaffPreferences).where(
        ShopStaffPreferences.staff_id == staff_id,
    ))
    return row or ShopStaffPreferences(
        staff_id=staff_id, language="fa", calendar="auto",
        notify_orders=True, notify_campaigns=True,
        notify_finance=True, notify_system=True,
    )


def update(
    db: Session, staff_id: int, *, language: str, calendar: str,
    notify_orders: bool, notify_campaigns: bool, notify_finance: bool,
    notify_system: bool,
) -> None:
    """Save only noncritical options while maintaining security notifications."""
    if language not in {"fa", "en"} or calendar not in {
        "auto", "jalali", "gregorian",
    }:
        raise security.SecurityRejected("invalid_request", 422)
    query = select(ShopStaffPreferences).where(
        ShopStaffPreferences.staff_id == staff_id,
    ).with_for_update()
    row = db.scalar(query)
    if row is None:
        row = ShopStaffPreferences(staff_id=staff_id)
        db.add(row)
    row.language = language
    row.calendar = calendar
    row.notify_orders = notify_orders
    row.notify_campaigns = notify_campaigns
    row.notify_finance = notify_finance
    row.notify_system = notify_system
    security.audit(db, staff_id, "account.preferences_updated")


def serialize(row: ShopStaffPreferences) -> dict:
    """Return a safe serialized view of the user's work preferences."""
    return {
        "language": row.language,
        "calendar": row.calendar,
        "notify_orders": row.notify_orders,
        "notify_campaigns": row.notify_campaigns,
        "notify_finance": row.notify_finance,
        "notify_system": row.notify_system,
    }
