"""Private, signed FastAPI bridge for the separate Next.js dashboard.

The bridge does not replace the current SQLAdmin panel. Requests are signed
by Next.js on the server; browsers never receive the bridge secret or staff
session version. Every call revalidates the active database staff role.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import func, or_, select, text, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import config
from db import session_maker
from models.shop_content import (
    Product, ProductMedia, Testimonial, ShopCategory, ShopIdentity, ShopOrder, ShopSettings,
)
from models.shop_checkout import (
    ShopOrderLine, ShopCartItem, ShopShippingMethod, ShopCoupon,
)
from models.shop_payment import ShopRefundCase, ShopPaymentAttempt
from models.shop_engagement import (
    ShopWalletAccount, ShopWalletEntry,
)
from models.shop_engagement import (
    ShopCampaign, ShopCampaignDelivery, ShopCampaignMedia,
)
from models.shop_staff import ShopStaff
from models.shop_product_visibility import ShopProductVisibility
from services.shop_sequence import next_display_position
from services.shop_store_context import current_context
from services.shop_uom import validate_product_units
from models.shop_multibot import DEFAULT_STORE_ID
from models.shop_store_commerce import ShopStoreSettings
from services.shop_analytics import build_shop_analytics
from services.shop_broadcast_control import (
    BroadcastControl, CampaignRejected, delivery_counts,
)
from services.shop_campaigns import ShopCampaignService
from utils.utils import verify_password


router = APIRouter(prefix="/internal/admin/v1", tags=["Next Admin bridge"])
ALL_ROLES = frozenset({
    "superadmin", "sales", "content", "finance", "marketing", "viewer",
})
PRICE_LIMIT = 9_999_999_999_999_999


async def database() -> AsyncIterator[AsyncSession]:
    """Yield one database transaction for a request without auto-committing."""
    async with session_maker() as session:
        yield session


Db = Annotated[AsyncSession, Depends(database)]


def verify_bridge_signature(
    *,
    secret: str,
    timestamp: str,
    method: str,
    target: str,
    body: bytes,
    staff_id: int,
    session_version: int,
    signature: str,
    now: float | None = None,
) -> bool:
    """Verify one server-to-server HMAC without accepting client-side roles.

    This pure function also supports fast offline regression tests that
    exercise body, path, method, timestamp and identity tampering.
    """
    try:
        stamp = int(timestamp)
    except ValueError:
        return False
    clock = time.time() if now is None else now
    if (
        abs(clock - stamp) > 60
        or staff_id < 0 or session_version < 0
        or len(secret) < 32 or len(signature) != 64
    ):
        return False
    digest = hashlib.sha256(body).hexdigest()
    canonical = "\n".join((
        timestamp, method.upper(), target, digest,
        str(staff_id), str(session_version),
    ))
    expected = hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


async def bounded_bridge_body(request: Request) -> bytes:
    """Read a signed body once with a hard bound even for chunked uploads.

    Starlette's cached request body is restored for its multipart parser.
    Enforcing a bound before signature verification avoids unbounded memory.
    """
    path = request.url.path
    import re

    upload = (
        path.startswith("/internal/admin/v1/upload/")
        or bool(re.fullmatch(
            r"/internal/admin/v1/products/[1-9][0-9]{0,18}/digital-file",
            path,
        )) and request.method == "POST"
    )
    # Only the signed, typed model import endpoint may accept an 8 MiB
    # spreadsheet. All other admin API requests keep their previous limits.
    data_import = (
        request.method == "POST"
        and path.startswith("/internal/admin/v1/data-models/")
        and path.endswith("/import")
        and len(path.split("/")) == 7
    )
    limit = (
        50_100_000 if upload else
        8 * 1024 * 1024 if data_import else
        256 * 1024
    )
    header = request.headers.get("content-length")
    if header is not None:
        try:
            length = int(header)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid content length") from None
        if length < 0 or length > limit:
            raise HTTPException(status_code=413, detail="Request body too large")
    collected = bytearray()
    async for chunk in request.stream():
        if len(collected) + len(chunk) > limit:
            raise HTTPException(status_code=413, detail="Request body too large")
        collected.extend(chunk)
    request._body = bytes(collected)  # Reuse Starlette's body cache for form().
    return request._body


async def signed_staff(request: Request, session: Db) -> ShopStaff | None:
    """Validate a bounded HMAC request and an active, unrevoked staff account."""
    secret = config.NEXT_ADMIN_BRIDGE_SECRET
    if not config.NEXT_ADMIN_BRIDGE_ENABLED or not secret:
        raise HTTPException(status_code=404, detail="Not found")

    headers = request.headers
    stamp = headers.get("x-shop-time", "")
    signature = headers.get("x-shop-signature", "")
    staff_id_raw = headers.get("x-shop-staff", "")
    version_raw = headers.get("x-shop-version", "")
    try:
        timestamp = int(stamp)
        staff_id = int(staff_id_raw)
        version = int(version_raw)
    except ValueError:
        raise HTTPException(status_code=401, detail="Unauthorized") from None

    # Method, query string, body, staff ID and revocation version are signed.
    target = request.url.path
    if request.url.query:
        target += f"?{request.url.query}"
    body = await bounded_bridge_body(request)
    if not verify_bridge_signature(
        secret=secret,
        timestamp=stamp,
        method=request.method,
        target=target,
        body=body,
        staff_id=staff_id,
        session_version=version,
        signature=signature,
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if staff_id == 0 and version == 0:
        if request.url.path not in {"/internal/admin/v1/auth/login", "/internal/admin/v1/auth/redeem"}:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return None

    if staff_id == 0 or version == 0:
        raise HTTPException(status_code=401, detail="Unauthorized")
    staff = await session.get(ShopStaff, staff_id)
    if (
        staff is None or not staff.is_active
        or staff.session_version != version
        or staff.role not in ALL_ROLES
    ):
        raise HTTPException(status_code=401, detail="Session revoked")
    return staff


Staff = Annotated[ShopStaff | None, Depends(signed_staff)]


def require_staff(staff: ShopStaff | None, *roles: str) -> ShopStaff:
    """Authorize from the database, ignoring any client-side role label."""
    if staff is None:
        raise HTTPException(status_code=401, detail="Login required")
    if staff.role not in ("superadmin", *roles):
        raise HTTPException(status_code=403, detail="Permission denied")
    return staff


def _store_rows(model):
    """Restrict every signed admin list/count to the active Store set."""
    ctx = current_context()
    return model.store_id.in_(ctx.active_store_ids) if ctx else true()


def product_data(item: Product) -> dict:
    """Serialize explicit safe product fields; preserve large IRR as string."""
    return {
        "id": item.id,
        "store_id": item.store_id,
        "sku": item.sku,
        "external_ref": item.external_ref,
        "uom_id": item.uom_id,
        "purchase_uom_id": item.purchase_uom_id,
        "category_id": item.category_id,
        "name": item.name,
        "description": item.description,
        "price_irr": str(item.price),
        "price_stars": item.price_stars,
        "stock_quantity": item.stock_quantity,
        "requires_shipping": item.requires_shipping,
        "product_type": item.product_type,
        "position": item.position,
        "is_published": item.is_published,
    }


class LoginPayload(BaseModel):
    """Credentials forwarded only between trusted server processes."""

    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class CategoryPayload(BaseModel):
    """Merchant-managed category with no hardcoded category Enum."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    is_published: bool = False


