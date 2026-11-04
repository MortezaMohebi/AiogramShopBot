"""Execute provider-free customer journeys against real Codespace PostgreSQL.

Run only with compose.beta-qa.yml. Provider SDK calls terminate in explicit
in-memory test transports; no HTTP session capable of sending a bot request
is created. Fixtures are synthetic and additive; no database is ever reset.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from scripts.test_lab_safety import require_isolated_lab

require_isolated_lab()
if os.environ.get("SHOP_BETA_QA") != "1":
    raise RuntimeError("This E2E runner requires the named Beta QA stack.")

from sqlalchemy import func, select, text  # noqa: E402
from starlette.datastructures import Headers, UploadFile  # noqa: E402

from channels.bale import BaleTransport  # noqa: E402
from channels.contracts import Platform  # noqa: E402
from db import engine, session_maker  # noqa: E402
from models.shop_bot_catalog_acl import ShopBotProductRule  # noqa: E402
from models.shop_checkout import ShopCart, ShopShippingMethod  # noqa: E402
from models.shop_checkout_policy import ShopStoreCheckoutPolicy  # noqa: E402
from models.shop_content import Product, ShopCategory, ShopIdentity  # noqa: E402
from models.shop_customer_account_data import (  # noqa: E402
    ShopCustomerAddress,
    ShopCustomerWishlist,
)
from models.shop_customer_support import ShopSupportTicket  # noqa: E402
from models.shop_multibot import ShopBot, ShopStore  # noqa: E402
from models.shop_staff import ShopStaff  # noqa: E402
from models.shop_staff_store import ShopStaffStoreAccess  # noqa: E402
from models.shop_store_commerce import (  # noqa: E402
    ShopBotCommercePolicy,
    ShopBotPaymentAccess,
    ShopPaymentAccount,
)
from services import shop_admin_security as security  # noqa: E402
from services.shop_bot_context import resolve_bot_context  # noqa: E402
from services.shop_digital_catalog import (  # noqa: E402
    add_license_batch,
    set_private_product_file,
)
from services.shop_multibot_dispatch import dispatch  # noqa: E402
from services.shop_payment_accounts import _encrypt  # noqa: E402
from services.shop_uom import seed_store_units  # noqa: E402
from models.shop_uom import default_unit_id  # noqa: E402

MANIFEST = Path("/qa/beta-fixture.json")
PDF_V1 = b"%PDF-1.4\n% isolated Beta QA private file version 1\n%%EOF\n"
HOME = {
    "shop:categories",
    "ux:search",
    "shop:cart",
    "shop:orders",
    "ux:account",
    "ux:support",
}


class FakeTelegram:
    """Record native Telegram calls with no SDK client or network capability."""

    token = "999000000:" + "A" * 35

    def __init__(self) -> None:
        """Initialize independent per-bot native message and invoice receipts."""
        self.messages: list[dict] = []
        self.invoices: list[dict] = []
        self.documents: list[dict] = []
        self.acknowledged: list[str] = []
        self.precheckout: list[dict] = []
        self.fail_invoice = False
        self.fail_delivery = False

    async def send_message(self, **payload):
        """Capture real TelegramTransport output and confirm one Message ID."""
        markup = payload.get("reply_markup")
        if markup is not None:
            payload["reply_markup"] = markup.model_dump(exclude_none=True)
        self.messages.append(payload)
        if self.fail_delivery:
            raise TimeoutError("Synthetic ambiguous provider outcome")
        return SimpleNamespace(message_id=len(self.messages) + 100)

    async def send_document(self, **payload):
        """Read the exact private file supplied to the native upload adapter."""
        document = payload["document"]
        self.documents.append(
            {
                "sha256": hashlib.sha256(Path(document.path).read_bytes()).hexdigest(),
                "chat_id": payload["chat_id"],
                "protected": payload.get("protect_content"),
            }
        )
        if self.fail_delivery:
            raise TimeoutError("Synthetic ambiguous provider outcome")
        return SimpleNamespace(message_id=len(self.documents) + 1000)

    async def answer_callback_query(self, **payload):
        """Record that the native callback spinner is acknowledged."""
        self.acknowledged.append(payload["callback_query_id"])
        return True

    async def answer_pre_checkout_query(self, **payload):
        """Record a native, bounded precheckout answer without charging anyone."""
        self.precheckout.append(payload)
        return True

    async def send_invoice(self, **payload):
        """Accept one synthetic invoice, optionally lose its response."""
        self.invoices.append(payload)
        if self.fail_invoice:
            raise TimeoutError("Synthetic invoice response timeout")
        return SimpleNamespace(message_id=len(self.invoices) + 2000)

    async def refund_star_payment(self, **payload):
        """Simulate an acknowledged refund, without financial provider access."""
        self.precheckout.append({"fake_refund": payload})
        return True


class FakeBaleResponse:
    """Minimal asynchronous HTTP response used only by the native Bale adapter."""

    status = 200

    def __init__(self, result: dict) -> None:
        """Retain one deterministic fake Provider envelope."""
        self.result = result

    async def __aenter__(self):
        """Expose the response through aiohttp's context-manager protocol."""
        return self

    async def __aexit__(self, *_args):
        """Release no resources, because no network connection exists."""
        return False

    async def json(self, **_kwargs):
        """Return the official response shape, rather than bypassing its parser."""
        return {"ok": True, "result": self.result}


