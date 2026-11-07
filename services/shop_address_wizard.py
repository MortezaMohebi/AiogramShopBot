"""Private, resumable address form shared by Telegram and Bale."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply, InboundEvent, InlineAction
from models.shop_customer_account_data import ShopCustomerAddress
from models.shop_customer_navigation import ShopCustomerChatState
from utils.shop_text import clean_text

PROVINCES = (
    "آذربایجان شرقی", "آذربایجان غربی", "اردبیل", "اصفهان", "البرز",
    "ایلام", "بوشهر", "تهران", "چهارمحال و بختیاری", "خراسان جنوبی",
    "خراسان رضوی", "خراسان شمالی", "خوزستان", "زنجان", "سمنان",
    "سیستان و بلوچستان", "فارس", "قزوین", "قم", "کردستان", "کرمان",
    "کرمانشاه", "کهگیلویه و بویراحمد", "گلستان", "گیلان", "لرستان",
    "مازندران", "مرکزی", "هرمزگان", "همدان", "یزد",
)
# An optional free-text fallback covers settlements absent from this list.
CITIES = (
    ("تبریز", "مراغه", "مرند"), ("ارومیه", "خوی", "مهاباد"),
    ("اردبیل", "پارس‌آباد"), ("اصفهان", "کاشان", "نجف‌آباد"),
    ("کرج", "فردیس"), ("ایلام", "دهلران"), ("بوشهر", "برازجان"),
    ("تهران", "ری", "شهریار", "اسلامشهر"),
    ("شهرکرد", "بروجن"), ("بیرجند", "قائن"),
    ("مشهد", "نیشابور", "سبزوار", "تربت حیدریه"),
    ("بجنورد", "شیروان"), ("اهواز", "آبادان", "دزفول"),
    ("زنجان", "ابهر"), ("سمنان", "شاهرود"),
    ("زاهدان", "زابل", "چابهار"), ("شیراز", "مرودشت", "جهرم"),
    ("قزوین", "تاکستان"), ("قم",), ("سنندج", "سقز"),
    ("کرمان", "رفسنجان", "سیرجان"), ("کرمانشاه", "اسلام‌آباد غرب"),
    ("یاسوج", "گچساران"), ("گرگان", "گنبد کاووس"),
    ("رشت", "لاهیجان", "انزلی"), ("خرم‌آباد", "بروجرد"),
    ("ساری", "بابل", "آمل", "قائم‌شهر"), ("اراک", "ساوه"),
    ("بندرعباس", "قشم", "میناب"), ("همدان", "ملایر"), ("یزد", "میبد"),
)
STEPS = ("recipient", "phone", "province", "city", "full_address", "postal_code")
PHONE = re.compile(r"^\+?[0-9]{7,16}\Z")
_LOCAL_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
ACTION = re.compile(
    r"ux:address:(new|resume|pause|back|cancel|next|confirm|page:[0-3]|"
    r"province:(?:[0-9]|[12][0-9]|30)|city:[0-9]|other)\Z"
)


def _rows(*actions: tuple[str, str]) -> tuple[tuple[InlineAction, ...], ...]:
    """Create bounded provider-neutral buttons."""
    return tuple((InlineAction(label, callback),) for label, callback in actions)


def _draft(state: ShopCustomerChatState) -> dict[str, str]:
    """Decode only this customer's own bounded draft."""
    return json.loads(state.address_draft or "{}")


def _step(state: ShopCustomerChatState) -> str:
    """Return the current form field without trusting an arbitrary key."""
    return state.context_ref if state.context_ref in STEPS + ("confirm", "city_other") else STEPS[0]