class CategoryPatch(BaseModel):
    """Only explicitly present fields are changed."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    position: int | None = Field(default=None, ge=0, le=1_000_000)
    is_published: bool | None = None


class ProductPayload(BaseModel):
    """Create a product; merchant SKU and optional description may be blank."""

    model_config = ConfigDict(extra="forbid")
    sku: str = Field(default="", max_length=64)
    external_ref: str | None = Field(default=None, max_length=80)
    uom_id: str | None = Field(default=None, max_length=36)
    purchase_uom_id: str | None = Field(default=None, max_length=36)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=40_000)
    category_id: int | None = Field(default=None, ge=1)
    price_irr: int = Field(ge=0, le=PRICE_LIMIT)
    stock_quantity: int = Field(default=0, ge=0, le=100_000_000)
    product_type: Literal["physical", "digital"] = "physical"
    requires_shipping: bool = True
    price_stars: int | None = Field(default=None, ge=1)
    is_published: bool = False
    show_description: bool = True
    show_stock: bool = True
    show_media: bool = True
    show_reviews: bool = True


class ProductPatch(BaseModel):
    """Allow explicit visibility changes without changing archived orders."""

    model_config = ConfigDict(extra="forbid")
    sku: str | None = Field(default=None, max_length=64)
    external_ref: str | None = Field(default=None, max_length=80)
    uom_id: str | None = Field(default=None, max_length=36)
    purchase_uom_id: str | None = Field(default=None, max_length=36)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=40_000)
    category_id: int | None = Field(default=None, ge=1)
    price_irr: int | None = Field(default=None, ge=0, le=PRICE_LIMIT)
    stock_quantity: int | None = Field(default=None, ge=0, le=100_000_000)
    position: int | None = Field(default=None, ge=0, le=1_000_000)
    product_type: Literal["physical", "digital"] | None = None
    requires_shipping: bool | None = None
    price_stars: int | None = Field(default=None, ge=1)
    is_published: bool | None = None
    show_description: bool | None = None
    show_stock: bool | None = None
    show_media: bool | None = None
    show_reviews: bool | None = None


PUBLIC_OPTIONAL_FIELDS = (
    "show_description", "show_stock", "show_media", "show_reviews",
)


def public_field_values(row: ShopProductVisibility | None) -> dict[str, bool]:
    """Apply backwards-compatible visible defaults for existing products."""
    return {
        name: getattr(row, name) if row is not None else True
        for name in PUBLIC_OPTIONAL_FIELDS
    }


class CampaignPayload(BaseModel):
    """Unsending campaign draft controlled by the existing marketing core."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=3000)
    audience: Literal["all", "telegram", "bale"] = "all"


class CampaignStart(BaseModel):
    """Frozen approved paid call ceiling for a Business API campaign."""

    model_config = ConfigDict(extra="forbid")
    bale_mode: Literal["standard", "business"] = "standard"
    approved_paid_calls: int = Field(default=0, ge=0, le=1_000_000)


class SettingsPayload(BaseModel):
    """Text settings editable by the merchant rather than by deploying code."""

    model_config = ConfigDict(extra="forbid")
    brand_name: str | None = Field(default=None, max_length=255)
    welcome_message: str | None = Field(default=None, max_length=4096)
    faq_text: str | None = Field(default=None, max_length=20_000)
    support_url: str | None = Field(default=None, max_length=500)


@router.post("/auth/login")
async def login(payload: LoginPayload, staff: Staff, session: Db) -> dict:
    """Authenticate with the same Argon2 staff accounts as SQLAdmin."""
    if staff is not None:
        raise HTTPException(status_code=400, detail="Unexpected session")
    username = payload.username.strip().casefold()
    # Redis-backed account throttling is shared between Next.js processes.
    key = "shop:nextlogin:" + hashlib.sha256(
        username.encode("utf-8")
    ).hexdigest()
    limiter = Redis(
        host=config.REDIS_HOST, password=config.REDIS_PASSWORD,
        socket_connect_timeout=2, socket_timeout=2,
    )
    try:
        attempts = await limiter.incr(key)
        if attempts == 1:
            await limiter.expire(key, 600)
        if attempts > 10:
            raise HTTPException(status_code=429, detail="Try again later")
    except HTTPException:
        raise
    except Exception:
        # Fail closed when the login throttle cannot be verified.
        raise HTTPException(status_code=503, detail="Login unavailable") from None
    finally:
        await limiter.aclose()

    account = await session.scalar(
        select(ShopStaff).where(
            ShopStaff.username == username,
            ShopStaff.is_active.is_(True),
        )
    )
    if account is None or not verify_password(
        payload.password, account.password_hash
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "id": account.id,
        "username": account.username,
        "role": account.role,
        "session_version": account.session_version,
    }


@router.get("/auth/me")
async def me(staff: Staff) -> dict:
    """Revalidate the current cookie subject against live staff metadata."""
    account = require_staff(staff, *ALL_ROLES)
    return {"id": account.id, "username": account.username, "role": account.role}


