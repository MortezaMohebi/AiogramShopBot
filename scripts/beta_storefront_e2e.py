"""Execute provider-free customer journeys against real Codespace PostgreSQL.

Run only with compose.beta-qa.yml. Provider SDK calls terminate in explicit
in-memory test transports; no HTTP session capable of sending a bot request
is created. Fixtures are synthetic and additive; no database is ever reset.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
from json import loads
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
from aiogram.exceptions import TelegramBadRequest  # noqa: E402
from aiogram.methods import EditMessageText  # noqa: E402

from channels.bale import BaleTransport  # noqa: E402
from channels.contracts import BotReply, InlineAction, Platform, ViewOutcome  # noqa: E402
from channels.telegram import TelegramTransport  # noqa: E402
from db import engine, session_maker  # noqa: E402
from models.shop_bot_catalog_acl import ShopBotProductRule  # noqa: E402
from models.shop_checkout import ShopCart, ShopCartItem, ShopShippingMethod  # noqa: E402
from models.shop_checkout_policy import ShopStoreCheckoutPolicy  # noqa: E402
from models.shop_content import Product, ShopCategory, ShopIdentity  # noqa: E402
from models.shop_customer_account_data import (  # noqa: E402
    ShopCustomerAddress,
    ShopCustomerWishlist,
)
from models.shop_customer_navigation import ShopCustomerChatState  # noqa: E402
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
    "shop:list:0",
    "ux:search",
    "shop:cart",
    "shop:orders",
    "ux:account",
    "ux:support",
}


class NativeMessageLog:
    """Keep immutable reply snapshots alongside current fake provider state."""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.current: dict[int, dict] = {}
        self.calls: list[tuple[str, dict]] = []
        self.next_message_id = 100
        self.outcomes: dict[str, str] = {}
        self.pauses: dict[str, tuple[asyncio.Event, asyncio.Event]] = {}

    def outcome(self, method: str, payload: dict) -> str | None:
        """Record an attempt and consume a one-shot error instruction."""
        self.calls.append((method, deepcopy(payload)))
        return self.outcomes.pop(method, None)

    async def pause(self, method: str) -> None:
        """Hold one fake network response until a concurrency probe releases it."""
        events = self.pauses.pop(method, None)
        if events is not None:
            entered, release = events
            entered.set()
            await asyncio.wait_for(release.wait(), timeout=20)

    def remember(self, payload: dict, *, edit: bool = False) -> dict:
        """Return a positive ID for a send and retain it on an edit."""
        if edit:
            message_id = payload["message_id"]
        else:
            self.next_message_id += 1
            message_id = self.next_message_id
        snapshot = deepcopy(payload)
        snapshot["message_id"] = message_id
        snapshot["text"] = snapshot.get("text") or snapshot.get("caption") or ""
        self.messages.append(snapshot)
        self.current[message_id] = snapshot
        return snapshot

    def retire(self, payload: dict) -> None:
        """Remove markup without removing or rewriting historical content."""
        message_id = payload["message_id"]
        if message_id in self.current:
            self.current[message_id] = {
                **self.current[message_id], "reply_markup": payload.get("reply_markup"),
            }


class FakeTelegram(NativeMessageLog):
    """Record native Telegram calls with no SDK client or network capability."""

    token = "999000000:" + "A" * 35

    def __init__(self) -> None:
        """Initialize independent per-bot native message and invoice receipts."""
        super().__init__()
        self.invoices: list[dict] = []
        self.documents: list[dict] = []
        self.acknowledged: list[str] = []
        self.precheckout: list[dict] = []
        self.fail_invoice = False
        self.fail_delivery = False

    async def _message(self, method, payload, *, edit=False, photo=False):
        """Capture real TelegramTransport output and model typed API failures."""
        markup = payload.get("reply_markup")
        if markup is not None and hasattr(markup, "model_dump"):
            payload["reply_markup"] = markup.model_dump(exclude_none=True)
        action = self.outcome(method, payload)
        await self.pause(method)
        if action is None and edit and payload["message_id"] not in self.current:
            action = "missing"
        if action is None and method == "editMessageText" and (
            "caption" in self.current[payload["message_id"]]
        ):
            action = "not_text"
        if action in {"missing", "not_text", "unchanged", "invalid"}:
            description = {
                "missing": "Bad Request: message to edit not found",
                "not_text": "Bad Request: there is no text in the message to edit",
                "unchanged": "Bad Request: message is not modified",
                "invalid": "Bad Request: BUTTON_DATA_INVALID",
            }[action]
            raise TelegramBadRequest(
                method=EditMessageText(text=payload.get("text") or "QA"),
                message=description,
            )
        if method == "editMessageReplyMarkup":
            self.retire(payload)
            result = self.current[payload["message_id"]]
        else:
            result = self.remember(payload, edit=edit)
        if action == "unknown" or self.fail_delivery:
            raise TimeoutError("Synthetic ambiguous provider outcome")
        return SimpleNamespace(
            message_id=result["message_id"],
            photo=[SimpleNamespace(file_id="qa-telegram-photo")] if photo else [],
        )

    async def send_message(self, **payload):
        """Confirm one native message."""
        return await self._message("sendMessage", payload)

    async def send_photo(self, **payload):
        """Confirm an independent native preview."""
        payload.pop("photo", None)
        return await self._message("sendPhoto", payload, photo=True)

    async def edit_message_text(self, **payload):
        """Keep the same provider ID while replacing text and controls."""
        return await self._message("editMessageText", payload, edit=True)

    async def edit_message_media(self, **payload):
        """Retain the same provider ID and expose the new media caption."""
        payload["caption"] = payload.pop("media").caption
        return await self._message("editMessageMedia", payload, edit=True, photo=True)

    async def edit_message_caption(self, **payload):
        """Retain the media and replace its caption."""
        return await self._message("editMessageCaption", payload, edit=True, photo=True)

    async def edit_message_reply_markup(self, **payload):
        """Retire old markup while preserving the referenced message."""
        return await self._message("editMessageReplyMarkup", payload, edit=True)

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

    def __init__(
        self, result: dict, *, status: int = 200, description: str = "",
        before_response=None,
    ) -> None:
        """Retain one deterministic fake Provider envelope."""
        self.result = result
        self.status = status
        self.description = description
        self.before_response = before_response

    async def __aenter__(self):
        """Expose the response through aiohttp's context-manager protocol."""
        if self.before_response is not None:
            await self.before_response()
        return self

    async def __aexit__(self, *_args):
        """Release no resources, because no network connection exists."""
        return False

    async def json(self, **_kwargs):
        """Return the official response shape, rather than bypassing its parser."""
        if self.status >= 400:
            return {
                "ok": False, "error_code": self.status,
                "description": self.description,
            }
        return {"ok": True, "result": self.result}


