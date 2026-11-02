"""Private, signed FastAPI bridge for the separate Next.js dashboard.

The bridge does not replace the current SQLAdmin panel. Requests are signed
by Next.js on the server; browsers never receive the bridge secret or staff
session version. Every call revalidates the active database staff role.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import config
from db import session_maker
from models.shop_content import (
    Product, ProductMedia, Testimonial, ShopCategory, ShopIdentity, ShopOrder, ShopSettings,
)
from models.shop_checkout import (
    ShopOrderLine, ShopShippingMethod, ShopCoupon,
)
from models.shop_payment import ShopRefundCase, ShopPaymentAttempt
from models.shop_engagement import (
    ShopWalletAccount, ShopWalletEntry,
)
from models.shop_engagement import (
    ShopCampaign, ShopCampaignDelivery, ShopCampaignMedia,
)
from models.shop_staff import ShopStaff
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

    if (
        abs(time.time() - timestamp) > 60
        or staff_id < 0 or version < 0
        or len(signature) != 64
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # A query string and body are part of the signature; the backend never
    # authorizes a different resource or arbitrary mutation than was signed.
    target = request.url.path
    if request.url.query:
        target += f"?{request.url.query}"
    digest = hashlib.sha256(await request.body()).hexdigest()
    canonical = "\n".join((
        stamp, request.method.upper(), target, digest,
        str(staff_id), str(version),
    ))
    expected = hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if staff_id == 0 and version == 0:
        if request.url.path != "/internal/admin/v1/auth/login":
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


def product_data(item: Product) -> dict:
    """Serialize explicit safe product fields; preserve large IRR as string."""
    return {
        "id": item.id,
        "sku": item.sku,
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
    position: int = Field(default=0, ge=0, le=1_000_000)
    is_published: bool = False


class CategoryPatch(BaseModel):
    """Only explicitly present fields are changed."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    position: int | None = Field(default=None, ge=0, le=1_000_000)
    is_published: bool | None = None


class ProductPayload(BaseModel):
    """A new product with exact IRR price and optional independent Stars price."""

    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=40_000)
    category_id: int | None = Field(default=None, ge=1)
    price_irr: int = Field(ge=0, le=PRICE_LIMIT)
    stock_quantity: int = Field(default=0, ge=0, le=100_000_000)
    position: int = Field(default=0, ge=0, le=1_000_000)
    product_type: Literal["physical", "digital"] = "physical"
    requires_shipping: bool = True
    price_stars: int | None = Field(default=None, ge=1)
    is_published: bool = False


