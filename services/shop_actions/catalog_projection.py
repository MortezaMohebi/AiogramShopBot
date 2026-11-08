"""Pure scalar display derived only from an already authorized catalog page."""

from __future__ import annotations


def search_display(page: dict) -> str:
    """Render a bounded plain-text preview without another catalog lookup."""
    items = page["items"]
    if not items:
        return "محصولی پیدا نشد."
    lines = ["نتیجه‌های این صفحه:"]
    for item in items[:5]:
        name = item["name"][:240]
        unit = item["uom"]["name"][:80]
        lines.append(f"{name} — {item['price_irr']:,} ریال / {unit}")
    if len(items) > 5 or page["has_more"]:
        lines.append("نتیجه‌های بیشتری موجود است.")
    return "\n".join(lines)[:4000]
