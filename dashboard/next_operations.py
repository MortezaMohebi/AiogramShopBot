"""Signed Next.js admin operations over the existing shop models and services.

Only FastAPI owns business mutations, private file storage, provider refunds,
staff RBAC and wallet accounting. Public Next.js routes never expose keys.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from models.shop_admin_control import AdminProfile, AdminSession
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.datastructures import UploadFile
from starlette.responses import FileResponse

import config
from channels.contracts import Platform
from channels.bale import BaleTransport, BaleApiError
from dashboard.media_storage import (
    UnsupportedMediaError,
    safe_media_path,
    save_media,
)
from dashboard.next_api import Db, Staff, require_staff
from models.shop_content import Product, ProductMedia, Testimonial, ShopIdentity
from models.shop_engagement import (
    ShopCampaign, ShopCampaignMedia, ShopReferralPolicy, ShopWalletAccount,
    ShopWalletEntry,
)
from models.shop_checkout import ShopOrderLine, ShopOrderReviewAudit
from models.shop_content import ShopOrder
from models.shop_staff import ShopStaff
from services.shop_payments import PaymentRejected
from services.shop_refunds import ShopRefundService
from services.shop_campaigns import ShopCampaignService
from services.shop_broadcast_control import CampaignRejected
from services.shop_wallet import ShopWalletService, StoreCreditRejected
from services.shop_channel_features import get_features
from services.shop_sequence import next_display_position

router = APIRouter()
MAX_UPLOAD_REQUEST = 50_100_000


def positive_id(raw: object) -> int:
    """Parse a positive form identifier without trusting foreign input."""
    try:
        number = int(raw)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(status_code=422, detail="شناسه معتبر نیست.") from None
    if number <= 0:
        raise HTTPException(status_code=422, detail="شناسه معتبر نیست.")
    return number


def bounded_number(raw: object) -> int:
    """Parse a bounded nonnegative media sort order."""
    try:
        number = int(raw)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(status_code=422, detail="ترتیب نامعتبر است.") from None
    if not 0 <= number <= 1_000_000:
        raise HTTPException(status_code=422, detail="ترتیب نامعتبر است.")
    return number


def file_response(key: str, mime: str) -> FileResponse:
    """Return a private, safe, non-cacheable preview of a stored file."""
    try:
        path = safe_media_path(config.SHOP_MEDIA_ROOT, key)
    except UnsupportedMediaError:
        raise HTTPException(status_code=404, detail="Not found") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(
        path,
        media_type=mime or "application/octet-stream",
        content_disposition_type="inline",
        filename="media" + path.suffix,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "X-Frame-Options": "DENY",
        },
    )


@router.get("/media/products")
async def media_product_options(staff: Staff, session: Db) -> list[dict]:
    """Provide a bounded list of real products for the media picker."""
    require_staff(staff, "content")
    records = (await session.execute(
        select(Product.id, Product.name, Product.sku)
        .order_by(Product.id.desc()).limit(300)
    )).all()
    return [
        {"id": item_id, "name": name, "sku": sku}
        for item_id, name, sku in records
    ]


@router.get("/products/{product_id}/media")
async def product_media_for_editor(
    product_id: int, staff: Staff, session: Db,
) -> dict:
    """Load one product's private media for its integrated editor only."""
    require_staff(staff, "content")
    if await session.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    items = (
        await session.execute(
            select(ProductMedia)
            .where(ProductMedia.product_id == product_id)
            .order_by(ProductMedia.position, ProductMedia.id)
            .limit(100)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": item.id,
                "filename": item.original_filename,
                "kind": item.kind,
                "mime_type": item.mime_type,
                "size_bytes": item.size_bytes,
                "caption": item.caption,
                "is_published": item.is_published,
            }
            for item in items
        ],
    }