class FakeBaleSession(NativeMessageLog):
    """Intercept every native Bale HTTP request before any network exists."""

    def __init__(self) -> None:
        """Initialize bot-local transport evidence and transaction inquiry data."""
        super().__init__()
        self.invoices: list[dict] = []
        self.documents: list[dict] = []
        self.acknowledged: list[str] = []
        self.transactions: dict[str, dict] = {}
        self.fail_delivery = False

    def post(self, url: str, *, json=None, data=None, **_kwargs):
        """Model the official JSON/multipart API boundary with synthetic replies."""
        method = url.rsplit("/", 1)[-1]
        body = dict(json or {})
        if method == "sendPhoto" and data is not None:
            fields = {field[0]["name"]: field[2] for field in data._fields}
            body = {
                "chat_id": int(fields["chat_id"]),
                "caption": fields.get("caption", ""),
                "reply_markup": loads(fields.get("reply_markup", "null")),
            }
        action = self.outcome(method, body)
        edit = method.startswith("editMessage")
        if action is None and edit and body["message_id"] not in self.current:
            action = "missing"
        if action is None and method == "editMessageText" and (
            "caption" in self.current[body["message_id"]]
        ):
            action = "not_text"
        if action in {"missing", "not_text", "unchanged", "invalid", "limited"}:
            description = {
                "missing": "message to edit not found",
                "not_text": "there is no text in the message to edit",
                "unchanged": "message is not modified",
                "invalid": "BUTTON_DATA_INVALID",
                "limited": "Too Many Requests",
            }[action]
            return FakeBaleResponse(
                {}, status=429 if action == "limited" else 400, description=description,
            )

        async def before_response():
            await self.pause(method)
            if action == "unknown" or (
                self.fail_delivery and method in {"sendMessage", "sendDocument"}
            ):
                raise TimeoutError("Synthetic ambiguous provider outcome")

        result = {"message_id": len(self.messages) + len(self.documents) + 100}
        if method in {"sendMessage", "sendPhoto", "editMessageText", "editMessageCaption"}:
            result = self.remember(body, edit=edit)
            if method == "sendPhoto":
                result = {**result, "photo": [{"file_id": "qa-bale-photo"}]}
        elif method == "editMessageReplyMarkup":
            self.retire(body)
            result = self.current[body["message_id"]]
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
        return FakeBaleResponse(result, before_response=before_response)