def _render(state: ShopCustomerChatState, *, page: int = 0) -> BotReply:
    """Show one step with Back, Cancel and a pause preserving the draft."""
    values = _draft(state)
    step = _step(state)
    foot = _rows(
        ("◀ قبلی", "ux:address:back"),
        ("بعداً ادامه می‌دهم", "ux:address:pause"),
        ("لغو ثبت نشانی", "ux:address:cancel"),
    )
    if step == "confirm":
        summary = "\n".join(
            f"{label}: {values.get(key) or '—'}" for label, key in (
                ("عنوان", "label"), ("گیرنده", "recipient"), ("تلفن گیرنده", "phone"),
                ("استان", "province"), ("شهر", "city"),
                ("نشانی", "full_address"), ("کدپستی", "postal_code"),
            )
        )
        return BotReply(
            f"📍 نشانی را بررسی کنید:\n{summary}",
            _rows(("✅ ثبت نشانی", "ux:address:confirm")) + foot,
        )
    if step == "province":
        start = page * 8
        buttons = _rows(*(
            (name, f"ux:address:province:{index}")
            for index, name in enumerate(PROVINCES[start:start + 8], start)
        ))
        navigation = []
        if page:
            navigation.append(("◀ صفحه قبل", f"ux:address:page:{page - 1}"))
        if start + 8 < len(PROVINCES):
            navigation.append(("صفحه بعد ▶", f"ux:address:page:{page + 1}"))
        return BotReply("استان گیرنده را انتخاب کنید.", buttons + _rows(*navigation) + foot)
    if step == "city":
        province = values.get("province")
        cities = CITIES[PROVINCES.index(province)] if province in PROVINCES else ()
        buttons = _rows(*(
            (name, f"ux:address:city:{index}")
            for index, name in enumerate(cities)
        ))
        return BotReply(
            "شهر گیرنده را انتخاب کنید.",
            buttons + _rows(("شهر دیگری است", "ux:address:other")) + foot,
        )
    prompts = {
        "recipient": "نام گیرنده را بنویسید.",
        "phone": "شماره تماس گیرنده را بنویسید. این شماره تأیید حساب نیست.",
        "city_other": "نام شهر را بنویسید.",
        "full_address": "نشانی کامل، خیابان و پلاک را بنویسید.",
        "postal_code": "کدپستی را بنویسید یا از آن بگذرید.",
    }
    buttons = _rows(("بدون کدپستی", "ux:address:next")) if step == "postal_code" else ()
    return BotReply(prompts[step], buttons + foot)


def _advance(state: ShopCustomerChatState) -> None:
    """Skip already known recipient and contact fields."""
    values = _draft(state)
    position = STEPS.index(_step(state))
    next_fields = STEPS[position + 1:]
    state.context_ref = next((field for field in next_fields if field not in values), "confirm")