class FakeBaleSession:
    """Intercept every native Bale HTTP request before any network exists."""

    def __init__(self) -> None:
        """Initialize bot-local transport evidence and transaction inquiry data."""
        self.messages: list[dict] = []
        self.invoices: list[dict] = []
        self.documents: list[dict] = []
        self.acknowledged: list[str] = []
        self.transactions: dict[str, dict] = {}
        self.fail_delivery = False

    def post(self, url: str, *, json=None, data=None, **_kwargs):
        """Model the official JSON/multipart API boundary with synthetic replies."""
        method = url.rsplit("/", 1)[-1]
        body = json or {}
        result = {"message_id": len(self.messages) + len(self.documents) + 100}
        if method == "sendMessage":
            self.messages.append(body)
        elif method == "sendInvoice":
            self.invoices.append(body)
        elif method == "answerCallbackQuery":
            self.acknowledged.append(body["callback_query_id"])
        elif method == "inquireTransaction":
            key = str(body.get("transaction_id", body.get("id", "")))
            result = self.transactions.get(key, {"status": "unpaid"})
        elif method == "sendDocument":
            fields = {field[0]["name"]: field[2] for field in data._fields}
            self.documents.append(
                {
                    "sha256": hashlib.sha256(fields["document"].read()).hexdigest(),
                    "chat_id": int(fields["chat_id"]),
                }
            )
        elif method != "answerPreCheckoutQuery":
            raise AssertionError("Unexpected fake Bale API method")
        if self.fail_delivery and method in {"sendMessage", "sendDocument"}:
            raise TimeoutError("Synthetic ambiguous provider outcome")
        return FakeBaleResponse(result)


def callbacks(message: dict) -> list[str]:
    """Read callback payloads from actual native inline keyboard serialization."""
    return [
        button["callback_data"]
        for row in (message.get("reply_markup") or {}).get("inline_keyboard", [])
        for button in row
        if "callback_data" in button
    ]


def inbound(user_id: int, *, action=None, message=None, contact=None) -> dict:
    """Build raw provider input without allowing the payload to choose a Bot."""
    actor = {"id": user_id, "first_name": "مشتری آزمایشی"}
    body = {
        "message_id": 1,
        "from": actor,
        "chat": {"id": user_id, "type": "private"},
    }
    if action:
        return {
            "callback_query": {
                "id": uuid4().hex,
                "from": actor,
                "message": body,
                "data": action,
            }
        }
    if contact is not None:
        body["contact"] = contact
    else:
        body["text"] = message or "/start"
    return {"message": body}


