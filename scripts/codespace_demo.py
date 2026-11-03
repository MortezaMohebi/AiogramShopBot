"""Insert optional, clearly labeled live Codespace demo catalog records.

Only a Codespace database is accepted. No customer identity, payment,
refund, message, recipient list or broadcast is fabricated.
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from db import session_maker
from models.shop_content import Product, ShopCategory, ShopSettings
from models.shop_checkout import ShopShippingMethod


async def seed_demo() -> None:
    """Populate two published products for real Telegram/Bale catalog testing."""
    if (
        os.getenv("POSTGRES_DB") != "shop_codespace"
        or os.getenv("DB_HOST") != "postgres"
    ):
        raise RuntimeError("This demo may only use the Codespace database.")

    async with session_maker() as session:
        category = await session.scalar(
            select(ShopCategory).where(
                ShopCategory.name == "محصولات آزمایشی Codespace"
            )
        )
        if category is None:
            category = ShopCategory(
                name="محصولات آزمایشی Codespace",
                position=0,
                is_published=True,
            )
            session.add(category)
            await session.flush()

        for sku, name, price, product_type in (
            ("CSPACE-PHYSICAL-01", "کالای فیزیکی نمایشی", 990_000, "physical"),
            ("CSPACE-DIGITAL-02", "کالای دیجیتال نمایشی", 490_000, "digital"),
        ):
            existing = await session.scalar(
                select(Product).where(Product.sku == sku)
            )
            if existing is None:
                session.add(
                    Product(
                        sku=sku,
                        name=name,
                        category_id=category.id,
                        description=(
                            "فقط برای آزمایش کاتالوگ ربات تلگرام و بله؛ "
                            "سفارش واقعی ثبت نکنید."
                        ),
                        price=price,
                        stock_quantity=10,
                        product_type=product_type,
                        requires_shipping=product_type == "physical",
                        position=0 if product_type == "physical" else 1,
                        is_published=True,
                    )
                )
        settings = await session.get(ShopSettings, 1)
        if settings is None:
            session.add(
                ShopSettings(
                    id=1,
                    brand_name="فروشگاه تست Codespace",
                    welcome_message=(
                        "به محیط آزمایشی خوش آمدید. "
                        "پرداخت در این نسخه غیرفعال است."
                    ),
                    faq_text="این محیط مخصوص بررسی API تلگرام و بله است.",
                    support_url=None,
                )
            )

        shipping = await session.scalar(
            select(ShopShippingMethod).where(
                ShopShippingMethod.name == "ارسال نمایشی Codespace"
            )
        )
        if shipping is None:
            session.add(
                ShopShippingMethod(
                    name="ارسال نمایشی Codespace",
                    price_irr=150_000,
                    position=0,
                    is_active=True,
                )
            )
        await session.commit()
        print(
            "Demo catalog ready for /catalog (both platforms). "
            "No messages, payments or broadcasts were sent."
        )


if __name__ == "__main__":
    asyncio.run(seed_demo())
