"""Insert optional, clearly labeled live Codespace demo catalog records.

Only a Codespace database is accepted. No customer identity, payment,
refund, message, recipient list or broadcast is fabricated.
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from db import session_maker
from models.shop_content import Product, ShopCategory
from models.shop_multibot import DEFAULT_STORE_ID, ShopStore, ShopBot
from models.shop_store_commerce import ShopStoreSettings
from models.shop_bot_catalog_acl import ShopBotProductRule
from services.shop_uom import seed_store_units
from scripts.codespace_bootstrap import safe_configuration
from models.shop_checkout import ShopShippingMethod


async def seed_demo() -> None:
    """Populate an explicit Store and two credential-free draft demo bots."""
    safe_configuration()
    if (
        os.getenv("POSTGRES_DB") != "shop_codespace"
        or os.getenv("DB_HOST") != "postgres"
    ):
        raise RuntimeError("This demo may only use the Codespace database.")

    async with session_maker() as session:
        if await session.get(ShopStore, DEFAULT_STORE_ID) is None:
            raise RuntimeError("Bootstrap the Codespace Store before seeding a demo.")
        await session.run_sync(lambda sync: seed_store_units(sync, DEFAULT_STORE_ID))
        demo_bot_ids = (
            ("telegram", "00000000-0000-4000-8000-000000000301"),
            ("bale", "00000000-0000-4000-8000-000000000302"),
        )
        for platform, bot_id in demo_bot_ids:
            if await session.get(ShopBot, bot_id) is None:
                session.add(ShopBot(
                    id=bot_id, store_id=DEFAULT_STORE_ID,
                    slug=f"codespace-demo-{platform}", name=f"Draft demo {platform}",
                    platform=platform, status="draft", runtime_owner="registry",
                    version=1,
                ))
        await session.flush()
        category = await session.scalar(
            select(ShopCategory).where(
                ShopCategory.store_id == DEFAULT_STORE_ID,
                ShopCategory.name == "محصولات آزمایشی Codespace"
            )
        )
        if category is None:
            category = ShopCategory(
                store_id=DEFAULT_STORE_ID, name="محصولات آزمایشی Codespace",
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
                select(Product).where(
                    Product.store_id == DEFAULT_STORE_ID, Product.sku == sku
                )
            )
            if existing is None:
                existing = Product(
                        store_id=DEFAULT_STORE_ID, sku=sku,
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
                session.add(existing)
                await session.flush()
            for _platform, bot_id in demo_bot_ids:
                if await session.get(ShopBotProductRule, (bot_id, existing.id)) is None:
                    session.add(ShopBotProductRule(
                        bot_id=bot_id, product_id=existing.id, effect="allow",
                    ))
        settings = await session.get(ShopStoreSettings, DEFAULT_STORE_ID)
        if settings is None:
            session.add(
                ShopStoreSettings(
                    store_id=DEFAULT_STORE_ID,
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
                ShopShippingMethod.store_id == DEFAULT_STORE_ID,
                ShopShippingMethod.name == "ارسال نمایشی Codespace"
            )
        )
        if shipping is None:
            session.add(
                ShopShippingMethod(
                    store_id=DEFAULT_STORE_ID, name="ارسال نمایشی Codespace",
                    price_irr=150_000,
                    position=0,
                    is_active=True,
                )
            )
        await session.commit()
        print(
            "Demo catalog and credential-free draft Registry bots ready. "
            "No messages, payments or broadcasts were sent."
        )


if __name__ == "__main__":
    asyncio.run(seed_demo())