@router.post("/upload/{target}", status_code=201)
async def upload_media(
    target: str, request: Request, staff: Staff, session: Db,
) -> dict:
    """Upload one bounded original using the shared signature-detecting store.

    New content is ALWAYS unpublished. For campaigns, lock the draft before
    writing the private file to prevent approval racing an upload.
    """
    if target not in {"product", "testimonial", "campaign"}:
        raise HTTPException(status_code=404, detail="Not found")
    require_staff(staff, "marketing" if target == "campaign" else "content")
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data;"):
        raise HTTPException(status_code=415, detail="Expected multipart upload")
    if int(request.headers.get("content-length", "0") or "0") > MAX_UPLOAD_REQUEST:
        raise HTTPException(status_code=413, detail="Upload request too large")

    saved = None
    try:
        # Up to 2,000 UTF-8 Persian characters need more than 4 KiB.
        async with request.form(
            max_files=1, max_fields=10, max_part_size=8192
        ) as form:
            # Position is allocated in the database, not entered by users.
            # Separate models keep independent display sequences.
            sequence_model = {
                "product": ProductMedia,
                "testimonial": Testimonial,
                "campaign": ShopCampaignMedia,
            }[target]
            position = await session.run_sync(
                lambda sync: next_display_position(sync, sequence_model)
            )
            caption = form.get("caption", "")
            if not isinstance(caption, str):
                raise HTTPException(status_code=422, detail="Invalid caption")
            caption = caption.strip()
            max_caption = 1024 if target == "campaign" else 2000
            if len(caption) > max_caption:
                raise HTTPException(status_code=422, detail="توضیح بیش از حد طولانی است.")
            uploaded = form.get("file")
            if not isinstance(uploaded, UploadFile) or not uploaded.filename:
                if target != "testimonial" or not caption:
                    raise HTTPException(status_code=422, detail="فایل لازم است.")
                uploaded = None

            if target == "campaign":
                campaign_id = positive_id(form.get("campaign_id"))
                campaign = await session.scalar(
                    select(ShopCampaign)
                    .where(ShopCampaign.id == campaign_id).with_for_update()
                )
                if campaign is None or campaign.status != "draft":
                    raise HTTPException(
                        status_code=409,
                        detail="فقط کمپین پیش‌نویس رسانه می‌پذیرد.",
                    )
            else:
                product_id = positive_id(form.get("product_id"))
                product = await session.scalar(
                    select(Product)
                    .where(Product.id == product_id).with_for_update()
                )
                if product is None:
                    raise HTTPException(status_code=404, detail="Product not found")

            if uploaded is not None:
                saved = await save_media(
                    uploaded,
                    root=config.SHOP_MEDIA_ROOT,
                    max_bytes=config.SHOP_MEDIA_MAX_BYTES,
                )
            if target == "product":
                record = ProductMedia(
                    product_id=product_id,
                    storage_key=saved.key,
                    original_filename=saved.original_filename,
                    mime_type=saved.mime_type,
                    size_bytes=saved.size_bytes,
                    kind=saved.kind,
                    caption=caption or None,
                    position=position,
                    is_published=False,
                )
            elif target == "testimonial":
                record = Testimonial(
                    product_id=product_id,
                    text=caption or None,
                    media_storage_key=saved.key if saved else None,
                    media_kind=saved.kind if saved else None,
                    media_mime_type=saved.mime_type if saved else None,
                    position=position,
                    is_approved=False,
                )
            else:
                record = ShopCampaignMedia(
                    campaign_id=campaign_id,
                    storage_key=saved.key,
                    original_filename=saved.original_filename,
                    mime_type=saved.mime_type,
                    size_bytes=saved.size_bytes,
                    kind=saved.kind,
                    caption=caption or None,
                    position=position,
                )
            session.add(record)
            await session.flush()
            record_id = record.id
            await session.commit()
            response = {"id": record_id, "status": "pending_review" if target != "campaign" else "draft"}
            if target == "campaign":
                response["campaign_id"] = campaign_id
            return response
    except (UnsupportedMediaError, SQLAlchemyError, HTTPException) as exc:
        await session.rollback()
        if saved is not None:
            safe_media_path(config.SHOP_MEDIA_ROOT, saved.key).unlink(
                missing_ok=True
            )
        if isinstance(exc, UnsupportedMediaError):
            raise HTTPException(status_code=422, detail=str(exc)) from None
        if isinstance(exc, SQLAlchemyError):
            raise HTTPException(status_code=409, detail="Upload could not be saved") from None
        raise