@router.get("/overview")
async def overview(staff: Staff, session: Db) -> dict:
    """Return source-backed KPI cards and a small order table, not mock data."""
    require_staff(staff, *ALL_ROLES)
    report = await build_shop_analytics(session, days=30)
    products = int(await session.scalar(
        select(func.count()).select_from(Product)
        .where(_store_rows(Product))
    ) or 0)
    published = int(await session.scalar(
        select(func.count()).select_from(Product)
        .where(Product.is_published.is_(True), _store_rows(Product))
    ) or 0)
    # Viewer and content/marketing roles may see aggregates, not individual
    # customer orders. Sales/finance can inspect explicit operational records.
    orders = (
        (await session.execute(
            select(ShopOrder).where(_store_rows(ShopOrder))
            .order_by(ShopOrder.id.desc()).limit(8)
        )).scalars().all()
        if staff and staff.role in ("superadmin", "sales", "finance")
        else []
    )
    return {
        "products": products,
        "published_products": published,
        "channels": [
            {
                **asdict(ch),
                "gross_paid_irr": str(ch.gross_paid_irr),
                "store_credit_irr": str(ch.store_credit_irr),
            }
            for ch in report.channels
        ],
        "open_refunds": report.open_refund_cases,
        "campaigns": asdict(report.campaigns),
        "recent_orders": [
            {
                "id": row.id, "platform": row.platform,
                "name": row.product_name_snapshot, "status": row.status,
                "total_irr": str(row.total_irr),
                "created_at": row.created_at.isoformat(),
            }
            for row in orders
        ],
    }


@router.get("/categories")
async def categories(staff: Staff, session: Db) -> list[dict]:
    """Show actual category records in admin-defined order."""
    require_staff(staff, "content")
    items = (await session.execute(
        select(ShopCategory).where(_store_rows(ShopCategory))
        .order_by(ShopCategory.position, ShopCategory.id)
        .limit(2000)
    )).scalars().all()
    return [
        {
            "id": row.id, "name": row.name, "store_id": row.store_id,
            "position": row.position, "is_published": row.is_published,
        }
        for row in items
    ]


@router.post("/categories", status_code=201)
async def create_category(
    payload: CategoryPayload, staff: Staff, session: Db
) -> dict:
    """Create a database-backed category, never hardcode navigation content."""
    require_staff(staff, "content")
    fields = payload.model_dump()
    fields["position"] = await session.run_sync(
        lambda sync: next_display_position(sync, ShopCategory)
    )
    record = ShopCategory(**fields)
    session.add(record)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Category already exists") from None
    await session.refresh(record)
    return {"id": record.id}


