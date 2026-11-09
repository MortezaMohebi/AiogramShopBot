"""A shared read-only catalog flow used by both messaging adapters.

Menu structure is deliberately static. Products and testimonial content come
from the database, are filtered by publication status, and are never fixtures.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from channels.contracts import (
    BotReply, InboundEvent, InlineAction, MediaAttachment, Platform,
)
from models.shop_content import (
    Product, ProductMedia, ShopCategory, Testimonial,
)
from services.shop_money import format_rials
from models.shop_product_visibility import ShopProductVisibility
from services.shop_presentation import product_message
from services.shop_product_attributes import match_attributes, public_attributes, read_product_attributes
from models.shop_uom import ShopUom
from services.shop_channel_features import get_features
from services.shop_bot_catalog_acl import (
    CatalogScope, permitted_product_clause, resolve_scope,
)
from services.shop_bot_context import BotContext
from services.shop_admin_security import SecurityRejected
from models.shop_bot_catalog_acl import ShopBotCategoryRule
from models.shop_bot_operations import ShopBotOperations
from models.shop_store_commerce import ShopStoreSettings

_PAGE_SIZE = 4
_CATEGORY_PAGE_SIZE = 6
_REVIEW_PAGE_SIZE = 3
_MEDIA_PAGE_SIZE = 4
_LIST_PATTERN = re.compile(r"shop:list:(0|[1-9][0-9]{0,18})\Z")
_CATEGORY_PATTERN = re.compile(r"shop:category:([1-9][0-9]{0,18}):(0|[1-9][0-9]{0,18})\Z")
_SUBCATEGORY_PATTERN = re.compile(r"shop:subcategories:([1-9][0-9]{0,9}):(0|[1-9][0-9]{0,9})\Z")
_CATEGORY_LIST_PATTERN = re.compile(r"shop:categories:(0|[1-9][0-9]{0,18})\Z")
_GALLERY_PATTERN = re.compile(
    r"shop:gallery:(0|[1-9][0-9]{0,18}):(0|[1-9][0-9]{0,18})\Z"
)
_BROWSE_ORIGIN = re.compile(r":b:(0|[1-9][0-9]{0,9}):(0|[1-9][0-9]{0,9})\Z")
_PRODUCT_PATTERN = re.compile(r"shop:item:([1-9][0-9]{0,18})\Z")
_GALLERY_ITEM_PATTERN = re.compile(
    r"g:([1-9][0-9]{0,18}):(0|[1-9][0-9]{0,18}):(0|[1-9][0-9]{0,18})\Z"
)
_DETAIL_PATTERN = re.compile(r"shop:detail:([1-9][0-9]{0,18})\Z")
_GALLERY_DETAIL_PATTERN = re.compile(
    r"d:([1-9][0-9]{0,18}):(0|[1-9][0-9]{0,18}):(0|[1-9][0-9]{0,18})\Z"
)


def is_gallery_read_action(action: str) -> bool:
    """Identify read-only product buttons emitted on independent gallery cards."""
    return bool(
        _GALLERY_ITEM_PATTERN.fullmatch(action)
        or _GALLERY_DETAIL_PATTERN.fullmatch(action)
    )
_REVIEW_PATTERN = re.compile(r"shop:reviews:([1-9][0-9]{0,18}):(0|[1-9][0-9]{0,18})\Z")
_MEDIA_PATTERN = re.compile(r"shop:files:([1-9][0-9]{0,18}):(0|[1-9][0-9]{0,18})\Z")
_FILE_PATTERN = re.compile(r"shop:file:([1-9][0-9]{0,18})\Z")
_SEARCH_PRODUCT_ROUTES = (
    "shop:item:", "shop:detail:", "shop:reviews:", "shop:files:", "shop:file:",
)



def _price(value: Decimal) -> str:
    """Format a Decimal without floating-point conversion."""
    formatted = format(value, ",.2f")
    return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted


def _button(label: str, payload: str) -> InlineAction:
    """Limit product labels so inline buttons fit both APIs."""
    short_label = label if len(label) <= 64 else f"{label[:63]}…"
    return InlineAction(label=short_label, callback_data=payload)


def _product_links(reply: BotReply, *, suffix: str, back: InlineAction) -> BotReply:
    """Retain the list origin through related product views."""
    if not suffix:
        return reply

    def contextual(action: InlineAction) -> InlineAction:
        if action.callback_data.startswith(_SEARCH_PRODUCT_ROUTES):
            payload = action.callback_data + suffix
            if len(payload.encode()) <= 64:
                return replace(action, callback_data=payload)
        if action.callback_data in {"shop:list:0", back.callback_data}:
            return back
        return action

    rows = tuple(tuple(contextual(action) for action in row) for row in reply.rows)
    return replace(
        reply, rows=rows or ((back,),),
        product_action=reply.product_action + suffix if reply.product_action else None,
    )


class CatalogFlow:
    """Resolve catalog and review navigation using one shared SQL schema."""

    def __init__(
        self, currency_label: str = "ریال", display_unit: str = "IRR",
        *, bot_context: BotContext | None = None,
    ) -> None:
        """Bind a trusted BotContext without a client-supplied bot ID."""
        self.currency_label = currency_label
        self.display_unit = display_unit
        # Receivers supply only contexts resolved after authentication.
        self.bot_context = bot_context

    def compact_products(
        self,
        products: Sequence[Product],
        *,
        title: str,
        target: Callable[[Product], str],
        controls: tuple[InlineAction, ...],
        footer: tuple[InlineAction, ...],
    ) -> BotReply:
        """Present a single scannable list without loading or sending media."""
        lines = [title]
        rows = []
        for product in products:
            if self.bot_context.platform == Platform.TELEGRAM and product.product_type == "digital":
                price = (
                    f"{product.price_stars} Stars (XTR)"
                    if type(product.price_stars) is int and product.price_stars > 0
                    else "قیمت Stars تعیین نشده"
                )
            else:
                price = format_rials(product.price, self.display_unit)
            lines.append(f"• {product.name[:100]} · {price}")
            rows.append((_button(product.name, target(product)),))
        if controls:
            rows.append(controls)
        if footer:
            rows.append(footer)
        return BotReply("\n".join(lines), tuple(rows))

    def _price_label(self, product: Product, platform: str) -> str:
        """Use the same amount and payment unit as the product card."""
        if platform == "telegram" and product.product_type == "digital":
            if type(product.price_stars) is int and product.price_stars > 0:
                return f"{product.price_stars} Stars (XTR)"
            return "قیمت Stars تعیین نشده"
        return format_rials(product.price, self.display_unit)

    async def reply(
        self, event: InboundEvent, session: AsyncSession
    ) -> BotReply | None:
        """Resolve recognized commands or buttons; ignore other bot features."""
        if self.bot_context is None:
            raise ValueError("An authenticated bot context is required.")
        if self.bot_context.platform != event.platform:
            raise SecurityRejected("bot_identity_mismatch", 403)
        scope = await resolve_scope(
            session, bot_id=self.bot_context.bot_id,
        )
        if event.callback_data is not None:
            data = event.callback_data
            search_origin = data.endswith(":search") and data.startswith(_SEARCH_PRODUCT_ROUTES)
            suffix = ""
            back = _button("بازگشت به محصولات", "shop:list:0")
            if search_origin:
                from services.shop_customer_search import open_result

                unavailable = await open_result(session, self.bot_context, event)
                if unavailable is not None:
                    return unavailable
                suffix = ":search"
                back = _button("بازگشت به نتایج جستجو", "ux:search:back")
            elif data.startswith(_SEARCH_PRODUCT_ROUTES):
                origin = _BROWSE_ORIGIN.search(data)
                if origin is not None:
                    suffix = origin[0]
                    back = _button(
                        "بازگشت به محصولات",
                        f"shop:category:{origin[1]}:{origin[2]}" if int(origin[1])
                        else f"shop:list:{origin[2]}",
                    )
            data = data.removesuffix(suffix) if suffix else data

            def product_links(reply: BotReply) -> BotReply:
                return _product_links(reply, suffix=suffix, back=back)

            match = _LIST_PATTERN.fullmatch(data)
            if match:
                return await self._list_products(session, int(match.group(1)), scope=scope)
            match = _CATEGORY_PATTERN.fullmatch(data)
            if match:
                return await self._list_products(
                    session, int(match.group(2)), category_id=int(match.group(1)), scope=scope
                )
            match = _GALLERY_PATTERN.fullmatch(data)
            if match:
                return await self._list_products(
                    session, int(match[2]), category_id=int(match[1]) or None,
                    scope=scope, gallery=True,
                )
            match = _GALLERY_ITEM_PATTERN.fullmatch(data)
            if match:
                product_id, category_id, page = map(int, match.groups())
                return await self._product(
                    session, product_id, event.platform.value, scope,
                    navigation=(), return_to=f"shop:gallery:{category_id}:{page}",
                    gallery_context=(category_id, page),
                )
            match = _PRODUCT_PATTERN.fullmatch(data)
            if match:
                reply = await self._product(
                    session, int(match[1]), event.platform.value, scope,
                    navigation=() if suffix else None,
                    return_to=back.callback_data,
                )
                return product_links(reply)
            gallery_detail = _GALLERY_DETAIL_PATTERN.fullmatch(data)
            match = gallery_detail or _DETAIL_PATTERN.fullmatch(data)
            if match:
                reply = await self._product(
                    session, int(match[1]), event.platform.value, scope,
                    return_to=back.callback_data, details=True,
                    gallery_context=(int(match.group(2)), int(match.group(3)))
                    if gallery_detail else None,
                )
                return product_links(reply)
            match = _REVIEW_PATTERN.fullmatch(data)
            if match:
                reply = await self._reviews(
                    session, int(match.group(1)), int(match.group(2)), scope
                )
                return product_links(reply)
            match = _MEDIA_PATTERN.fullmatch(data)
            if match:
                reply = await self._media(
                    session, int(match.group(1)), int(match.group(2)), scope
                )
                return product_links(reply)
            match = _FILE_PATTERN.fullmatch(data)
            if match:
                reply = await self._file(session, int(match.group(1)), scope)
                return product_links(reply)
            if data == "shop:home":
                return await self._home(
                    session, event.platform.value, returning=True,
                )
            if data == "shop:help":
                return await self._settings_text(session, key="support", platform=event.platform.value)
            if data == "shop:faq":
                return await self._settings_text(session, key="faq", platform=event.platform.value)
            match = _SUBCATEGORY_PATTERN.fullmatch(data)
            if match:
                return await self._categories_or_products(
                    session, requested_page=int(match.group(2)),
                    parent_id=int(match.group(1)), scope=scope,
                )
            match = _CATEGORY_LIST_PATTERN.fullmatch(data)
            if match:
                return await self._categories_or_products(
                    session, requested_page=int(match.group(1)), scope=scope
                )
            if data == "shop:categories":
                return await self._categories_or_products(session, scope=scope)
            if data.startswith("shop:"):
                return BotReply(
                    "درخواست معتبر نیست. لطفاً دوباره از فهرست محصولات شروع کنید.",
                    ((_button("🛍 محصولات", "shop:list:0"),),),
                )
            return None

        text = (event.text or "").strip()
        if text in ("/catalog", "محصولات", "🛍 محصولات", "🛍 فروشگاه", "🏠 صفحه اول"):
            return await self._list_products(session, 0, scope=scope)
        if text.split(" ", 1)[0] == "/start":
            return await self._home(session, event.platform.value)
        if text in ("/help", "پشتیبانی", "🆘 پشتیبانی"):
            return await self._settings_text(session, key="support", platform=event.platform.value)
        if text in ("❓ پرسش‌های متداول", "/faq"):
            return await self._settings_text(session, key="faq", platform=event.platform.value)
        return None

    async def _home(
        self, session: AsyncSession, platform: str, *, returning: bool = False,
    ) -> BotReply:
        """Show the welcome once at entry and a compact title on return."""
        store_id = self.bot_context.store_id
        settings = await session.get(ShopStoreSettings, store_id)
        per_bot = await session.get(
            ShopBotOperations,
            self.bot_context.bot_id,
        )
        welcome = (
            per_bot.welcome_message
            if per_bot and per_bot.welcome_message
            else settings.welcome_message
            if settings and settings.welcome_message
            else "به فروشگاه خوش آمدید."
        )
        from services.shop_customer_menu import effective_menu

        # The current Bot's Store owns the default layout. A Bot override may
        # only reorder/disable known actions, never bypass payment/cart ACL.
        owner = self.bot_context.bot_id
        rows = await effective_menu(
            session, bot_id=owner, platform=Platform(platform),
        )
        title = (settings.brand_name or "").strip() if settings else ""
        return BotReply(
            text=(f"🛍 {title or 'فروشگاه'}" if returning else welcome[:4096]),
            rows=rows,
            menu_view=True,
        )

    async def _settings_text(
        self, session: AsyncSession, *, key: str, platform: str
    ) -> BotReply:
        """Read help and support information from editable admin settings."""
        store_id = self.bot_context.store_id
        settings = await session.get(ShopStoreSettings, store_id)
        per_bot = await session.get(
            ShopBotOperations,
            self.bot_context.bot_id,
        )
        if key == "faq":
            body = settings.faq_text if settings else None
        else:
            url = (per_bot.support_url or "").strip() if per_bot and per_bot.support_url else ((settings.support_url or "").strip() if settings else "")
            body = url if url.startswith("https://") else None
        return BotReply(
            text=(body or "اطلاعات این بخش هنوز ثبت نشده است.")[:4096],
            rows=((_button("🏠 صفحه اول", "shop:home"),),),
        )

    @staticmethod
    def _visible_category_tree(scope: CatalogScope):
        # Keep the same product rule precedence. Ancestors provide navigation,
        # but unpublished or denied ancestor names are never exposed.
        direct = select(Product.id).where(
            Product.category_id == ShopCategory.id,
            permitted_product_clause(scope),
        ).correlate(ShopCategory).exists()
        tree = select(ShopCategory.id, ShopCategory.parent_id).where(
            ShopCategory.store_id == scope.store_id,
            ShopCategory.is_published.is_(True),
            direct,
        ).cte(recursive=True)
        parent = aliased(ShopCategory)
        denied = select(ShopBotCategoryRule.category_id).where(
            ShopBotCategoryRule.bot_id == scope.bot_id,
            ShopBotCategoryRule.category_id == parent.id,
            ShopBotCategoryRule.effect == "deny",
        ).correlate(parent).exists()
        return tree.union(select(parent.id, parent.parent_id).join(
            tree, tree.c.parent_id == parent.id,
        ).where(
            parent.store_id == scope.store_id, parent.is_published.is_(True), ~denied,
        ))

    async def _categories_or_products(
        self, session: AsyncSession, requested_page: int = 0,
        *, scope: CatalogScope, parent_id: int | None = None,
    ) -> BotReply:
        """Paginate visible roots or the children of one visible category."""
        tree = self._visible_category_tree(scope)
        members = select(tree.c.id)
        parent = None
        if parent_id is not None:
            parent = await session.scalar(select(ShopCategory).where(
                ShopCategory.id == parent_id, ShopCategory.id.in_(members),
            ))
            if parent is None:
                return BotReply("این دسته‌بندی در دسترس نیست.", ((_button("دسته‌بندی‌ها", "shop:categories"),),))
        condition = (
            ShopCategory.parent_id == parent_id if parent_id is not None
            else or_(ShopCategory.parent_id.is_(None), ShopCategory.parent_id.not_in(members))
        )
        query = select(ShopCategory).where(ShopCategory.id.in_(members), condition)
        count = await session.scalar(select(func.count()).select_from(query.subquery()))
        if not count and parent is None:
            return await self._list_products(session, 0, scope=scope)
        if not count:
            return BotReply("زیردسته‌ای برای نمایش وجود ندارد.", ((_button("دسته‌بندی‌ها", "shop:categories"),),))
        last_page = (count - 1) // _CATEGORY_PAGE_SIZE
        page = min(requested_page, last_page)
        items = await session.scalars(query.order_by(
            ShopCategory.position, ShopCategory.id,
        ).offset(page * _CATEGORY_PAGE_SIZE).limit(_CATEGORY_PAGE_SIZE))
        rows = [(_button(item.name, f"shop:category:{item.id}:0"),) for item in items]
        prefix = f"shop:subcategories:{parent_id}" if parent_id is not None else "shop:categories"
        controls = []
        if page:
            controls.append(_button("صفحه قبل", f"{prefix}:{page - 1}"))
        if page < last_page:
            controls.append(_button("صفحه بعد", f"{prefix}:{page + 1}"))
        if controls:
            rows.append(tuple(controls))
        if parent is not None:
            target = "shop:categories"
            if parent.parent_id is not None and await session.scalar(
                select(tree.c.id).where(tree.c.id == parent.parent_id)
            ) is not None:
                target = f"shop:subcategories:{parent.parent_id}:0"
            rows.append((_button("بازگشت به دسته‌بندی‌ها", target),))
        else:
            rows.append((_button("همه محصولات", "shop:list:0"),))
        title = parent.name if parent is not None else "🗂️ دسته‌بندی محصولات را انتخاب کنید:"
        return BotReply(text=f"{title}\nصفحه {page + 1} از {last_page + 1}", rows=tuple(rows))

    async def _list_products(
        self,
        session: AsyncSession,
        requested_page: int,
        category_id: int | None = None,
        *, scope: CatalogScope, gallery: bool = False,
    ) -> BotReply:
        """Render a bounded page of published products."""
        filters = [permitted_product_clause(scope)]
        child_link = None
        if category_id is not None:
            selected = await session.scalar(
                select(ShopCategory.id).where(
                    ShopCategory.id == category_id,
                    ShopCategory.is_published.is_(True),
                    ShopCategory.store_id == scope.store_id,
                )
            )
            if selected is None:
                return BotReply(
                    "این دسته‌بندی در دسترس نیست.",
                    ((_button("همه محصولات", "shop:list:0"),),),
                )
            filters.append(Product.category_id == category_id)
            tree = self._visible_category_tree(scope)
            visible_parent = tree.alias("visible_parent")
            if await session.scalar(select(tree.c.id).where(
                tree.c.parent_id == category_id,
                select(visible_parent.c.id).where(visible_parent.c.id == category_id).exists(),
            ).limit(1)) is not None:
                child_link = _button("زیردسته‌ها", f"shop:subcategories:{category_id}:0")
        count_result = await session.execute(
            select(func.count()).select_from(Product).where(*filters)
        )
        count = count_result.scalar_one()
        if count == 0:
            if child_link is not None:
                return await self._categories_or_products(session, scope=scope, parent_id=category_id)
            return BotReply(
                "هنوز محصولی برای نمایش منتشر نشده است.",
                ((_button("منوی اصلی", "shop:home"),),),
            )

        last_page = (count - 1) // _PAGE_SIZE
        page = min(requested_page, last_page)
        results = await session.execute(
            select(Product)
            .where(*filters)
            .order_by(Product.position, Product.id)
            .offset(page * _PAGE_SIZE)
            .limit(_PAGE_SIZE)
        )
        products = results.scalars().all()
        controls = []
        compact_prefix = (
            f"shop:category:{category_id}" if category_id is not None
            else "shop:list"
        )
        prefix = f"shop:gallery:{category_id or 0}" if gallery else compact_prefix
        if page > 0:
            controls.append(_button("صفحه قبل", f"{prefix}:{page - 1}"))
        if page < last_page:
            controls.append(_button("صفحه بعد", f"{prefix}:{page + 1}"))
        footer = (
            *((child_link,) if child_link is not None else ()),
            _button("دسته‌بندی‌ها", "shop:categories"),
            _button("منوی اصلی", "shop:home"),
        )
        title = f"محصولات · صفحه {page + 1} از {last_page + 1}"
        if not gallery:
            suffix = f":b:{category_id or 0}:{page}" if category_id or page else ""
            return self.compact_products(
                products, title=title, target=lambda product: f"shop:item:{product.id}{suffix}",
                controls=tuple(controls),
                footer=(_button("نمایش تصویری", f"shop:gallery:{category_id or 0}:{page}"), *footer),
            )
        cards = []
        for product in products:
            visibility = await session.get(ShopProductVisibility, product.id)
            unit = await session.get(ShopUom, product.uom_id)
            if unit is None or unit.store_id != scope.store_id:
                continue
            telegram_digital = (
                self.bot_context.platform == Platform.TELEGRAM
                and product.product_type == "digital"
            )
            price_label = (
                f"{product.price_stars} Stars (XTR)"
                if telegram_digital and type(product.price_stars) is int
                and product.price_stars > 0
                else "قیمت Stars تعیین نشده" if telegram_digital
                else format_rials(product.price, self.display_unit)
            )
            cover = None
            if visibility is None or visibility.show_media:
                cover = await session.scalar(select(ProductMedia).where(
                    ProductMedia.product_id == product.id,
                    ProductMedia.kind == "photo",
                    ProductMedia.is_published.is_(True),
                ).order_by(ProductMedia.position, ProductMedia.id).limit(1))
            preview = (
                MediaAttachment(
                    storage_key=cover.storage_key, kind="photo",
                    mime_type=cover.mime_type, caption=product.name[:100],
                ) if cover else None
            )
            card_text = product_message(
                product, price_label=price_label, unit_symbol=unit.symbol,
                show_description=False,
                show_stock=visibility is None or visibility.show_stock,
                attributes=await read_product_attributes(session, product.id, display_store_id=product.store_id),
            )
            cards.append(BotReply(
                text=card_text[:4096], preview=preview,
                rows=((_button(
                    "مشاهدهٔ محصول",
                    f"g:{product.id}:{category_id or 0}:{page}",
                ),),),
            ))
        return BotReply(
            text=title,
            rows=(
                *((tuple(controls),) if controls else ()),
                (
                    _button("فهرست محصولات", f"{compact_prefix}:{page}"),
                    *footer,
                ),
            ),
            cards=tuple(cards),
        )

    async def _product(
        self, session: AsyncSession, product_id: int,
        platform: str, scope: CatalogScope,
        *, navigation: tuple[InlineAction, ...] | None = None,
        return_to: str = "shop:list:0",
        gallery_context: tuple[int, int] | None = None,
        details: bool = False,
    ) -> BotReply:
        """Show an active product, never exposing an unpublished record."""
        result = await session.execute(
            select(Product).where(
                Product.id == product_id,
                permitted_product_clause(scope),
            )
        )
        product = result.scalar_one_or_none()
        if product is None:
            return BotReply(
                "این محصول در حال حاضر قابل نمایش نیست.",
                ((_button("بازگشت به محصولات", return_to),),),
            )

        visibility = await session.get(ShopProductVisibility, product.id)
        show_description = visibility.show_description if visibility else True
        show_stock = visibility.show_stock if visibility else True
        show_media = visibility.show_media if visibility else True
        show_reviews = visibility.show_reviews if visibility else True
        unit = await session.get(ShopUom, product.uom_id)
        if unit is None or unit.store_id != product.store_id:
            return BotReply("واحد اندازه‌گیری این محصول معتبر نیست.")
        telegram_digital = (
            platform == "telegram" and product.product_type == "digital"
        )
        stars_ready = (
            not telegram_digital
            or type(product.price_stars) is int
            and product.price_stars > 0
        )
        price_label = self._price_label(product, platform)
        attributes = await read_product_attributes(session, product.id, display_store_id=product.store_id)
        body = product_message(
            product,
            price_label=price_label,
            unit_symbol=unit.symbol,
            show_description=show_description,
            show_stock=show_stock,
            full_attributes=details,
            attributes=attributes,
        )
        product_action = (
            f"g:{product.id}:{gallery_context[0]}:{gallery_context[1]}"
            if gallery_context else f"shop:item:{product.id}"
        )
        if details:
            return BotReply(
                body, ((_button("بازگشت به محصول", product_action),),),
                product_action=product_action,
            )
        features = await get_features(
            session, platform,
            bot_id=self.bot_context.bot_id,
        )
        rows = []
        if features.cart_enabled:
            if product.stock_quantity > 0 and stars_ready:
                rows.append(
                    (_button("🛒 افزودن به سبد", f"shop:add:{product.id}"),)
                )
            rows.append((_button("🛒 مشاهده سبد", "shop:cart"),))
        rows.append(
            (_button("♡ علاقه‌مندی‌ها", f"ux:wish:toggle:{product.id}"),)
        )
        if product.stock_quantity <= 0:
            rows.append(
                (_button("🔔 اطلاع از موجودشدن", f"ux:stock:toggle:{product.id}"),)
            )
        if navigation is None:
            previous = await session.scalar(select(Product.id).where(
                permitted_product_clause(scope),
                or_(
                    Product.position < product.position,
                    (Product.position == product.position) & (Product.id < product.id),
                ),
            ).order_by(Product.position.desc(), Product.id.desc()).limit(1))
            following = await session.scalar(select(Product.id).where(
                permitted_product_clause(scope),
                or_(
                    Product.position > product.position,
                    (Product.position == product.position) & (Product.id > product.id),
                ),
            ).order_by(Product.position, Product.id).limit(1))
            navigation = tuple(
                _button(label, f"shop:item:{target}")
                for label, target in (
                    ("◀ محصول قبلی", previous), ("محصول بعدی ▶", following),
                ) if target is not None
            )
        if navigation:
            rows.append(navigation)
        rows.append((
            _button("🔎 جستجو", "ux:search"),
            _button("☰ دسته‌بندی‌ها", "shop:categories"),
        ))
        # Hide the navigation controls as well as the underlying data.
        if show_media:
            rows.append((_button("📎 رسانه‌های محصول", f"shop:files:{product.id}:0"),))
        if show_reviews:
            rows.append((_button("💬 رضایت مشتریان", f"shop:reviews:{product.id}:0"),))
        rows.append((_button("بازگشت به محصولات", return_to),))
        preview = None
        if show_media:
            cover = await session.scalar(select(ProductMedia).where(
                ProductMedia.product_id == product.id,
                ProductMedia.is_published.is_(True),
                ProductMedia.kind == "photo",
            ).order_by(ProductMedia.position, ProductMedia.id).limit(1))
            if cover is not None:
                # Keep name, price and stock visible within the photo caption.
                body = product_message(
                    product, price_label=price_label, unit_symbol=unit.symbol,
                    show_description=False, show_stock=show_stock,
                    attributes=attributes,
                )
                preview = MediaAttachment(
                    storage_key=cover.storage_key, kind=cover.kind,
                    mime_type=cover.mime_type, caption=product.name[:100],
                )
            total_media = await session.scalar(select(func.count()).select_from(
                ProductMedia,
            ).where(
                ProductMedia.product_id == product.id,
                ProductMedia.is_published.is_(True),
            ))
            if total_media:
                body += f"\n📎 {total_media} رسانه؛ فقط با درخواست شما باز می‌شوند."
        if (show_description and product.description) or public_attributes(attributes):
            detail_target = (
                f"d:{product.id}:{gallery_context[0]}:{gallery_context[1]}"
                if gallery_context else f"shop:detail:{product.id}"
            )
            rows.insert(1, (_button("مشاهده جزئیات", detail_target),))
        if navigation is not None:
            body = f"🛍 {body}"
        return BotReply(text=body[:4096], rows=tuple(rows), preview=preview, product_action=product_action)

    async def _media(
        self, session: AsyncSession, product_id: int,
        requested_page: int, scope: CatalogScope,
    ) -> BotReply:
        """Page through unlimited published product media without hardcoding files."""
        published = await session.scalar(
            select(Product.id).where(
                Product.id == product_id, permitted_product_clause(scope)
            )
        )
        if published is None:
            return BotReply("این محصول در حال حاضر قابل نمایش نیست.")
        policy = await session.get(ShopProductVisibility, product_id)
        if policy is not None and not policy.show_media:
            return BotReply("رسانه‌های این محصول برای نمایش فعال نیستند.")
        condition = (
            ProductMedia.product_id == product_id,
            ProductMedia.is_published.is_(True),
        )
        result = await session.execute(
            select(func.count()).select_from(ProductMedia).where(*condition)
        )
        count = result.scalar_one()
        if count == 0:
            return BotReply(
                "هنوز فایلی برای این محصول منتشر نشده است.",
                ((_button("بازگشت", f"shop:item:{product_id}"),),),
            )
        last_page = (count - 1) // _MEDIA_PAGE_SIZE
        page = min(requested_page, last_page)
        items = await session.execute(
            select(ProductMedia)
            .where(*condition)
            .order_by(ProductMedia.position, ProductMedia.id)
            .offset(page * _MEDIA_PAGE_SIZE)
            .limit(_MEDIA_PAGE_SIZE)
        )
        buttons = [
            (_button(
                f"📎 {item.kind} · {(item.caption or item.original_filename)[:36]}",
                f"shop:file:{item.id}",
            ),)
            for item in items.scalars().all()
        ]
        controls = []
        if page:
            controls.append(_button("صفحه قبل", f"shop:files:{product_id}:{page - 1}"))
        if page < last_page:
            controls.append(_button("صفحه بعد", f"shop:files:{product_id}:{page + 1}"))
        rows = buttons + ([tuple(controls)] if controls else [])
        rows.append((_button("بازگشت به محصول", f"shop:item:{product_id}"),))
        return BotReply(
            text=f"📎 فایل‌های محصول\nصفحه {page + 1} از {last_page + 1}",
            rows=tuple(rows),
        )

    async def _file(
        self, session: AsyncSession, media_id: int, scope: CatalogScope,
    ) -> BotReply:
        """Deliver exactly one explicitly requested, published attachment."""
        item = await session.scalar(select(ProductMedia).join(
            Product, Product.id == ProductMedia.product_id,
        ).where(
            ProductMedia.id == media_id,
            ProductMedia.is_published.is_(True),
            permitted_product_clause(scope),
        ))
        if item is None:
            return BotReply("رسانه در دسترس نیست.")
        visibility = await session.get(ShopProductVisibility, item.product_id)
        if visibility is not None and not visibility.show_media:
            return BotReply("رسانه در دسترس نیست.")
        return BotReply(
            "📎 رسانهٔ درخواستی محصول",
            ((_button("بازگشت به محصول", f"shop:item:{item.product_id}"),),),
            (MediaAttachment(
                storage_key=item.storage_key, kind=item.kind,
                mime_type=item.mime_type, caption=item.caption or "",
                filename=item.original_filename,
            ),),
        )

    async def _reviews(
        self, session: AsyncSession, product_id: int,
        requested_page: int, scope: CatalogScope,
    ) -> BotReply:
        """Show approved text testimonials for one published product."""
        exists = await session.execute(
            select(Product.id).where(
                Product.id == product_id, permitted_product_clause(scope)
            )
        )
        if exists.scalar_one_or_none() is None:
            return BotReply(
                "این محصول در حال حاضر قابل نمایش نیست.",
                ((_button("بازگشت به محصولات", "shop:list:0"),),),
            )
        policy = await session.get(ShopProductVisibility, product_id)
        if policy is not None and not policy.show_reviews:
            return BotReply("رضایت‌های این محصول برای نمایش فعال نیستند.")

        condition = (
            Testimonial.product_id == product_id,
            Testimonial.is_approved.is_(True),
        )
        count_result = await session.execute(
            select(func.count()).select_from(Testimonial).where(*condition)
        )
        count = count_result.scalar_one()
        if not count:
            return BotReply(
                "هنوز رضایت متنی تأییدشده‌ای برای این محصول وجود ندارد.",
                ((_button("بازگشت به محصول", f"shop:item:{product_id}"),),),
            )

        last_page = (count - 1) // _REVIEW_PAGE_SIZE
        page = min(requested_page, last_page)
        result = await session.execute(
            select(Testimonial)
            .where(*condition)
            .order_by(Testimonial.position, Testimonial.id)
            .offset(page * _REVIEW_PAGE_SIZE)
            .limit(_REVIEW_PAGE_SIZE)
        )
        testimonials = result.scalars().all()
        snippets = [
            f"• {(item.text or 'رضایت تصویری/صوتی')[:600]}"
            for item in testimonials
        ]
        attachments = tuple(
            MediaAttachment(
                storage_key=item.media_storage_key,
                kind=item.media_kind or "document",
                mime_type=item.media_mime_type or "application/octet-stream",
                caption=(item.text or "")[:900],
            )
            for item in testimonials
            if item.media_storage_key
        )
        controls = []
        if page > 0:
            controls.append(
                _button("صفحه قبل", f"shop:reviews:{product_id}:{page - 1}")
            )
        if page < last_page:
            controls.append(
                _button("صفحه بعد", f"shop:reviews:{product_id}:{page + 1}")
            )
        rows = []
        if controls:
            rows.append(tuple(controls))
        rows.append((_button("بازگشت به محصول", f"shop:item:{product_id}"),))
        return BotReply(
            text="💬 رضایت مشتریان\n\n" + "\n\n".join(snippets),
            rows=tuple(rows),
            attachments=attachments,
        )