def callbacks(message: dict) -> list[str]:
    """Read callback payloads from actual native inline keyboard serialization."""
    return [
        button["callback_data"]
        for row in (message.get("reply_markup") or {}).get("inline_keyboard", [])
        for button in row
        if "callback_data" in button
    ]


def inbound(
    user_id: int, *, action=None, message=None, contact=None,
    message_id=None, callback_id=None, update_id=None,
) -> dict:
    """Build raw provider input without allowing the payload to choose a Bot."""
    actor = {"id": user_id, "first_name": "مشتری آزمایشی"}
    body = {
        "message_id": message_id if message_id is not None else uuid4().int % 1_000_000 + 1,
        "from": actor,
        "chat": {"id": user_id, "type": "private"},
    }
    if action:
        if type(message_id) is not int or message_id <= 0:
            raise ValueError("A synthetic tap needs the provider-issued message ID.")
        return {
            "update_id": update_id if update_id is not None else uuid4().int % (2**31 - 1),
            "callback_query": {
                "id": callback_id or "qa-" + uuid4().hex,
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


@dataclass(frozen=True)
class VisibleTap:
    """A previously rendered native callback and the message that owns it."""

    message_id: int
    data: str


class StorefrontJourney:
    """Drive actual chat controls without provider credentials or network."""

    def __init__(self, scope, user_id: int) -> None:
        self.scope = scope
        self.user_id = user_id
        self.native = (
            FakeTelegram() if scope.platform == Platform.TELEGRAM else FakeBaleSession()
        )
        self.client = self.native if isinstance(self.native, FakeTelegram) else BaleTransport(
            "qa-fake-token", self.native, bot_id=scope.bot_id,
        )

    async def actions(self, reply: dict | None = None) -> dict[str, VisibleTap]:
        """Resolve only actions present in a recorded provider reply."""
        if reply is None:
            assert self.native.messages, "No provider reply to inspect"
            reply = self.native.messages[-1]
        payloads = callbacks(reply)
        message_id = reply["message_id"]
        result = {
            data: VisibleTap(message_id, data)
            for data in payloads if not data.startswith("v1:")
        }
        if not any(data.startswith("v1:") for data in payloads):
            return result
        async with session_maker() as db:
            state = await db.get(
                ShopCustomerChatState, (self.scope.bot_id, self.user_id),
            )
            assert state and state.store_id == self.scope.store_id
            assert state.ui_message_id == message_id
            view = state.view_state["active"]
        for slot, logical in enumerate(view["actions"]):
            data = f"v1:{view['generation']}:{slot}"
            if data in payloads:
                result[logical] = VisibleTap(message_id, data)
        assert {tap.data for tap in result.values()} == set(payloads), (
            "Fake reply controls differ from the actual provider message"
        )
        return result

    async def prepare(self, action: str, reply: dict | None = None) -> VisibleTap:
        """Select a visible action before dispatch, allowing intentional replays."""
        actions = await self.actions(reply)
        assert action in actions, (action, tuple(actions))
        return actions[action]

    async def tap(
        self, tap: VisibleTap, *, callback_id: str | None = None, **dispatch_options,
    ) -> dict:
        """Submit one distinct update for this exact provider button."""
        return await dispatch(
            self.scope, self.client, inbound(
                self.user_id, action=tap.data, message_id=tap.message_id,
                callback_id=callback_id,
            ),
            **dispatch_options,
        )

    async def ask(self, action=None, *, message=None, contact=None) -> dict:
        """Follow a visible control or supply ordinary text or native contact."""
        if action is not None:
            outcome = await self.tap(await self.prepare(action))
        else:
            outcome = await dispatch(
                self.scope, self.client,
                inbound(self.user_id, message=message, contact=contact),
            )
        assert outcome["status"] in {"processed", "invoice_requested"}, outcome
        answer = self.native.messages[-1]
        assert 1 <= len(answer["text"]) <= 4096
        assert all(1 <= len(value.encode()) <= 64 for value in callbacks(answer))
        return answer

    async def open_product(self, product_id: int) -> dict:
        """Open one seeded product through the shopper's search interface."""
        async with session_maker() as db:
            product = await db.get(Product, product_id)
            assert product is not None and product.store_id == self.scope.store_id
            name = product.name
        await self.ask(message="/search")
        reply = await self.ask(message=name)
        actions = await self.actions(reply)
        item = next((
            key for key in actions
            if key.startswith(("shop:item:", "ux:search:item:"))
            and key.endswith(f":{product_id}")
        ), None)
        if f"shop:add:{product_id}" not in actions and item is not None:
            reply = await self.ask(item)
        assert name in reply["text"], reply["text"]
        return reply

    async def add_address(self) -> str:
        """Use separate wizard turns and return the explicit choose action."""
        await self.ask("ux:address:new")
        async with session_maker() as db:
            state = await db.get(
                ShopCustomerChatState, (self.scope.bot_id, self.user_id),
            )
            step = state.context_ref
        if step == "recipient":
            await self.ask(message="مشتری آزمایشی")
            step = "phone"
        if step == "phone":
            await self.ask(message="09123456789")
        await self.ask("ux:address:province:7")
        await self.ask("ux:address:city:0")
        await self.ask(message="خیابان نمونه پلاک ۱۲")
        await self.ask("ux:address:next")
        await self.ask("ux:address:confirm")
        matches = [
            action for action in await self.actions()
            if action.startswith("ux:address:choose:")
        ]
        assert len(matches) == 1
        return matches[0]


async def seed(*, persist_manifest: bool = True) -> dict:
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

        if persist_manifest:
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
        else:
            await db.commit()
    if persist_manifest:
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
    # Deliberately reuse the same native numeric ID on the two providers.
    user_id = 700_000_000 + uuid4().int % 1_000_000
    for bot_key in ("telegram", "bale"):
        scope = await context(fixture, bot_key)
        journey = StorefrontJourney(scope, user_id)
        native = journey.native
        ask = journey.ask

        home = await ask(message="/start")
        assert set(await journey.actions(home)) <= HOME
        shortcuts = {
            "shop:list:0": "🛍 فروشگاه",
            "shop:cart": "🛒 سبد خرید",
            "shop:orders": "📦 سفارش‌های من",
            "ux:support": "💬 پشتیبانی",
        }
        for action in sorted(HOME):
            home = await ask(message="/start")
            if action in await journey.actions(home):
                await ask(action)
            else:
                # The pre-repair baseline puts four destinations solely in the
                # Reply Keyboard. Use only a label the fake actually received.
                label = shortcuts[action]
                assert any(
                    button["text"] == label
                    for msg in native.messages
                    for row in (msg.get("reply_markup") or {}).get("keyboard", [])
                    for button in row
                ), label
                await ask(message=label)
        await ask(message="/search")
        found = await ask(message="توضیح فارسی")
        assert "نتیجه" in found["text"], found["text"]
        assert all(
            not action.endswith(f":{fixture['foreign_product']}")
            for action in await journey.actions(found)
        ), "Cross-Store search result button leaked"
        async with session_maker() as db:
            product = await db.get(Product, fixture["products"]["physical"])
            product_name, sku = product.name, product.sku
        fields = await ask(message="/search")
        if "ux:search:field:sku" not in await journey.actions(fields):
            options = next(
                action for action in await journey.actions(fields)
                if action.startswith("ux:search:filter")
            )
            await ask(options)
        await ask("ux:search:field:sku")
        by_sku = await ask(message=sku)
        assert product_name in by_sku["text"]
        # Deliberately inject a forged legacy action. All legitimate taps above
        # and below use controls and IDs emitted by the fake provider.
        await journey.tap(VisibleTap(
            by_sku["message_id"], f"shop:item:{fixture['foreign_product']}",
        ))
        assert "محرمانه" not in native.messages[-1]["text"], (
            "Foreign product callback leaked"
        )
        await ask(message="/address")
        choose_address = await journey.add_address()
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
            assert choose_address == f"ux:address:choose:{address.id}"
        await ask(choose_address)
        await journey.open_product(fixture["products"]["physical"])
        await ask(f"ux:wish:toggle:{fixture['products']['physical']}")
        await ask(message="/wishlist")
        await ask(message="/profile")
        await ask("ux:phone")
        await ask(contact={"user_id": user_id + 1, "phone_number": "09123456789"})
        await ask("ux:profile")
        await ask("ux:phone")
        await ask(contact={"user_id": user_id, "phone_number": "09123456789"})
        for preference in ("ux:notify:on", "ux:notify:off"):
            account = await ask(message="/account")
            if "ux:notifications" not in await journey.actions(account):
                group = next(
                    action for action in await journey.actions(account)
                    if action.startswith("ux:account:") and "settings" in action
                )
                await ask(group)
            await ask("ux:notifications")
            await ask(preference)
        await ask(message="/support")
        await ask("ux:ticket:new")
        await ask("ux:ticket:topic:general")
        await ask(message="درخواست پشتیبانی آزمایشی برای بررسی چرخهٔ کامل")
        await ask("ux:tickets")
        await ask(message="/search")
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


async def check_fakes() -> None:
    """Exercise the native fake boundary without touching PostgreSQL."""
    user_id = 101
    reply = BotReply("نمونه", ((InlineAction("ادامه", "shop:home"),),))
    for native in (FakeTelegram(), FakeBaleSession()):
        transport = (
            TelegramTransport(native) if isinstance(native, FakeTelegram)
            else BaleTransport("qa-fake-token", native)
        )
        sent = await transport.send_view(user_id, reply)
        assert sent.outcome == ViewOutcome.CONFIRMED and sent.message_id > 0
        assert callbacks(native.current[sent.message_id]) == ["shop:home"]
        edited = await transport.send_view(
            user_id, reply, edit_message_id=sent.message_id,
        )
        assert edited.message_id == sent.message_id
        for injection, expected in (
            ("unchanged", ViewOutcome.NO_CHANGE),
            ("missing", ViewOutcome.CANNOT_EDIT),
            ("unknown", ViewOutcome.UNKNOWN),
        ):
            native.outcomes["editMessageText"] = injection
            result = await transport.send_view(
                user_id, reply, edit_message_id=sent.message_id,
            )
            assert result.outcome == expected, result
        assert sum(method == "sendMessage" for method, _ in native.calls) == 1
        await transport.clear_inline(user_id, sent.message_id)
        assert callbacks(native.current[sent.message_id]) == []
    print("PASS  Native fakes: positive IDs, same-ID edits, markup, and classified outcomes")


async def cart_quantity(journey: StorefrontJourney, product_id: int) -> int:
    """Observe committed real PostgreSQL cart effects through a separate session."""
    async with session_maker() as db:
        return int(await db.scalar(
            select(ShopCartItem.quantity)
            .join(ShopCart, ShopCart.id == ShopCartItem.cart_id)
            .where(
                ShopCart.bot_id == journey.scope.bot_id,
                ShopCart.store_id == journey.scope.store_id,
                ShopCart.platform_user_id == journey.user_id,
                ShopCartItem.product_id == product_id,
            )
        ) or 0)


async def advisory_owners() -> set[int]:
    """Read checked-out PostgreSQL session lock owners in this test database."""
    async with session_maker() as db:
        return set(await db.scalars(text(
            "SELECT DISTINCT pid FROM pg_locks WHERE locktype = 'advisory' "
            "AND granted AND database = ("
            "SELECT oid FROM pg_database WHERE datname = current_database())"
        )))


async def assert_idle_owner(pid: int) -> None:
    """Require that guarded provider I/O leaves no transaction open."""
    async with session_maker() as db:
        idle = await db.scalar(text(
            "SELECT xact_start IS NULL FROM pg_stat_activity WHERE pid = :pid"
        ), {"pid": pid})
        assert idle is True, "Navigation held an open PostgreSQL transaction"


async def verify_lease_handoff(journey: StorefrontJourney, product: int) -> None:
    """A receiver that loses its lease may not publish newly issued controls."""
    before = await cart_quantity(journey, product)
    await journey.open_product(product)
    old = await journey.prepare(f"shop:add:{product}")
    entered, release = asyncio.Event(), asyncio.Event()
    journey.native.pauses["editMessageText"] = (entered, release)
    owner_lost = False

    async def lease_check() -> None:
        if owner_lost:
            raise security.SecurityRejected("receiver_lease_lost", 503)

    task = asyncio.create_task(journey.tap(old, lease_check=lease_check))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert await cart_quantity(journey, product) == before + 1
        owner_lost = True
    finally:
        release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
    if isinstance(result, security.SecurityRejected):
        assert result.code == "receiver_lease_lost"
    else:
        assert isinstance(result, dict), result
    remote = journey.native.current[old.message_id]
    for data in callbacks(remote):
        # The provider accepted the edit, but lease fencing must make every
        # newly rendered control unusable even if it shows on a real client.
        if data.startswith("v1:"):
            status = await journey.tap(VisibleTap(old.message_id, data))
            assert status["status"] == "stale_callback", status
    assert (await journey.tap(old))["status"] == "stale_callback"
    await journey.ask(message="/start")
    assert await cart_quantity(journey, product) == before + 1
    assert journey.native.messages[-1]["message_id"] != old.message_id


async def verify_missing_view(journey: StorefrontJourney, product: int) -> None:
    """An obsolete control with no current view gets one scoped recovery."""
    tap = VisibleTap(10, f"shop:add:{product}")
    callback_id = "1qa-legacy" if journey.scope.platform == Platform.BALE else "qa-old"
    for _ in range(2):
        result = await journey.tap(tap, callback_id=callback_id)
        assert result["status"] == "stale_callback"
    assert len(journey.native.messages) == 1
    assert "shop:home" in await journey.actions()
    if journey.scope.platform == Platform.BALE:
        assert not journey.native.acknowledged, "Legacy Bale must use visible recovery"
    else:
        assert journey.native.acknowledged == [callback_id, callback_id]
    assert await cart_quantity(journey, product) == 0
    async with session_maker() as db:
        identity = await db.scalar(select(ShopIdentity).where(
            ShopIdentity.bot_id == journey.scope.bot_id,
            ShopIdentity.platform_user_id == journey.user_id,
        ))
        assert identity is None, "An obsolete action enrolled the shopper"


async def concurrency(fixture: dict) -> None:
    """Exercise distinct callbacks while one committed handler is still publishing."""
    suffix = uuid4().int % 1_000_000
    product = fixture["products"]["physical"]
    for index, bot_key in enumerate(("telegram", "bale")):
        scope = await context(fixture, bot_key)
        first = StorefrontJourney(scope, 811_000_000 + suffix + index * 2)
        other = StorefrontJourney(scope, first.user_id + 1)
        await verify_missing_view(
            StorefrontJourney(scope, first.user_id + 2_000_000), product,
        )
        await first.open_product(product)
        add = await first.prepare(f"shop:add:{product}")
        await other.open_product(product)
        unrelated_add = await other.prepare(f"shop:add:{product}")
        assert await cart_quantity(first, product) == 0
        baseline = await advisory_owners()
        entered, release = asyncio.Event(), asyncio.Event()
        first.native.pauses["editMessageText"] = (entered, release)
        task = asyncio.create_task(first.tap(add))
        waiter = duplicate = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            # The handler committed, but the provider has yet to confirm the
            # replacement view. The dedicated advisory session must still own
            # the lock, and only one added quantity may be visible.
            assert await cart_quantity(first, product) == 1
            guarded = (await advisory_owners()) - baseline
            assert len(guarded) == 1
            await assert_idle_owner(next(iter(guarded)))
            waiter = asyncio.create_task(first.tap(add))
            await asyncio.sleep(0)
            waiter.cancel()
            assert isinstance(
                (await asyncio.gather(waiter, return_exceptions=True))[0],
                asyncio.CancelledError,
            )
            duplicate = asyncio.create_task(first.tap(add))
            assert (await asyncio.wait_for(other.tap(unrelated_add), 5))["status"] == "processed"
            assert await cart_quantity(other, product) == 1
            assert await cart_quantity(first, product) == 1
        finally:
            release.set()
            outcomes = await asyncio.gather(
                *(pending for pending in (task, duplicate) if pending is not None),
                return_exceptions=True,
            )
        assert [result["status"] for result in outcomes] == ["processed", "stale_callback"]
        assert await cart_quantity(first, product) == 1
        assert await advisory_owners() == baseline
        assert first.native.messages[-1]["message_id"] == add.message_id
        assert (await first.tap(add))["status"] == "stale_callback"

        # A timed-out edit may have changed the actual native message. Do not
        # post a replacement or repeat an operation on the unknown target.
        await first.open_product(product)
        uncertain = await first.prepare(f"shop:add:{product}")
        first.native.outcomes["editMessageText"] = "unknown"
        sent_before = sum(method == "sendMessage" for method, _ in first.native.calls)
        await first.tap(uncertain)
        assert await cart_quantity(first, product) == 2
        assert sum(method == "sendMessage" for method, _ in first.native.calls) == sent_before
        assert (await first.tap(uncertain))["status"] == "stale_callback"
        sent_after_first_replay = sum(
            method == "sendMessage" for method, _ in first.native.calls
        )
        assert sent_after_first_replay <= sent_before + 1
        assert (await first.tap(uncertain))["status"] == "stale_callback"
        assert sum(
            method == "sendMessage" for method, _ in first.native.calls
        ) == sent_after_first_replay
        assert await cart_quantity(first, product) == 2
        await first.ask(message="/start")
        await verify_lease_handoff(first, product)
        assert await advisory_owners() == baseline
        print(
            f"PASS  {bot_key} PostgreSQL: one effect per view, committed lock, "
            "cancelled waiter, independent shopper, obsolete and unknown replay, "
            "lease handoff, and single recovery with no current view"
        )


async def main() -> int:
    """Run only requested, isolated scenarios and return failure on any assertion."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=("fakes", "seed", "menus", "concurrency", "all"), default="all",
    )
    args = parser.parse_args()
    try:
        if args.stage == "fakes":
            await check_fakes()
            return 0
        fixture = (
            await seed()
            if args.stage in {"seed", "all"} or not MANIFEST.exists()
            else json.loads(MANIFEST.read_text())
        )
        if args.stage in {"menus", "all"}:
            await menus(fixture)
        if args.stage in {"concurrency", "all"}:
            await concurrency(fixture)
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