@router.patch("/categories/{category_id}")
async def edit_category(
    category_id: int, payload: CategoryPatch, staff: Staff, session: Db
) -> dict:
    """Edit one category and preserve all product foreign keys."""
    require_staff(staff, "content")
    record = await session.get(ShopCategory, category_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Category not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(status_code=422, detail="Null not allowed")
        setattr(record, field, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Category already exists") from None
    return {"id": record.id}


@router.get("/products")
async def products(
    staff: Staff, session: Db, page: int = 1, search: str = ""
) -> dict:
    """Paginate unlimited products with a bounded query and search field."""
    require_staff(staff, "content")
    if page < 1 or page > 100_000 or len(search) > 100:
        raise HTTPException(status_code=400, detail="Invalid page/search")
    predicate = (
        or_(
            Product.name.ilike(f"%{search}%"),
            Product.sku.ilike(f"%{search}%"),
        )
        if search else None
    )
    count_statement = select(func.count()).select_from(Product).where(
        _store_rows(Product),
    )
    list_statement = select(Product).where(_store_rows(Product))
    if predicate is not None:
        count_statement = count_statement.where(predicate)
        list_statement = list_statement.where(predicate)
    total = int(await session.scalar(count_statement) or 0)
    items = (await session.execute(
        list_statement.order_by(Product.id.desc())
        .offset((page - 1) * 20).limit(20)
    )).scalars().all()
    return {
        "items": [product_data(item) for item in items],
        "total": total, "page": page, "page_size": 20,
    }


@router.get("/products/{product_id}")
async def product(product_id: int, staff: Staff, session: Db) -> dict:
    """Read a single product for the editable dashboard form."""
    require_staff(staff, "content")
    item = await session.get(Product, product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Product not found")
    visibility = await session.get(ShopProductVisibility, product_id)
    return {**product_data(item), **public_field_values(visibility)}


def validated_product_values(
    values: dict, *, current: Product | None = None
) -> dict:
    """Enforce physical/digital constraints before a database write."""
    merged = {
        "product_type": current.product_type if current else "physical",
        "requires_shipping": current.requires_shipping if current else True,
    }
    merged.update(values)
    if merged["product_type"] == "digital" and merged["requires_shipping"]:
        raise HTTPException(
            status_code=422, detail="Digital goods cannot require shipping"
        )
    if "price_irr" in values:
        values["price"] = values.pop("price_irr")
    return values


@router.post("/products", status_code=201)
async def create_product(
    payload: ProductPayload, staff: Staff, session: Db
) -> dict:
    """Create a product with a unique SKU and safe unpublished default."""
    require_staff(staff, "content")
    fields = payload.model_dump()
    visibility = {name: fields.pop(name) for name in PUBLIC_OPTIONAL_FIELDS}
    # Keep historic NOT NULL and UNIQUE constraints without forcing the
    # merchant to invent an SKU for every new product.
    fields["sku"] = fields["sku"].strip() or f"AUTO-{secrets.token_hex(8).upper()}"
    fields["description"] = fields["description"].strip()
    scope = current_context()
    if scope is not None:
        scope.require(scope.current_store_id, write=True)
    store_id = scope.current_store_id if scope else DEFAULT_STORE_ID
    fields["store_id"] = store_id
    fields["uom_id"], fields["purchase_uom_id"] = await validate_product_units(
        session, store_id=store_id,
        uom_id=fields.get("uom_id"),
        purchase_uom_id=fields.get("purchase_uom_id"),
    )
    fields["position"] = await session.run_sync(
        lambda sync: next_display_position(sync, Product)
    )
    fields = validated_product_values(fields)
    category_id = fields.get("category_id")
    if category_id is not None:
        category = await session.get(ShopCategory, category_id)
        scope = current_context()
        if category is None or (
            scope is not None and category.store_id != scope.current_store_id
        ):
            raise HTTPException(
                status_code=422, detail="Category belongs to another Store",
            )
    record = Product(**fields)
    session.add(record)
    try:
        await session.flush()
        session.add(ShopProductVisibility(product_id=record.id, **visibility))
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="SKU already exists") from None
    return {"id": record.id}


@router.patch("/products/{product_id}")
async def edit_product(
    product_id: int, payload: ProductPatch, staff: Staff, session: Db
) -> dict:
    """Patch safe editable properties; do not modify historic order snapshots."""
    require_staff(staff, "content")
    record = await session.get(Product, product_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Product not found")
    fields = payload.model_dump(exclude_unset=True)
    # License inventory is derived from sealed, unclaimed license rows;
    # directly editing Product.stock_quantity would promise nonexistent
    # codes and could charge a customer with no deliverable.
    if record.digital_delivery_mode == "license" and (
        "stock_quantity" in fields or fields.get("product_type", "digital") != "digital"
    ):
        raise HTTPException(
            status_code=409, detail="digital_license_stock_managed",
        )
    if record.digital_delivery_mode == "file" and (
        fields.get("product_type", "digital") != "digital"
    ):
        raise HTTPException(
            status_code=409, detail="digital_file_in_use",
        )
    visibility = {
        name: fields.pop(name) for name in PUBLIC_OPTIONAL_FIELDS
        if name in fields
    }
    for name, value in visibility.items():
        if value is None:
            raise HTTPException(status_code=422, detail=f"{name} must be boolean")
    for required in (
        "name", "description", "price_irr", "stock_quantity",
        "position", "product_type", "requires_shipping", "is_published",
    ):
        if required in fields and fields[required] is None:
            raise HTTPException(status_code=422, detail="Null not allowed")
    if "sku" in fields:
        fields["sku"] = (fields["sku"] or "").strip() or f"AUTO-{secrets.token_hex(8).upper()}"
    if "uom_id" in fields or "purchase_uom_id" in fields:
        selected, purchase = await validate_product_units(
            session, store_id=record.store_id,
            uom_id=fields.get("uom_id", record.uom_id),
            purchase_uom_id=fields.get(
                "purchase_uom_id", record.purchase_uom_id,
            ),
        )
        if selected != record.uom_id:
            # Existing stock, open carts or historic orders are quantified in
            # the original unit. Relabeling them would corrupt inventory.
            has_cart = await session.scalar(select(ShopCartItem.id).where(
                ShopCartItem.product_id == record.id,
            ).limit(1))
            has_order = await session.scalar(select(ShopOrderLine.id).where(
                ShopOrderLine.product_id == record.id,
            ).limit(1))
            if record.stock_quantity or has_cart is not None or has_order is not None:
                raise HTTPException(
                    status_code=409,
                    detail="uom_locked",
                )
        fields["uom_id"] = selected
        fields["purchase_uom_id"] = purchase
    fields = validated_product_values(fields, current=record)
    category_id = fields.get("category_id")
    if category_id is not None:
        category = await session.get(ShopCategory, category_id)
        scope = current_context()
        if category is None or (
            scope is not None and category.store_id != scope.current_store_id
        ):
            raise HTTPException(
                status_code=422, detail="Category belongs to another Store",
            )
    for key, value in fields.items():
        setattr(record, key, value)
    if visibility:
        existing_policy = await session.get(ShopProductVisibility, product_id)
        if existing_policy is None:
            session.add(ShopProductVisibility(
                product_id=product_id, **visibility,
            ))
        else:
            for key, value in visibility.items():
                setattr(existing_policy, key, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="SKU already exists") from None
    return {"id": record.id}


@router.get("/orders")
async def orders(staff: Staff, session: Db, page: int = 1) -> dict:
    """Show read-only order state; payment confirmations remain provider-only."""
    require_staff(staff, "sales", "finance")
    if not 1 <= page <= 100_000:
        raise HTTPException(status_code=400, detail="Invalid page")
    total = int(await session.scalar(
        select(func.count()).select_from(ShopOrder)
        .where(_store_rows(ShopOrder))
    ) or 0)
    items = (await session.execute(
        select(ShopOrder).where(_store_rows(ShopOrder))
        .order_by(ShopOrder.id.desc())
        .offset((page - 1) * 20).limit(20)
    )).scalars().all()
    return {
        "items": [
            {
                "id": order.id, "platform": order.platform,
                "store_id": order.store_id,
                "user_id": str(order.platform_user_id),
                "name": order.product_name_snapshot,
                "status": order.status, "provider": order.provider,
                "total_irr": str(order.total_irr),
                "created_at": order.created_at.isoformat(),
            }
            for order in items
        ],
        "total": total, "page": page, "page_size": 20,
    }


@router.get("/customers")
async def customers(staff: Staff, session: Db, page: int = 1) -> dict:
    """List platform-scoped identities without merging matching numeric IDs."""
    require_staff(staff, "sales")
    if not 1 <= page <= 100_000:
        raise HTTPException(status_code=400, detail="Invalid page")
    total = int(await session.scalar(
        select(func.count()).select_from(ShopIdentity)
        .where(_store_rows(ShopIdentity))
    ) or 0)
    records = (await session.execute(
        select(ShopIdentity).where(_store_rows(ShopIdentity))
        .order_by(ShopIdentity.id.desc())
        .offset((page - 1) * 20).limit(20)
    )).scalars().all()
    return {
        "items": [
            {
                "id": entry.id, "platform": entry.platform,
                "store_id": entry.store_id,
                "bot_id": entry.bot_id,
                "user_id": str(entry.platform_user_id),
                "name": entry.first_name, "username": entry.username,
                "is_blocked": entry.is_blocked,
                "allow_announcements": entry.allow_announcements,
            }
            for entry in records
        ],
        "total": total, "page": page, "page_size": 20,
    }


@router.get("/campaigns")
async def campaigns(staff: Staff, session: Db) -> list[dict]:
    """Read durable queue progress; campaign controls use existing core."""
    require_staff(staff, "marketing")
    items = (await session.execute(
        select(ShopCampaign)
        .order_by(ShopCampaign.id.desc()).limit(100)
    )).scalars().all()
    result: list[dict] = []
    for item in items:
        counts = (await session.execute(
            select(
                ShopCampaignDelivery.status,
                func.count(ShopCampaignDelivery.id),
            )
            .where(ShopCampaignDelivery.campaign_id == item.id)
            .group_by(ShopCampaignDelivery.status)
        )).all()
        bale_total = await session.scalar(
            select(func.count()).select_from(ShopCampaignDelivery)
            .join(
                ShopIdentity,
                ShopIdentity.id == ShopCampaignDelivery.identity_id,
            )
            .where(
                ShopCampaignDelivery.campaign_id == item.id,
                ShopIdentity.platform == "bale",
            )
        )
        media_total = await session.scalar(
            select(func.count()).select_from(ShopCampaignMedia)
            .where(ShopCampaignMedia.campaign_id == item.id)
        )
        result.append({
            "bale_recipients": int(bale_total or 0),
            "media_count": int(media_total or 0),
            "id": item.id, "title": item.title, "text": item.text,
            "audience": item.audience, "status": item.status,
            "bale_mode": item.bale_mode,
            "max_paid_calls": item.max_paid_calls,
            "paid_calls_reserved": item.paid_calls_reserved,
            "counts": {status: int(n) for status, n in counts},
        })
    return result


@router.post("/campaigns", status_code=201)
async def create_campaign(
    payload: CampaignPayload, staff: Staff, session: Db
) -> dict:
    """Create only an unsent draft with no implicit audience approval."""
    require_staff(staff, "marketing")
    item = ShopCampaign(**payload.model_dump(), status="draft")
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"id": item.id}


@router.post("/campaigns/{campaign_id}/approve")
async def approve_campaign(
    campaign_id: int, staff: Staff, session: Db
) -> dict:
    """Snapshot consenting recipients without starting an external send."""
    user = require_staff(staff, "marketing")
    try:
        total = await ShopCampaignService.approve(
            session, campaign_id=campaign_id,
            approver=f"staff:{user.id}",
        )
    except CampaignRejected as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    return {"audience_size": total}


@router.post("/campaigns/{campaign_id}/start")
async def start_campaign(
    campaign_id: int, payload: CampaignStart, staff: Staff, session: Db
) -> dict:
    """Freeze mode and upper paid-call cap before waking the worker."""
    user = require_staff(staff, "marketing")
    try:
        count = await BroadcastControl.start(
            session, campaign_id=campaign_id, actor=f"staff:{user.id}",
            bale_mode=payload.bale_mode,
            approved_paid_calls=payload.approved_paid_calls,
        )
    except CampaignRejected as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    return {"queued": count}


@router.post("/campaigns/{campaign_id}/{action}")
async def change_campaign(
    campaign_id: int, action: Literal["pause", "resume", "cancel"],
    staff: Staff, session: Db
) -> dict:
    """Pause/resume/cancel through the central audited Broadcast controller."""
    user = require_staff(staff, "marketing")
    try:
        await BroadcastControl.change(
            session, campaign_id=campaign_id,
            actor=f"staff:{user.id}", action=action,
        )
    except CampaignRejected as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    return {"ok": True}


@router.get("/settings")
async def settings(staff: Staff, session: Db) -> dict:
    """Return editable brand and help text without exposing bot tokens."""
    require_staff(staff, "superadmin")
    scope = current_context()
    current_id = scope.current_store_id if scope else DEFAULT_STORE_ID
    row = (
        await session.get(ShopSettings, 1)
        if current_id == DEFAULT_STORE_ID
        else await session.get(ShopStoreSettings, current_id)
    )
    return {
        "brand_name": row.brand_name if row else "",
        "welcome_message": row.welcome_message if row else "",
        "faq_text": row.faq_text if row else "",
        "support_url": row.support_url if row else "",
    }


@router.patch("/settings")
async def change_settings(
    payload: SettingsPayload, staff: Staff, session: Db
) -> dict:
    """Write merchant text settings; never allow application environment edits."""
    require_staff(staff, "superadmin")
    scope = current_context()
    current_id = scope.current_store_id if scope else DEFAULT_STORE_ID
    if current_id == DEFAULT_STORE_ID:
        row = await session.get(ShopSettings, 1)
        if row is None:
            row = ShopSettings(id=1)
            session.add(row)
    else:
        row = await session.get(ShopStoreSettings, current_id)
        if row is None:
            row = ShopStoreSettings(store_id=current_id)
            session.add(row)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await session.commit()
    return {"ok": True}


@router.get("/reports")
async def reports(staff: Staff, session: Db, days: int = 30) -> dict:
    """Expose aggregate channel performance without mixing IRR with XTR."""
    require_staff(staff, *ALL_ROLES)
    try:
        result = await build_shop_analytics(session, days=days)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid period") from None
    channels = []
    for channel in result.channels:
        channel_data = asdict(channel)
        for money_key in ("gross_paid_irr", "store_credit_irr"):
            channel_data[money_key] = str(channel_data[money_key])
        channels.append(channel_data)
    return {
        "channels": channels,
        "campaigns": asdict(result.campaigns),
        "open_refund_cases": result.open_refund_cases,
        "credit_issued_irr": str(result.credit_issued_irr),
        "credit_spent_irr": str(result.credit_spent_irr),
        "top_products": [asdict(item) for item in result.top_products],
        "since": result.since.isoformat() if result.since else None,
    }


class ReconciliationPayload(BaseModel):
    """Recorded external delivery evidence, without any automatic resend."""

    model_config = ConfigDict(extra="forbid")
    delivery_id: int = Field(ge=1)
    resolution: Literal["sent", "skipped"]
    evidence: str = Field(min_length=12, max_length=255)


@router.get("/capabilities")
async def capabilities(staff: Staff) -> dict:
    """Reveal safe feature flags, never secrets or webhook provider tokens."""
    require_staff(staff, *ALL_ROLES)
    return {
        "broadcast_worker_enabled": (
            config.SHOP_BROADCAST_WORKER_ENABLED
            and config.SHOP_CAMPAIGN_DISPATCH_ENABLED
        ),
        "bale_business_enabled": (
            config.BALE_BROADCAST_MODE == "business"
            and config.BALE_BROADCAST_PAID_ENABLED
        ),
        "max_paid_calls": config.SHOP_BROADCAST_MAX_PAID_CALLS,
        "wallet_adjustment_limit_irr": str(config.SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR),
        "telegram_stars_refunds_enabled": config.TELEGRAM_STARS_REFUNDS_ENABLED,
        "bale_prepare_ready": bool(
            config.BALE_BOT_TOKEN and config.BALE_BROADCAST_PREPARE_CHAT_ID > 0
        ),
        "media_photo_max_bytes": 10_000_000,
        "media_other_max_bytes": 50_000_000,
    }


@router.get("/media")
async def media(staff: Staff, session: Db, page: int = 1) -> dict:
    """Read private media metadata only, never expose storage keys or bot IDs."""
    require_staff(staff, "content")
    if not 1 <= page <= 100_000:
        raise HTTPException(status_code=400, detail="Invalid page")
    scope = current_context()
    count_query = select(func.count()).select_from(ProductMedia)
    if scope is not None:
        count_query = count_query.join(
            Product, Product.id == ProductMedia.product_id,
        ).where(Product.store_id.in_(scope.active_store_ids))
    total = int(await session.scalar(count_query) or 0)
    entries = (await session.execute(
        select(ProductMedia, Product.name)
        .join(Product, Product.id == ProductMedia.product_id)
        .order_by(ProductMedia.id.desc())
        .offset((page - 1) * 20).limit(20)
    )).all()
    return {
        "items": [
            {
                "id": item.id, "product_id": item.product_id,
                "product_name": name, "kind": item.kind,
                "filename": item.original_filename,
                "size_bytes": item.size_bytes,
                "is_published": item.is_published,
                "position": item.position,
                "caption": item.caption, "mime_type": item.mime_type,
            }
            for item, name in entries
        ],
        "total": total, "page": page, "page_size": 20,
    }


@router.get("/testimonials")
async def testimonials(staff: Staff, session: Db, page: int = 1) -> dict:
    """Return review moderation state without publicizing file storage paths."""
    require_staff(staff, "content")
    if not 1 <= page <= 100_000:
        raise HTTPException(status_code=400, detail="Invalid page")
    scope = current_context()
    count_query = select(func.count()).select_from(Testimonial)
    if scope is not None:
        count_query = count_query.join(
            Product, Product.id == Testimonial.product_id,
        ).where(Product.store_id.in_(scope.active_store_ids))
    total = int(await session.scalar(count_query) or 0)
    entries = (await session.execute(
        select(Testimonial, Product.name)
        .join(Product, Product.id == Testimonial.product_id)
        .order_by(Testimonial.id.desc())
        .offset((page - 1) * 20).limit(20)
    )).all()
    return {
        "items": [
            {
                "id": row.id, "product_id": row.product_id,
                "product_name": name, "text": row.text,
                "has_file": row.media_storage_key is not None,
                "is_approved": row.is_approved,
                "position": row.position,
                "media_kind": row.media_kind,
            }
            for row, name in entries
        ],
        "total": total, "page": page, "page_size": 20,
    }


@router.get("/shipping")
async def shipping(staff: Staff, session: Db) -> list[dict]:
    """Display dynamically configured shipping charges in integral rials."""
    require_staff(staff, "sales")
    result = await session.execute(
        select(ShopShippingMethod)
        .order_by(ShopShippingMethod.position, ShopShippingMethod.id)
        .limit(1000)
    )
    return [shipping_data(row) for row in result.scalars()]


@router.get("/coupons")
async def coupons(staff: Staff, session: Db) -> list[dict]:
    """Return merchant coupon rules without extending scope to staff wallets."""
    require_staff(staff, "sales", "marketing")
    result = await session.execute(
        select(ShopCoupon).order_by(ShopCoupon.id.desc()).limit(1000)
    )
    return [coupon_data(row) for row in result.scalars()]


@router.get("/refunds")
async def refunds(staff: Staff, session: Db) -> list[dict]:
    """Review financial cases, never expose unverified refund confirmation."""
    require_staff(staff, "finance")
    scope = current_context()
    query = select(
        ShopRefundCase, ShopOrder.platform,
        ShopOrder.total_irr, ShopOrder.provider,
    ).join(ShopOrder, ShopOrder.id == ShopRefundCase.order_id)
    if scope is not None:
        query = query.where(ShopOrder.store_id.in_(scope.active_store_ids))
    records = (await session.execute(
        query.order_by(ShopRefundCase.id.desc()).limit(200)
    )).all()
    return [
        {
            "id": row.id, "order_id": row.order_id,
            "platform": platform, "provider": provider, "status": row.status,
            "reason": row.reason, "amount_irr": str(amount),
            "created_at": row.created_at.isoformat(),
        }
        for row, platform, amount, provider in records
    ]


@router.get("/wallets")
async def wallets(staff: Staff, session: Db) -> dict:
    """Show merchant store-credit balances, separate from Bale native wallet."""
    require_staff(staff, "finance")
    scope = current_context()
    query = select(
        ShopWalletAccount.balance_irr,
        ShopIdentity.platform,
        ShopIdentity.platform_user_id,
        ShopWalletAccount.customer_id,
        ShopWalletAccount.scope,
        ShopWalletAccount.store_id,
    ).outerjoin(
        ShopIdentity, ShopIdentity.id == ShopWalletAccount.identity_id,
    )
    count_query = select(func.count()).select_from(ShopWalletAccount)
    if scope is not None:
        query = query.where(
            ShopWalletAccount.store_id.in_(scope.active_store_ids)
        )
        count_query = count_query.where(
            ShopWalletAccount.store_id.in_(scope.active_store_ids)
        )
    result = await session.execute(
        query.order_by(ShopWalletAccount.id.desc()).limit(100)
    )
    accounts = [{
        "balance_irr": str(balance),
        "platform": platform or "store",
        "user_id": str(user_id) if user_id is not None else f"Customer #{customer_id}",
        "scope": credit_scope, "store_id": store_id,
    } for balance, platform, user_id, customer_id, credit_scope, store_id in result.all()]
    count = int(await session.scalar(count_query) or 0)
    return {"items": accounts, "total": count}


@router.get("/campaigns/{campaign_id}/deliveries")
async def campaign_deliveries(
    campaign_id: int, staff: Staff, session: Db
) -> list[dict]:
    """Give staff bounded, actionable delivery receipts for uncertain messages."""
    require_staff(staff, "marketing")
    result = await session.execute(
        select(
            ShopCampaignDelivery, ShopIdentity.platform,
            ShopIdentity.platform_user_id,
        )
        .join(ShopIdentity, ShopIdentity.id == ShopCampaignDelivery.identity_id)
        .where(
            ShopCampaignDelivery.campaign_id == campaign_id,
            ShopCampaignDelivery.status == "unknown",
        )
        .order_by(ShopCampaignDelivery.id.desc()).limit(100)
    )
    return [
        {
            "id": row.id, "platform": platform,
            "user_id": str(user_id),
            "completed_steps": row.completed_steps,
            "last_error_code": row.last_error_code,
        }
        for row, platform, user_id in result.all()
    ]


@router.post("/campaigns/{campaign_id}/reconcile")
async def reconcile_campaign(
    campaign_id: int,
    payload: ReconciliationPayload,
    staff: Staff,
    session: Db,
) -> dict:
    """Resolve uncertain sends with explicit staff evidence, without retry."""
    user = require_staff(staff, "marketing")
    try:
        await BroadcastControl.reconcile(
            session,
            campaign_id=campaign_id,
            delivery_id=payload.delivery_id,
            actor=f"staff:{user.id}",
            resolution=payload.resolution,
            evidence=payload.evidence,
        )
    except CampaignRejected as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    return {"ok": True}


class ShippingPayload(BaseModel):
    """Editable merchant shipping method with precise integer-rial fees."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    price_irr: int = Field(ge=0, le=PRICE_LIMIT)
    position: int = Field(default=0, ge=0, le=1_000_000)
    is_active: bool = True


class CouponPayload(BaseModel):
    """Marketing-controlled discount; never exposes wallet credit fields."""

    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=3, max_length=32)
    discount_type: Literal["fixed", "percent"]
    value: int = Field(ge=1, le=PRICE_LIMIT)
    minimum_subtotal_irr: int = Field(default=0, ge=0, le=PRICE_LIMIT)
    max_uses: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None
    is_active: bool = True


def shipping_data(item: ShopShippingMethod) -> dict:
    """Serialize money in strings to preserve JavaScript integer precision."""
    return {
        "id": item.id, "name": item.name,
        "price_irr": str(item.price_irr), "position": item.position,
        "is_active": item.is_active,
    }


def coupon_data(item: ShopCoupon) -> dict:
    """Expose meaningful coupon attributes while never writing usage_count."""
    return {
        "id": item.id, "code": item.code,
        "discount_type": item.discount_type, "value": str(item.value),
        "minimum_subtotal_irr": str(item.minimum_subtotal_irr),
        "max_uses": item.max_uses, "used_count": item.used_count,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "is_active": item.is_active,
    }


@router.post("/shipping", status_code=201)
async def add_shipping(
    payload: ShippingPayload, staff: Staff, session: Db
) -> dict:
    """Create an active or inactive checkout shipping option via the database."""
    require_staff(staff, "sales")
    item = ShopShippingMethod(**{
        **payload.model_dump(), "price_irr": payload.price_irr,
    })
    session.add(item)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Shipping method exists") from None
    await session.refresh(item)
    return {"id": item.id}


@router.patch("/shipping/{method_id}")
async def edit_shipping(
    method_id: int, payload: ShippingPayload, staff: Staff, session: Db
) -> dict:
    """Update a method without changing past order shipping snapshots."""
    require_staff(staff, "sales")
    item = await session.get(ShopShippingMethod, method_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Shipping method not found")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Shipping method exists") from None
    return {"id": item.id}


def normalize_coupon(payload: CouponPayload) -> dict:
    """Enforce uppercase promo codes, bounded percentage and safe expiry."""
    import re

    code = payload.code.strip().upper()
    if re.fullmatch(r"[A-Z0-9_-]{3,32}", code) is None:
        raise HTTPException(status_code=422, detail="Invalid coupon code")
    if payload.discount_type == "percent" and payload.value > 100:
        raise HTTPException(status_code=422, detail="Percent cannot exceed 100")
    return {**payload.model_dump(), "code": code}


@router.post("/coupons", status_code=201)
async def add_coupon(
    payload: CouponPayload, staff: Staff, session: Db
) -> dict:
    """Create only a merchant-funded coupon with default unused counter."""
    require_staff(staff, "marketing")
    item = ShopCoupon(**normalize_coupon(payload))
    session.add(item)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Coupon code exists") from None
    await session.refresh(item)
    return {"id": item.id}


@router.patch("/coupons/{coupon_id}")
async def edit_coupon(
    coupon_id: int, payload: CouponPayload, staff: Staff, session: Db
) -> dict:
    """Edit a rule; consumed-count remains immutable through this interface."""
    require_staff(staff, "marketing")
    item = await session.get(ShopCoupon, coupon_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Coupon not found")
    for key, value in normalize_coupon(payload).items():
        setattr(item, key, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Coupon code exists") from None
    return {"id": item.id}


# Extend the same signed bridge; FastAPI remains the only business core.
from dashboard.next_operations import router as next_operations_router  # noqa: E402

router.include_router(next_operations_router)


@router.get("/bot-connections")
async def bot_connections(staff: Staff, session: Db) -> dict:
    """Expose actual Bot API deployment modes without secrets or side effects.

    Configuration is server-owned, so the dashboard cannot silently move a
    webhook to a malicious external destination or start a second poller.
    """
    require_staff(staff, "superadmin")
    await session.execute(text("SELECT 1"))

    import os
    from redis.asyncio import Redis

    pending_mode = None
    try:
        cache = Redis(
            host=config.REDIS_HOST,
            password=config.REDIS_PASSWORD,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        try:
            pending_mode = await cache.get("shop:pending:telegram:update_mode")
        finally:
            await cache.aclose()
    except Exception:
        # Do not hide the actual deployment mode if Redis is unavailable.
        pending_mode = None

    from urllib.parse import urlsplit

    provider_origin = config.WEBHOOK_HOST
    if provider_origin:
        parsed = urlsplit(provider_origin)
        provider_origin = f"{parsed.scheme}://{parsed.netloc}"

    return {
        "database": "connected",
        "telegram": {
            "configured": bool(config.TOKEN),
            "update_mode": config.TELEGRAM_UPDATE_MODE,
            "pending_update_mode": pending_mode,
            "api_transport": config.TELEGRAM_API_MODE,
            "webhook_url": (
                config.WEBHOOK_URL if config.TELEGRAM_UPDATE_MODE == "webhook"
                else None
            ),
            "worker_configured": bool(config.TELEGRAM_WORKER_URL),
            "proxy_configured": bool(config.TELEGRAM_PROXY_URL),
            "supported_update_modes": ["webhook", "getUpdates"],
        },
        "bale": {
            "configured": bool(config.BALE_BOT_TOKEN),
            "update_mode": "webhook",
            # Never expose Bale's secret path or provider token to the UI.
            "webhook_url_label": (
                f"{provider_origin}/webhooks/bale/[private-secret]"
                if provider_origin and config.BALE_BOT_TOKEN
                else None
            ),
            "supported_update_modes": ["webhook"],
        },
        "runtime_note": (
            "Transport mode and host are deployment settings. "
            "Changing them requires an explicit controlled restart; "
            "saving storefront text does not alter provider webhooks."
        ),
    }


class TelegramModeRequest(BaseModel):
    """Explicitly stage a mode switch; no implicit provider mutation."""

    model_config = ConfigDict(extra="forbid")
    mode: Literal["webhook", "polling"]
    confirmation: str


@router.post("/bot-connections/telegram-mode-request")
async def request_telegram_mode(
    payload: TelegramModeRequest, staff: Staff,
) -> dict:
    """Stage the mode for supervised Codespaces activation after a restart.

    A Telegram webhook and getUpdates cannot receive updates concurrently.
    Never call deleteWebhook or launch a second poller from a web request.
    """
    require_staff(staff, "superadmin")

    import os
    if (
        os.environ.get("CODESPACE_FRESH_SCHEMA") != "true"
        or os.environ.get("POSTGRES_DB") != "shop_codespace"
    ):
        raise HTTPException(
            status_code=403, detail="Controlled activation unavailable"
        )
    if payload.confirmation != "STAGE_TELEGRAM_MODE":
        raise HTTPException(
            status_code=422, detail="Explicit confirmation required"
        )

    from redis.asyncio import Redis

    cache = Redis(
        host=config.REDIS_HOST, password=config.REDIS_PASSWORD,
        decode_responses=True, socket_connect_timeout=2,
    )
    try:
        await cache.set("shop:pending:telegram:update_mode", payload.mode)
    finally:
        await cache.aclose()
    return {
        "ok": True,
        "pending_update_mode": payload.mode,
        "activation": "codespace_restart_required",
    }


@router.get("/bot-connections/probe")
async def bot_connection_probe(staff: Staff, request: Request) -> dict:
    """Check provider getMe/getWebhookInfo without modifying any webhook.

    Provider failures are represented as statuses instead of crashing
    the complete administration dashboard.
    """
    require_staff(staff, "superadmin")
    import asyncio

    from aiohttp import ClientSession, ClientTimeout
    from channels.bale import BaleTransport
    from utils.telegram import create_bot, create_telegram_session

    telegram: dict = {"status": "not_configured"}
    bale: dict = {"status": "not_configured"}

    if config.TOKEN:
        telegram_bot = getattr(request.app.state, "telegram_bot", None)
        owns_session = False
        try:
            if telegram_bot is None:
                # Isolated lab has no live receiver; a temporary session is
                # used only for this read-only probe.
                telegram_bot = create_bot(
                    config.TOKEN, create_telegram_session(),
                )
                owns_session = True
            info = await asyncio.wait_for(
                telegram_bot.get_webhook_info(), timeout=8
            )
            account = await asyncio.wait_for(
                telegram_bot.get_me(), timeout=8
            )
            telegram = {
                "status": "connected",
                "username": account.username,
                "pending_updates": info.pending_update_count or 0,
                "webhook_matches": (
                    info.url == config.WEBHOOK_URL
                    if config.TELEGRAM_UPDATE_MODE == "webhook"
                    else not bool(info.url)
                ),
                "provider_mode": (
                    "webhook" if info.url else "getUpdates"
                ),
            }
        except Exception:
            telegram = {"status": "unavailable"}
        finally:
            # The in-process managed Bot belongs to the receiver and MUST
            # never be closed by a dashboard health probe.
            if owns_session and telegram_bot is not None:
                await telegram_bot.session.close()

    if config.BALE_BOT_TOKEN:
        try:
            async with ClientSession(
                timeout=ClientTimeout(total=8),
                trust_env=False,
            ) as http:
                transport = BaleTransport(config.BALE_BOT_TOKEN, http)
                identity = await transport._call("getMe", {})
                bale = {
                    "status": "connected",
                    "username": (
                        identity.get("username")
                        if isinstance(identity, dict)
                        else None
                    ),
                }
                try:
                    info = await transport._call("getWebhookInfo", {})
                except Exception:
                    bale["webhook_status"] = "unsupported_or_unavailable"
                else:
                    expected = (
                        f"{config.WEBHOOK_HOST}/webhooks/bale/"
                        f"{config.BALE_WEBHOOK_SECRET}"
                    )
                    bale["webhook_status"] = (
                        "matching" if isinstance(info, dict)
                        and info.get("url") == expected
                        else "different"
                    )
        except Exception:
            bale = {"status": "unavailable"}

    return {"telegram": telegram, "bale": bale}