async def seed() -> dict:
    """Create synthetic Stores, explicit Bot grants, terms and private inventory."""
    suffix = uuid4().hex[:10]
    fixture = {"stores": [str(uuid4()), str(uuid4())], "bots": {}}
    async with session_maker() as db:
        assert await db.scalar(text("SELECT current_database()")) == "shop_codespace"
        assert await db.scalar(text("SELECT current_user")) == "shop_codespace"
        admin = await db.scalar(
            select(ShopStaff).where(ShopStaff.username == "shopadmin")
        )
        assert admin is not None, "Guarded bootstrap must create the QA administrator"
        fixture["admin_id"] = admin.id
        for index, store_id in enumerate(fixture["stores"]):
            db.add(
                ShopStore(
                    id=store_id,
                    slug=f"qa-beta-{suffix}-{index}",
                    name=f"فروشگاه آزمایشی {index + 1} {suffix}",
                    state="active",
                )
            )
        await db.flush()
        for store_id in fixture["stores"]:
            await db.run_sync(lambda sync, sid=store_id: seed_store_units(sync, sid))
            db.add(
                ShopStaffStoreAccess(
                    staff_id=admin.id,
                    store_id=store_id,
                    access_level="manager",
                    is_active=True,
                    changed_by=admin.id,
                )
            )
            db.add(
                ShopStoreCheckoutPolicy(
                    store_id=store_id,
                    mode="instant",
                    terms_version="qa-v1",
                    terms_text="شرایط فروش آزمایشی: ارسال کالا پس از تأیید پرداخت و ثبت رسید انجام می‌شود.",
                )
            )
        for key, platform, store_index in (
            ("telegram", "telegram", 0),
            ("telegram_second", "telegram", 0),
            ("bale", "bale", 0),
            ("foreign", "telegram", 1),
        ):
            bot_id = str(uuid4())
            fixture["bots"][key] = bot_id
            db.add(
                ShopBot(
                    id=bot_id,
                    store_id=fixture["stores"][store_index],
                    slug=f"qa-{key}-{suffix}",
                    name=f"QA {key}",
                    platform=platform,
                    status="active",
                    runtime_owner="registry",
                    credential_version=1,
                )
            )
        await db.flush()
        for bot_id in fixture["bots"].values():
            db.add(
                ShopBotCommercePolicy(
                    bot_id=bot_id, cart_enabled=True, credit_enabled=True
                )
            )
        category = ShopCategory(store_id=fixture["stores"][0], name="دستهٔ آزمایشی")
        db.add(category)
        await db.flush()
        fixture["products"] = {}
        for key, kind, stock in (
            ("physical", "physical", 50),
            ("file", "digital", 50),
            ("license", "digital", 0),
            ("stock", "physical", 0),
        ):
            product = Product(
                store_id=fixture["stores"][0],
                category_id=category.id,
                uom_id=default_unit_id(fixture["stores"][0]),
                sku=f"QA-{key}-{suffix}",
                name=f"محصول آزمایشی {key}",
                description="توضیح فارسی قابل جستجو",
                price=1000,
                price_stars=7 if kind == "digital" else None,
                stock_quantity=stock,
                product_type=kind,
                requires_shipping=kind == "physical",
                is_published=True,
            )
            db.add(product)
            await db.flush()
            fixture["products"][key] = product.id
            for bot_key in ("telegram", "telegram_second", "bale"):
                db.add(
                    ShopBotProductRule(
                        bot_id=fixture["bots"][bot_key],
                        product_id=product.id,
                        effect="allow",
                        updated_by=admin.id,
                    )
                )
        foreign = Product(
            store_id=fixture["stores"][1],
            uom_id=default_unit_id(fixture["stores"][1]),
            sku=f"QA-foreign-{suffix}",
            name="کالای محرمانهٔ فروشگاه دوم",
            description="نباید در فروشگاه اول دیده شود",
            price=2000,
            stock_quantity=10,
            is_published=True,
        )
        db.add(foreign)
        shipping = ShopShippingMethod(
            store_id=fixture["stores"][0],
            name="پست آزمایشی",
            price_irr=500,
            is_active=True,
        )
        db.add(shipping)
        await db.flush()
        fixture["foreign_product"] = foreign.id
        fixture["shipping_id"] = shipping.id
        for platform, rail in (
            ("telegram", "telegram_fiat"),
            ("telegram", "telegram_stars"),
            ("bale", "bale_wallet"),
        ):
            account_id = str(uuid4())
            db.add(
                ShopPaymentAccount(
                    id=account_id,
                    store_id=fixture["stores"][0],
                    platform=platform,
                    rail_type=rail,
                    name=f"QA {rail}",
                    currency="XTR" if rail == "telegram_stars" else "IRR",
                    state="active",
                    credential_ciphertext=None
                    if rail == "telegram_stars"
                    else _encrypt(
                        account_id=account_id,
                        platform=platform,
                        rail_type=rail,
                        token="qa-provider-token-never-live-000000",
                    ),
                )
            )
            await db.flush()
            db.add(
                ShopBotPaymentAccess(
                    bot_id=fixture["bots"][platform],
                    payment_account_id=account_id,
                    enabled=True,
                    priority=1,
                )
            )
        await db.commit()
        upload = UploadFile(
            file=BytesIO(PDF_V1),
            filename="qa-private.pdf",
            headers=Headers({"content-type": "application/pdf"}),
        )
        asset = await set_private_product_file(
            db,
            store_id=fixture["stores"][0],
            product_id=fixture["products"]["file"],
            uploaded=upload,
        )
        fixture["file_sha256"] = hashlib.sha256(PDF_V1).hexdigest()
        fixture["asset"] = asset
        await add_license_batch(
            db,
            store_id=fixture["stores"][0],
            product_id=fixture["products"]["license"],
            codes=[f"QA-ONE-TIME-{suffix}-{index:03d}" for index in range(30)],
        )

        # Use the normal enrollment functions with synthetic historical time,
        # leaving the current authenticator step unused for the browser login.
        def enroll(sync):
            profile = security.profile_for(sync, admin.id)
            if not profile.mfa_secret:
                instant = datetime.now(timezone.utc) - timedelta(seconds=60)
                secret = security.begin_mfa(sync, profile, now=instant)
                security.confirm_mfa(
                    sync,
                    profile,
                    security.totp(secret, instant.timestamp()),
                    now=instant,
                )

        await db.run_sync(enroll)
        await db.commit()
        from models.shop_staff_store import ShopStaffStorePreference
        from services.shop_store_context import save_default

        preference = await db.get(ShopStaffStorePreference, admin.id)
        await save_default(
            db,
            staff_id=admin.id,
            store_id=fixture["stores"][0],
            expected_version=preference.version if preference else 0,
        )
    MANIFEST.write_text(json.dumps(fixture), encoding="utf-8")
    print(
        "PASS  Seed: two PostgreSQL Stores, four Bots, private assets, explicit payment grants"
    )
    return fixture