class MediaPatch(BaseModel):
    """Editable metadata that cannot rewrite an original private file."""

    model_config = ConfigDict(extra="forbid")
    caption: str | None = Field(default=None, max_length=2000)
    position: int | None = Field(default=None, ge=0, le=1_000_000)
    is_published: bool | None = None


@router.patch("/media/{media_id}")
async def update_media(
    media_id: int, payload: MediaPatch, staff: Staff, session: Db,
) -> dict:
    """Unpublish whenever the reviewed caption changes; approve separately."""
    require_staff(staff, "content")
    record = await session.scalar(
        select(ProductMedia)
        .where(ProductMedia.id == media_id).with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Media not found")
    changes = payload.model_dump(exclude_unset=True)
    if "caption" in changes:
        new_caption = (changes["caption"] or "").strip() or None
        if new_caption != record.caption:
            record.caption = new_caption
            record.is_published = False
    if "position" in changes:
        record.position = changes["position"]
    if "is_published" in changes:
        if changes["is_published"] and "caption" in changes:
            raise HTTPException(status_code=409, detail="Review caption before publishing")
        if changes["is_published"] and not safe_media_path(
            config.SHOP_MEDIA_ROOT, record.storage_key
        ).is_file():
            raise HTTPException(status_code=409, detail="Original file missing")
        record.is_published = changes["is_published"]
    await session.commit()
    return {"id": record.id, "is_published": record.is_published}


@router.delete("/media/{media_id}")
async def delete_unpublished_media(
    media_id: int, staff: Staff, session: Db,
) -> dict:
    """Delete only unapproved originals, never an already published asset."""
    require_staff(staff, "content")
    record = await session.scalar(
        select(ProductMedia)
        .where(ProductMedia.id == media_id).with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Media not found")
    if record.is_published:
        raise HTTPException(status_code=409, detail="Unpublish before deletion")
    key = record.storage_key
    await session.delete(record)
    await session.commit()
    safe_media_path(config.SHOP_MEDIA_ROOT, key).unlink(missing_ok=True)
    return {"deleted": True}


class TestimonialPatch(BaseModel):
    """Moderation fields, never a direct storage-key override."""

    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(default=None, max_length=2000)
    position: int | None = Field(default=None, ge=0, le=1_000_000)
    is_approved: bool | None = None


@router.patch("/testimonials/{review_id}")
async def update_testimonial(
    review_id: int, payload: TestimonialPatch, staff: Staff, session: Db,
) -> dict:
    """Revoke approval on content edits and prevent empty testimonials."""
    require_staff(staff, "content")
    record = await session.scalar(
        select(Testimonial).where(Testimonial.id == review_id).with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Review not found")
    values = payload.model_dump(exclude_unset=True)
    if "text" in values:
        text = (values["text"] or "").strip() or None
        if text is None and record.media_storage_key is None:
            raise HTTPException(status_code=422, detail="Review cannot be empty")
        if text != record.text:
            record.text = text
            record.is_approved = False
    if "position" in values:
        record.position = values["position"]
    if "is_approved" in values:
        if values["is_approved"] and "text" in values:
            raise HTTPException(status_code=409, detail="Review text before approval")
        if values["is_approved"] and record.media_storage_key and not safe_media_path(
            config.SHOP_MEDIA_ROOT, record.media_storage_key
        ).is_file():
            raise HTTPException(status_code=409, detail="Original file missing")
        record.is_approved = values["is_approved"]
    await session.commit()
    return {"id": record.id, "is_approved": record.is_approved}


@router.delete("/testimonials/{review_id}")
async def delete_unapproved_testimonial(
    review_id: int, staff: Staff, session: Db,
) -> dict:
    """Only delete a testimonial while it is not approved."""
    require_staff(staff, "content")
    record = await session.scalar(
        select(Testimonial).where(Testimonial.id == review_id).with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if record.is_approved:
        raise HTTPException(status_code=409, detail="Revoke approval before deletion")
    key = record.media_storage_key
    await session.delete(record)
    await session.commit()
    if key:
        safe_media_path(config.SHOP_MEDIA_ROOT, key).unlink(missing_ok=True)
    return {"deleted": True}


@router.get("/media/preview/{kind}/{media_id}")
async def preview_media(
    kind: str, media_id: int, staff: Staff, session: Db,
) -> FileResponse:
    """Preview only stored originals with role-appropriate access."""
    if kind == "product":
        require_staff(staff, "content")
        record = await session.get(ProductMedia, media_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Not found")
        key, mime = record.storage_key, record.mime_type
    elif kind == "testimonial":
        require_staff(staff, "content")
        record = await session.get(Testimonial, media_id)
        if record is None or record.media_storage_key is None:
            raise HTTPException(status_code=404, detail="Not found")
        key, mime = record.media_storage_key, record.media_mime_type
    elif kind == "campaign":
        require_staff(staff, "marketing")
        record = await session.get(ShopCampaignMedia, media_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Not found")
        key, mime = record.storage_key, record.mime_type
    else:
        raise HTTPException(status_code=404, detail="Not found")
    return file_response(key, mime)


@router.get("/campaigns/{campaign_id}/media")
async def campaign_media_list(
    campaign_id: int, staff: Staff, session: Db,
) -> dict:
    """List ordered files without exposing provider IDs or storage keys."""
    require_staff(staff, "marketing")
    campaign = await session.get(ShopCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    files = (await session.execute(
        select(ShopCampaignMedia)
        .where(ShopCampaignMedia.campaign_id == campaign_id)
        .order_by(ShopCampaignMedia.position, ShopCampaignMedia.id)
        .limit(200)
    )).scalars().all()
    return {
        "can_edit": campaign.status == "draft",
        "items": [
            {
                "id": row.id, "kind": row.kind,
                "filename": row.original_filename,
                "size_bytes": row.size_bytes,
                "caption": row.caption, "position": row.position,
            }
            for row in files
        ],
    }


@router.delete("/campaigns/{campaign_id}/media/{media_id}")
async def delete_campaign_media(
    campaign_id: int, media_id: int, staff: Staff, session: Db,
) -> dict:
    """Do not alter approved, sending or previously sent campaign files."""
    require_staff(staff, "marketing")
    campaign = await session.scalar(
        select(ShopCampaign)
        .where(ShopCampaign.id == campaign_id).with_for_update()
    )
    if campaign is None or campaign.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft attachments can change")
    file = await session.scalar(
        select(ShopCampaignMedia)
        .where(
            ShopCampaignMedia.id == media_id,
            ShopCampaignMedia.campaign_id == campaign_id,
        ).with_for_update()
    )
    if file is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    key = file.storage_key
    await session.delete(file)
    await session.commit()
    safe_media_path(config.SHOP_MEDIA_ROOT, key).unlink(missing_ok=True)
    return {"deleted": True}


class WalletAdjustment(BaseModel):
    """Validated, idempotent shop credit adjustment, never Bale balance."""

    model_config = ConfigDict(extra="forbid")
    platform: Platform
    user_id: int = Field(gt=0)
    amount_irr: int = Field(gt=0)
    direction: str = Field(pattern="^(credit|debit)$")
    reason: str = Field(min_length=12, max_length=200)
    operation_id: UUID
    confirmation: str


@router.post("/wallets/adjust")
async def wallet_adjust(
    payload: WalletAdjustment, staff: Staff, session: Db,
) -> dict:
    """Apply a reviewable manual ledger operation under the existing cap."""
    operator = require_staff(staff, "finance")
    if not (await get_features(session, payload.platform.value)).store_credit_enabled:
        raise HTTPException(
            status_code=409, detail="Store credit is disabled for provider",
        )
    ceiling = config.SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR
    if ceiling <= 0:
        raise HTTPException(status_code=409, detail="Manual credit adjustment disabled")
    if payload.confirmation != "CREDIT_CONFIRMED" or payload.amount_irr > ceiling:
        raise HTTPException(status_code=422, detail="Confirmation or amount invalid")
    identity = await ShopWalletService.find_identity(
        session, payload.platform, payload.user_id
    )
    if identity is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    delta = payload.amount_irr if payload.direction == "credit" else -payload.amount_irr
    try:
        entry, created = await ShopWalletService.apply(
            session,
            identity_id=identity.id,
            delta_irr=delta,
            operation_key=f"staff-adjust:{operator.id}:{payload.operation_id}",
            reason=payload.reason.strip(),
            actor=f"staff:{operator.id}",
        )
        await session.commit()
    except (StoreCreditRejected, IntegrityError) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc) if isinstance(
            exc, StoreCreditRejected
        ) else "Duplicate operation") from None
    return {"entry_id": entry.id, "created": created}


@router.get("/wallets/ledger")
async def wallet_ledger(staff: Staff, session: Db) -> list[dict]:
    """Show append-only merchant ledger entries with actor attribution."""
    require_staff(staff, "finance")
    entries = (await session.execute(
        select(ShopWalletEntry, ShopIdentity.platform, ShopIdentity.platform_user_id)
        .join(ShopWalletAccount, ShopWalletAccount.id == ShopWalletEntry.account_id)
        .join(ShopIdentity, ShopIdentity.id == ShopWalletAccount.identity_id)
        .order_by(ShopWalletEntry.id.desc()).limit(100)
    )).all()
    return [
        {
            "id": entry.id, "platform": platform, "user_id": str(user_id),
            "delta_irr": str(entry.delta_irr),
            "balance_after_irr": str(entry.balance_after_irr),
            "reason": entry.reason, "actor": entry.actor,
            "created_at": entry.created_at.isoformat(),
        }
        for entry, platform, user_id in entries
    ]


class RefundDecision(BaseModel):
    """Explicit operator confirmation for supported refund provider paths."""

    model_config = ConfigDict(extra="forbid")
    action: str = Field(pattern="^(manual|store_credit|stars)$")
    provider_reference: str = Field(default="", max_length=128)
    confirmation: str


@router.post("/refunds/{case_id}/resolve")
async def resolve_refund(
    case_id: int, payload: RefundDecision, request: Request,
    staff: Staff, session: Db,
) -> dict:
    """Reuse the financial core; never simulate a provider refund."""
    operator = require_staff(staff, "finance")
    required = "REFUND_STARS_EXECUTE" if payload.action == "stars" else "REFUND_VERIFIED"
    if payload.confirmation != required:
        raise HTTPException(status_code=422, detail="Explicit confirmation required")
    reviewer = f"staff:{operator.id}"
    try:
        if payload.action == "manual":
            reference = payload.provider_reference.strip()
            await ShopRefundService.confirm_manual(
                session,
                case_id=case_id,
                provider_reference=reference,
                reviewer=reviewer,
            )
        elif payload.action == "store_credit":
            await ShopWalletService.refund_order(
                session, case_id=case_id, actor=reviewer
            )
        else:
            bot = getattr(request.app.state, "telegram_bot", None)
            if bot is None:
                raise PaymentRejected("Telegram bot is unavailable")
            await ShopRefundService.refund_stars(
                session,
                case_id=case_id,
                bot=bot,
                enabled=config.TELEGRAM_STARS_REFUNDS_ENABLED,
                reviewer=reviewer,
            )
    except (PaymentRejected, StoreCreditRejected) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"ok": True}


@router.get("/staff")
async def list_staff(staff: Staff, session: Db) -> list[dict]:
    """Return only safe staff metadata, not password hashes."""
    require_staff(staff, "superadmin")
    members = (await session.execute(
        select(ShopStaff).order_by(ShopStaff.id).limit(1000)
    )).scalars().all()
    # Aggregate safe sign-in metadata; never return bearer or MFA seed.
    enrolled = (await session.execute(
        select(AdminProfile.staff_id, AdminProfile.mfa_secret)
    )).all()
    mfa = {staff_id: bool(seed) for staff_id, seed in enrolled}
    recent = (await session.execute(
        select(AdminSession.staff_id, func.max(AdminSession.created_at))
        .group_by(AdminSession.staff_id)
    )).all()
    last_login = dict(recent)
    return [
        {
            "id": member.id, "username": member.username,
            "role": member.role, "is_active": member.is_active,
            "created_at": member.created_at.isoformat(),
            "mfa_enabled": mfa.get(member.id, False),
            "last_login_at": (
                last_login[member.id].isoformat()
                if member.id in last_login else None
            ),
        }
        for member in members
    ]


class ReferralPolicyPatch(BaseModel):
    """Merchant-funded reward policy: exact rials, capped percentage."""

    model_config = ConfigDict(extra="forbid")
    is_enabled: bool
    percent: int = Field(ge=0, le=30)
    min_order_irr: int = Field(ge=0, le=100_000_000_000)
    max_bonus_irr: int = Field(ge=0, le=100_000_000_000)


@router.get("/referral-policy")
async def referral_policy(staff: Staff, session: Db) -> dict:
    """Expose the optional shop-owned referral promotion, not crypto."""
    require_staff(staff, "superadmin")
    policy = await session.get(ShopReferralPolicy, 1)
    return {
        "is_enabled": policy.is_enabled if policy else False,
        "percent": policy.percent if policy else 0,
        "min_order_irr": str(policy.min_order_irr if policy else 0),
        "max_bonus_irr": str(policy.max_bonus_irr if policy else 0),
    }


@router.patch("/referral-policy")
async def update_referral_policy(
    payload: ReferralPolicyPatch, staff: Staff, session: Db,
) -> dict:
    """Update the singleton rule without mutating historical rewards."""
    require_staff(staff, "superadmin")
    policy = await session.scalar(
        select(ShopReferralPolicy)
        .where(ShopReferralPolicy.id == 1).with_for_update()
    )
    if policy is None:
        policy = ShopReferralPolicy(id=1)
        session.add(policy)
    for field, value in payload.model_dump().items():
        setattr(policy, field, value)
    await session.commit()
    return {"ok": True}


class OrderReviewDecision(BaseModel):
    """Explicit unpaid-order decisions with no payment-status privileges."""

    model_config = ConfigDict(extra="forbid")
    decision: str = Field(pattern="^(accept|reject)$")
    confirmation: str


@router.get("/orders/review-queue")
async def order_review_queue(staff: Staff, session: Db) -> list[dict]:
    """List only manual prepayment orders awaiting sales decisions."""
    require_staff(staff, "sales")
    orders = (await session.execute(
        select(ShopOrder)
        .where(
            ShopOrder.provider == "manual_review",
            ShopOrder.status.in_(("pending_review", "approved_unpaid")),
        )
        .order_by(ShopOrder.id.desc())
        .limit(100)
    )).scalars().all()
    return [
        {
            "id": order.id,
            "status": order.status,
            "platform": order.platform,
            "product_id": order.product_id,
            "total_irr": str(order.total_irr),
        }
        for order in orders
    ]


@router.post("/orders/{order_id}/review")
async def review_unpaid_order(
    order_id: int,
    payload: OrderReviewDecision,
    staff: Staff,
    session: Db,
) -> dict:
    """Accept/reject only a manual-review order and append an audit event."""
    operator = require_staff(staff, "sales")
    expected = (
        "ACCEPT_UNPAID_ORDER"
        if payload.decision == "accept" else "REJECT_UNPAID_ORDER"
    )
    if payload.confirmation != expected:
        raise HTTPException(
            status_code=422, detail="Order decision needs confirmation"
        )
    order = await session.scalar(
        select(ShopOrder)
        .where(
            ShopOrder.id == order_id,
            ShopOrder.provider == "manual_review",
        )
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in ("pending_review", "approved_unpaid"):
        raise HTTPException(status_code=409, detail="Order cannot be reviewed")

    if payload.decision == "accept":
        if order.status != "pending_review":
            raise HTTPException(status_code=409, detail="Order already accepted")
        result = await session.execute(
            select(ShopOrderLine, Product)
            .join(Product, ShopOrderLine.product_id == Product.id)
            .where(ShopOrderLine.order_id == order.id)
        )
        lines = result.all()
        if not lines or any(
            product.stock_quantity < line.quantity or not product.is_published
            for line, product in lines
        ):
            raise HTTPException(
                status_code=409, detail="Published stock must be verified"
            )
        new_status = "approved_unpaid"
    else:
        new_status = "cancelled"

    session.add(
        ShopOrderReviewAudit(
            order_id=order.id,
            actor=f"staff:{operator.id}",
            action=payload.decision,
            old_status=order.status,
            new_status=new_status,
        )
    )
    order.status = new_status
    await session.commit()
    return {"id": order.id, "status": new_status}


class BaleMediaPrepareDecision(BaseModel):
    """Require a deliberate operator action before seeding Bale file IDs."""

    model_config = ConfigDict(extra="forbid")
    confirmation: str


@router.post("/broadcast/prepare/{campaign_id}")
async def prepare_bale_broadcast_media(
    campaign_id: int,
    payload: BaleMediaPrepareDecision,
    request: Request,
    staff: Staff,
    session: Db,
) -> dict:
    """Use only the normal Bale Bot API and the configured private seed chat.

    This never starts, pays for, or sends the campaign to customers. Any
    uncertain seed result is surfaced to the operator rather than retried.
    """
    require_staff(staff, "marketing")
    if payload.confirmation != "PREPARE_BALE_MEDIA":
        raise HTTPException(status_code=422, detail="Confirmation required")
    if not config.BALE_BOT_TOKEN or config.BALE_BROADCAST_PREPARE_CHAT_ID <= 0:
        raise HTTPException(
            status_code=409, detail="Private Bale seed chat is not configured"
        )

    campaign = await session.scalar(
        select(ShopCampaign)
        .where(ShopCampaign.id == campaign_id)
        .with_for_update()
    )
    if campaign is None or campaign.status not in ("draft", "approved"):
        raise HTTPException(status_code=409, detail="Campaign cannot be prepared")
    try:
        attachments = await ShopCampaignService._attachments(session, campaign)
    except CampaignRejected as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    if not attachments:
        raise HTTPException(status_code=409, detail="Campaign has no media")

    client = getattr(request.app.state, "bale_http_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="Bale API client unavailable")
    standard_api = BaleTransport(config.BALE_BOT_TOKEN, client)
    try:
        for attachment in attachments:
            await standard_api.send_media(
                config.BALE_BROADCAST_PREPARE_CHAT_ID, attachment
            )
    except BaleApiError:
        raise HTTPException(
            status_code=502,
            detail="Media preparation requires provider reconciliation",
        ) from None
    return {"ok": True, "prepared": len(attachments)}