class ProductPatch(BaseModel):
    """Patch without silently resetting values omitted by the editor."""

    model_config = ConfigDict(extra="forbid")
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=40_000)
    category_id: int | None = Field(default=None, ge=1)
    price_irr: int | None = Field(default=None, ge=0, le=PRICE_LIMIT)
    stock_quantity: int | None = Field(default=None, ge=0, le=100_000_000)
    position: int | None = Field(default=None, ge=0, le=1_000_000)
    product_type: Literal["physical", "digital"] | None = None
    requires_shipping: bool | None = None
    price_stars: int | None = Field(default=None, ge=1)
    is_published: bool | None = None


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
    ) or 0)
    published = int(await session.scalar(
        select(func.count()).select_from(Product)
        .where(Product.is_published.is_(True))
    ) or 0)
    # Viewer and content/marketing roles may see aggregates, not individual
    # customer orders. Sales/finance can inspect explicit operational records.
    orders = (
        (await session.execute(
            select(ShopOrder).order_by(ShopOrder.id.desc()).limit(8)
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
        select(ShopCategory)
        .order_by(ShopCategory.position, ShopCategory.id)
        .limit(2000)
    )).scalars().all()
    return [
        {
            "id": row.id, "name": row.name,
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
    record = ShopCategory(**payload.model_dump())
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
    count_statement = select(func.count()).select_from(Product)
    list_statement = select(Product)
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
    return product_data(item)


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
    fields = validated_product_values(payload.model_dump())
    category_id = fields.get("category_id")
    if category_id is not None and not await session.get(
        ShopCategory, category_id
    ):
        raise HTTPException(status_code=422, detail="Category not found")
    record = Product(**fields)
    session.add(record)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="SKU already exists") from None
    await session.refresh(record)
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
    for required in (
        "sku", "name", "description", "price_irr", "stock_quantity",
        "position", "product_type", "requires_shipping", "is_published",
    ):
        if required in fields and fields[required] is None:
            raise HTTPException(status_code=422, detail="Null not allowed")
    fields = validated_product_values(fields, current=record)
    category_id = fields.get("category_id")
    if category_id is not None and not await session.get(
        ShopCategory, category_id
    ):
        raise HTTPException(status_code=422, detail="Category not found")
    for key, value in fields.items():
        setattr(record, key, value)
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
    ) or 0)
    items = (await session.execute(
        select(ShopOrder).order_by(ShopOrder.id.desc())
        .offset((page - 1) * 20).limit(20)
    )).scalars().all()
    return {
        "items": [
            {
                "id": order.id, "platform": order.platform,
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
    ) or 0)
    records = (await session.execute(
        select(ShopIdentity).order_by(ShopIdentity.id.desc())
        .offset((page - 1) * 20).limit(20)
    )).scalars().all()
    return {
        "items": [
            {
                "id": entry.id, "platform": entry.platform,
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
    row = await session.get(ShopSettings, 1)
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
    row = await session.get(ShopSettings, 1)
    if row is None:
        row = ShopSettings(id=1)
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
        "media_photo_max_bytes": 10_000_000,
        "media_other_max_bytes": 50_000_000,
    }


@router.get("/media")
async def media(staff: Staff, session: Db, page: int = 1) -> dict:
    """Read private media metadata only, never expose storage keys or bot IDs."""
    require_staff(staff, "content")
    if not 1 <= page <= 100_000:
        raise HTTPException(status_code=400, detail="Invalid page")
    total = int(await session.scalar(
        select(func.count()).select_from(ProductMedia)
    ) or 0)
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
    total = int(await session.scalar(
        select(func.count()).select_from(Testimonial)
    ) or 0)
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
    return [
        {
            "id": row.id, "name": row.name,
            "price_irr": str(row.price_irr), "is_active": row.is_active,
            "position": row.position,
        }
        for row in result.scalars()
    ]


@router.get("/coupons")
async def coupons(staff: Staff, session: Db) -> list[dict]:
    """Return merchant coupon rules without extending scope to staff wallets."""
    require_staff(staff, "sales", "marketing")
    result = await session.execute(
        select(ShopCoupon).order_by(ShopCoupon.id.desc()).limit(1000)
    )
    return [
        {
            "id": row.id, "code": row.code,
            "type": row.discount_type, "value": str(row.value),
            "used": row.used_count, "max_uses": row.max_uses,
            "is_active": row.is_active,
        }
        for row in result.scalars()
    ]


@router.get("/refunds")
async def refunds(staff: Staff, session: Db) -> list[dict]:
    """Review financial cases, never expose unverified refund confirmation."""
    require_staff(staff, "finance")
    records = (await session.execute(
        select(ShopRefundCase, ShopOrder.platform, ShopOrder.total_irr)
        .join(ShopOrder, ShopOrder.id == ShopRefundCase.order_id)
        .order_by(ShopRefundCase.id.desc()).limit(200)
    )).all()
    return [
        {
            "id": row.id, "order_id": row.order_id,
            "platform": platform, "status": row.status,
            "reason": row.reason, "amount_irr": str(amount),
            "created_at": row.created_at.isoformat(),
        }
        for row, platform, amount in records
    ]


@router.get("/wallets")
async def wallets(staff: Staff, session: Db) -> dict:
    """Show merchant store-credit balances, separate from Bale native wallet."""
    require_staff(staff, "finance")
    result = await session.execute(
        select(
            ShopWalletAccount.balance_irr,
            ShopIdentity.platform,
            ShopIdentity.platform_user_id,
        )
        .join(ShopIdentity, ShopIdentity.id == ShopWalletAccount.identity_id)
        .order_by(ShopWalletAccount.id.desc()).limit(100)
    )
    accounts = [
        {
            "balance_irr": str(balance),
            "platform": platform,
            "user_id": str(user_id),
        }
        for balance, platform, user_id in result.all()
    ]
    count = int(await session.scalar(
        select(func.count()).select_from(ShopWalletAccount)
    ) or 0)
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
