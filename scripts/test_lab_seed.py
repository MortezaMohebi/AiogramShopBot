"""Seed only synthetic Telegram/Bale storefront records in the test DB.

All identities are made up; no provider receipt, external wallet balance,
live message, actual customer information or payment is generated.
Rerunning this script preserves existing test edits and avoids duplicates.
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from scripts.test_lab_app import require_isolated_lab

require_isolated_lab()

from db import session_maker  # noqa: E402
from models.shop_checkout import (  # noqa: E402
    ShopCoupon,
    ShopOrderLine,
    ShopShippingMethod,
)
from models.shop_content import (  # noqa: E402
    Product,
    ShopCategory,
    ShopIdentity,
    ShopOrder,
    ShopSettings,
    Testimonial,
)
from models.shop_engagement import ShopCampaign  # noqa: E402
from models.shop_staff import ShopStaff  # noqa: E402
from services.shop_wallet import ShopWalletService  # noqa: E402
from utils.utils import hash_password  # noqa: E402


async def seed() -> None:
    """Create six revocable staff roles and a small shared synthetic shop."""
    credentials = (
        (os.environ.get("LAB_ADMIN_USERNAME", "labadmin"), "superadmin",
         "LAB_ADMIN_PASSWORD"),
        ("labcontent", "content", "LAB_CONTENT_PASSWORD"),
        ("labsales", "sales", "LAB_SALES_PASSWORD"),
        ("labmarketing", "marketing", "LAB_MARKETING_PASSWORD"),
        ("labfinance", "finance", "LAB_FINANCE_PASSWORD"),
        ("labviewer", "viewer", "LAB_VIEWER_PASSWORD"),
    )
    async with session_maker() as session:
        for username, role, password_name in credentials:
            password = os.environ.get(password_name, "")
            if len(password) < 14:
                raise RuntimeError(f"Missing strong test password: {password_name}")
            existing = await session.scalar(
                select(ShopStaff).where(ShopStaff.username == username)
            )
            if existing is None:
                session.add(ShopStaff(
                    username=username,
                    role=role,
                    password_hash=hash_password(password),
                    is_active=True,
                    session_version=1,
                ))
        await session.flush()

        settings = await session.get(ShopSettings, 1)
        if settings is None:
            session.add(ShopSettings(
                id=1,
                brand_name="فروشگاه آزمایشی تلگرام و بله",
                welcome_message="به محیط تست خوش آمدید؛ این یک خرید واقعی نیست.",
                faq_text="پرداخت و ارسال واقعی در محیط آزمایشی غیرفعال هستند.",
                support_url=None,
            ))

        category = await session.scalar(
            select(ShopCategory).where(ShopCategory.name == "محصولات نمونه تست")
        )
        if category is None:
            category = ShopCategory(
                name="محصولات نمونه تست",
                position=1,
                is_published=True,
            )
            session.add(category)
            await session.flush()

        specs = (
            ("LAB-PHYSICAL-001", "محصول فیزیکی آزمایشی", 2_500_000, "physical"),
            ("LAB-DIGITAL-002", "محصول دیجیتال آزمایشی", 800_000, "digital"),
        )
        products: dict[str, Product] = {}
        for sku, name, price, product_type in specs:
            record = await session.scalar(
                select(Product).where(Product.sku == sku)
            )
            if record is None:
                record = Product(
                    sku=sku,
                    category_id=category.id,
                    name=name,
                    description="دادهٔ ساختگی مخصوص تست داشبورد است.",
                    price=price,
                    stock_quantity=25,
                    position=1 if product_type == "physical" else 2,
                    product_type=product_type,
                    requires_shipping=product_type == "physical",
                    price_stars=None,
                    is_published=True,
                )
                session.add(record)
                await session.flush()
            products[sku] = record

        for platform, opted_in in (("telegram", True), ("bale", False)):
            existing = await session.scalar(
                select(ShopIdentity).where(
                    ShopIdentity.platform == platform,
                    ShopIdentity.platform_user_id == 101001,
                )
            )
            if existing is None:
                session.add(ShopIdentity(
                    platform=platform,
                    platform_user_id=101001,
                    username=f"lab_{platform}",
                    first_name="کاربر آزمایشی",
                    allow_announcements=opted_in,
                    is_blocked=False,
                ))
        await session.flush()

        # Separate store-credit accounts for the SAME numeric user ID on
        # Telegram and Bale. Neither amount is a native Bale wallet balance.
        for platform, fake_credit in (
            ("telegram", 500_000),
            ("bale", 350_000),
        ):
            identity = await session.scalar(
                select(ShopIdentity).where(
                    ShopIdentity.platform == platform,
                    ShopIdentity.platform_user_id == 101001,
                )
            )
            await ShopWalletService.apply(
                session,
                identity_id=identity.id,
                delta_irr=fake_credit,
                operation_key=f"lab-initial-store-credit:{platform}:101001",
                reason="Synthetic onboarding credit for integration tests",
                actor="lab:seed",
            )

        shipping = await session.scalar(
            select(ShopShippingMethod)
            .where(ShopShippingMethod.name == "ارسال آزمایشی")
        )
        if shipping is None:
            session.add(ShopShippingMethod(
                name="ارسال آزمایشی",
                price_irr=120_000,
                position=1,
                is_active=True,
            ))

        coupon = await session.scalar(
            select(ShopCoupon).where(ShopCoupon.code == "LABTEST10")
        )
        if coupon is None:
            session.add(ShopCoupon(
                code="LABTEST10",
                discount_type="percent",
                value=10,
                minimum_subtotal_irr=0,
                max_uses=100,
                used_count=0,
                is_active=True,
            ))

        fixture_order = await session.scalar(
            select(ShopOrder).where(
                ShopOrder.invoice_payload == "lab-manual-review-fixture"
            )
        )
        if fixture_order is None:
            product = products["LAB-PHYSICAL-001"]
            fixture_order = ShopOrder(
                platform="bale",
                platform_user_id=101001,
                chat_id=101001,
                product_id=product.id,
                product_name_snapshot=product.name,
                quantity=1,
                unit_price_irr=product.price,
                total_irr=product.price,
                provider="manual_review",
                status="pending_review",
                invoice_payload="lab-manual-review-fixture",
            )
            session.add(fixture_order)
            await session.flush()
            session.add(ShopOrderLine(
                order_id=fixture_order.id,
                product_id=product.id,
                product_name_snapshot=product.name,
                sku_snapshot=product.sku,
                unit_price_irr=product.price,
                quantity=1,
                total_irr=product.price,
            ))

        sample_testimonial = await session.scalar(
            select(Testimonial).where(
                Testimonial.product_id == products["LAB-PHYSICAL-001"].id,
                Testimonial.text == "نظر آزمایشی؛ هنوز تأیید نشده است.",
            )
        )
        if sample_testimonial is None:
            session.add(Testimonial(
                product_id=products["LAB-PHYSICAL-001"].id,
                text="نظر آزمایشی؛ هنوز تأیید نشده است.",
                position=0,
                is_approved=False,
            ))

        campaign = await session.scalar(
            select(ShopCampaign)
            .where(ShopCampaign.title == "کمپین پیش‌نویس آزمایشی")
        )
        if campaign is None:
            session.add(ShopCampaign(
                title="کمپین پیش‌نویس آزمایشی",
                text="ارسال واقعی غیرفعال است.",
                audience="all",
                status="draft",
            ))

        await session.commit()

    print(
        "Test-only seed is ready: six staff roles, two products, "
        "two platform-scoped identities and isolated demo balances, one unpaid order, "
        "one draft campaign and a review. No live provider calls."
    )


def main() -> None:
    """Run only after isolated Alembic migrations have been applied."""
    asyncio.run(seed())


if __name__ == "__main__":
    main()