async def address_reply(
    db: AsyncSession, state: ShopCustomerChatState | None,
    event: InboundEvent, *, store_id: str, customer_id: int,
    display_name: str | None, known_phone: str | None,
) -> BotReply | None:
    """Handle the address wizard and commit only an explicitly confirmed row."""
    action = event.callback_data or ""
    if not ACTION.fullmatch(action) and not (
        state is not None and state.action == "address_input"
        and event.text and not event.text.startswith("/")
    ):
        return None
    if state is None or state.store_id != store_id:
        return BotReply("ابتدا نشانی جدید را از فهرست نشانی‌ها انتخاب کنید.")
    if action == "ux:address:cancel":
        state.action, state.context_ref, state.address_draft = "idle", None, None
        await db.commit()
        return BotReply("ثبت نشانی لغو شد.", _rows(("نشانی‌ها", "ux:addresses")))
    if action == "ux:address:pause":
        state.action = "idle"
        await db.commit()
        return BotReply(
            "نشانی ناتمام ذخیره شد؛ از «نشانی‌های من» ادامه دهید.",
            _rows(("نشانی‌های من", "ux:addresses")),
        )
    if action == "ux:address:new":
        existing = (await db.scalars(select(ShopCustomerAddress.label).where(
            ShopCustomerAddress.store_id == store_id,
            ShopCustomerAddress.customer_id == customer_id,
        ))).all()
        if len(existing) >= 10:
            return BotReply("حداکثر ۱۰ نشانی قابل ذخیره است.")
        # Count-based names collide when an older address was deleted.
        label = "خانه" if not existing else next(
            name for number in range(2, 12)
            if (name := f"نشانی {number}") not in existing
        )
        draft = {"label": label}
        recipient = clean_text(display_name or "")[:100]
        if len(recipient) >= 2:
            draft["recipient"] = recipient
        if known_phone:
            draft["phone"] = known_phone
        state.address_draft = json.dumps(draft, ensure_ascii=False)
        state.context_ref = STEPS[0]
        state.action = "address_input"
        state.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        if "recipient" in draft:
            _advance(state)
    elif state.address_draft is None:
        return BotReply("نشانی ناتمام ندارید.", _rows(("نشانی جدید", "ux:address:new")))
    elif action == "ux:address:resume":
        # Resume is explicit; ordinary navigation leaves the draft parked.
        expiry = state.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            state.action, state.context_ref, state.address_draft = "idle", None, None
            await db.commit()
            return BotReply("مهلت نشانی ناتمام تمام شد؛ نشانی جدید بسازید.")
        state.action = "address_input"
    elif action == "ux:address:back":
        step = _step(state)
        current = len(STEPS) if step == "confirm" else (
            STEPS.index("city") if step == "city_other" else STEPS.index(step)
        )
        state.context_ref = STEPS[max(0, current - 1)]
        state.action = "address_input"
    elif action.startswith("ux:address:page:"):
        if _step(state) != "province":
            return _render(state)
        return _render(state, page=int(action.rsplit(":", 1)[1]))
    elif action.startswith("ux:address:province:") and _step(state) == "province":
        values = _draft(state)
        values["province"] = PROVINCES[int(action.rsplit(":", 1)[1])]
        values.pop("city", None)
        state.address_draft = json.dumps(values, ensure_ascii=False)
        _advance(state)
    elif action.startswith("ux:address:city:") and _step(state) == "city":
        values = _draft(state)
        cities = CITIES[PROVINCES.index(values["province"])]
        index = int(action.rsplit(":", 1)[1])
        if index >= len(cities):
            return _render(state)
        values["city"] = cities[index]
        state.address_draft = json.dumps(values, ensure_ascii=False)
        _advance(state)
    elif action == "ux:address:other" and _step(state) == "city":
        state.context_ref = "city_other"
    elif action == "ux:address:next" and _step(state) == "postal_code":
        values = _draft(state)
        values["postal_code"] = ""
        state.address_draft = json.dumps(values, ensure_ascii=False)
        _advance(state)
    elif action == "ux:address:confirm" and _step(state) == "confirm":
        values = _draft(state)
        if any(not values.get(field) for field in STEPS[:-1]):
            return BotReply("نشانی کامل نیست؛ به مرحلهٔ قبل برگردید.")
        count = int(await db.scalar(select(func.count()).select_from(
            ShopCustomerAddress,
        ).where(
            ShopCustomerAddress.store_id == store_id,
            ShopCustomerAddress.customer_id == customer_id,
        )) or 0)
        if count >= 10:
            return BotReply("حداکثر ۱۰ نشانی قابل ذخیره است.")
        address = ShopCustomerAddress(
            store_id=store_id, customer_id=customer_id, is_default=count == 0,
            **values,
        )
        db.add(address)
        await db.flush()
        state.action, state.context_ref, state.address_draft = "idle", None, None
        await db.commit()
        return BotReply(
            "✅ نشانی ذخیره شد. برای استفاده در سفارش، آن را انتخاب کنید.",
            _rows(
                ("انتخاب برای سفارش", f"ux:address:choose:{address.id}"),
                ("📍 نشانی‌های من", "ux:addresses"),
            ),
        )
    elif event.text and state.action == "address_input":
        step = _step(state)
        if step in {"province", "city", "confirm"}:
            return _render(state)
        field = "city" if step == "city_other" else step
        value = (
            clean_text(event.text) if field in {"recipient", "city", "full_address"}
            else event.text.strip().translate(_LOCAL_DIGITS)
        )
        valid = (
            (field == "recipient" and 2 <= len(value) <= 100)
            or (field == "phone" and PHONE.fullmatch(re.sub(r"[ \-()]", "", value)))
            or (field == "city" and 2 <= len(value) <= 80)
            or (field == "full_address" and 10 <= len(value) <= 500)
            or (field == "postal_code" and re.fullmatch(r"[0-9]{10}", value))
        )
        if not valid:
            return BotReply("مقدار واردشده معتبر نیست. دوباره تلاش کنید.", _render(state).rows)
        values = _draft(state)
        values[field] = re.sub(r"[ \-()]", "", value) if field == "phone" else value
        state.address_draft = json.dumps(values, ensure_ascii=False)
        if step == "city_other":
            state.context_ref = "city"
        _advance(state)
    elif action:
        return _render(state)
    await db.commit()
    return _render(state)