async def context(fixture: dict, bot_key: str):
    """Resolve the same trusted context used after provider authentication."""
    async with session_maker() as db:
        return await resolve_bot_context(
            db,
            authenticated_bot_id=fixture["bots"][bot_key],
            authenticated_platform=Platform.BALE
            if bot_key == "bale"
            else Platform.TELEGRAM,
        )


async def menus(fixture: dict) -> None:
    """Exercise actual raw dispatch, six menus, forms, ACL and native keyboards."""
    identity_customers = []
    for bot_key in ("telegram", "bale"):
        scope = await context(fixture, bot_key)
        native = FakeTelegram() if bot_key == "telegram" else FakeBaleSession()
        client = (
            native if bot_key == "telegram" else BaleTransport("qa-fake-token", native)
        )
        user_id = 700_000_000 + uuid4().int % 1_000_000

        async def ask(*, action=None, message=None, contact=None):
            outcome = await dispatch(
                scope,
                client,
                inbound(
                    user_id,
                    action=action,
                    message=message,
                    contact=contact,
                ),
            )
            assert outcome["status"] == "processed", "A visible menu action was ignored"
            answer = native.messages[-1]
            assert 1 <= len(answer["text"]) <= 4096
            assert all(1 <= len(value.encode()) <= 64 for value in callbacks(answer))
            return answer

        home = await ask(message="/start")
        assert set(callbacks(home)) == HOME, "The six Home actions differ by platform"
        for action in HOME:
            await ask(action=action)
            await ask(action="shop:home")
        await ask(action="ux:search")
        found = await ask(message="توضیح فارسی")
        assert any(value.startswith("shop:item:") for value in callbacks(found)), (
            "Persian product search returned no match",
            found["text"],
        )
        assert f"shop:item:{fixture['foreign_product']}" not in callbacks(found), (
            "Cross-Store search result button leaked"
        )
        async with session_maker() as db:
            product = await db.get(Product, fixture["products"]["physical"])
            sku = product.sku
        await ask(action="ux:search:field:sku")
        by_sku = await ask(message=sku)
        assert callbacks(by_sku).count(f"shop:item:{product.id}") == 1
        await ask(action="shop:home")
        await ask(action=f"shop:item:{fixture['foreign_product']}")
        assert "محرمانه" not in native.messages[-1]["text"], (
            "Foreign product callback leaked"
        )
        await ask(action="ux:address:new")
        await ask(
            message="خانه|مشتری آزمایشی|09123456789|تهران|تهران|خیابان نمونه پلاک ۱۲|1234567890"
        )
        async with session_maker() as db:
            identity = await db.scalar(
                select(ShopIdentity).where(
                    ShopIdentity.bot_id == scope.bot_id,
                    ShopIdentity.platform_user_id == user_id,
                )
            )
            identity_customers.append(identity.customer_id)
            address = await db.scalar(
                select(ShopCustomerAddress).where(
                    ShopCustomerAddress.customer_id == identity.customer_id,
                )
            )
            assert address is not None, "Address was not persisted"
            address_id = address.id
        await ask(action=f"ux:address:choose:{address_id}")
        await ask(action=f"ux:wish:toggle:{fixture['products']['physical']}")
        await ask(action="ux:wishlist")
        await ask(action="ux:phone")
        await ask(contact={"user_id": user_id + 1, "phone_number": "09123456789"})
        await ask(contact={"user_id": user_id, "phone_number": "09123456789"})
        await ask(action="ux:notify:on")
        await ask(action="ux:notify:off")
        await ask(action="ux:ticket:new")
        await ask(action="ux:ticket:topic:general")
        await ask(message="درخواست پشتیبانی آزمایشی برای بررسی چرخهٔ کامل")
        await ask(action="ux:tickets")
        await ask(action="ux:search")
        await ask(message="/cancel")
        async with session_maker() as db:
            ticket_count = await db.scalar(
                select(func.count())
                .select_from(ShopSupportTicket)
                .where(
                    ShopSupportTicket.bot_id == scope.bot_id,
                )
            )
            assert ticket_count > 0, "Support ticket was not persisted"
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(ShopCustomerWishlist)
                    .where(
                        ShopCustomerWishlist.customer_id == identity.customer_id,
                    )
                )
                == 1
            ), "Wishlist ownership was not persisted"
        assert native.acknowledged, "Native callbacks were not acknowledged"
        print(
            f"PASS  {bot_key}: six menus, Persian search, address, Contact, wishlist, support, cancel, ACL"
        )
    assert len(set(identity_customers)) == 2, (
        "Equal Telegram/Bale numeric IDs were merged"
    )


async def main() -> int:
    """Run only requested, isolated scenarios and return failure on any assertion."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("seed", "menus", "all"), default="all")
    args = parser.parse_args()
    try:
        fixture = (
            await seed()
            if args.stage in {"seed", "all"} or not MANIFEST.exists()
            else json.loads(MANIFEST.read_text())
        )
        if args.stage in {"menus", "all"}:
            await menus(fixture)
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
