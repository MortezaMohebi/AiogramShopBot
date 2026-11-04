"""A verified, Store-owned support workflow shared by Telegram and Bale.

The Bot sender is derived from BotContext, tickets from StoreCustomer and
support content is immutable. Chat input is accepted only after a timed FSM
request, and staff notes never appear in customer history accidentally.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply, InboundEvent, InlineAction
from models.shop_content import ShopIdentity
from models.shop_customer_navigation import ShopCustomerChatState
from models.shop_customer_support import ShopSupportMessage, ShopSupportTicket
from services.shop_bot_context import BotContext
from services.shop_customer_access import customer_access_clause
from services.shop_customer_account import customer_for_bot

_TICKET_ID = re.compile(r"ux:ticket:view:([1-9][0-9]{0,18})\Z")
_TICKET_REPLY = re.compile(r"ux:ticket:reply:([1-9][0-9]{0,18})\Z")
_TICKET_TOPIC = re.compile(r"ux:ticket:topic:(general|order|payment|delivery|refund)\Z")
_TICKET_PAGE = re.compile(
    r"ux:ticket:page:([1-9][0-9]{0,18}):([1-9][0-9]{0,18}):([0-9])\Z"
)
_TICKET_TTL = timedelta(minutes=15)
_MESSAGE_PAGE_UNITS = 3500
_MAX_DATABASE_ID = 9_223_372_036_854_775_807


def is_support_action(action: str) -> bool:
    """Recognize only bounded support callbacks, including complete thread pages."""
    if action in {"ux:support", "ux:tickets", "ux:ticket:new"} or _TICKET_TOPIC.fullmatch(action):
        return True
    for pattern in (_TICKET_ID, _TICKET_REPLY, _TICKET_PAGE):
        match = pattern.fullmatch(action)
        if match and all(int(value) <= _MAX_DATABASE_ID for value in match.groups()):
            return True
    return False


def _message_pages(body: str) -> tuple[str, ...]:
    """Preserve every Unicode character within both providers' UTF-16 limits."""
    pages = []
    start = 0
    units = 0
    for position, character in enumerate(body):
        width = 2 if ord(character) > 0xFFFF else 1
        if units + width > _MESSAGE_PAGE_UNITS:
            pages.append(body[start:position])
            start = position
            units = 0
        units += width
    pages.append(body[start:])
    return tuple(pages)


def validate_ticket_body(value: str) -> str:
    """Reject empty, unbounded or control-character customer messages."""
    if (
        not isinstance(value, str) or not 1 <= len(value.strip()) <= 4000
        or any(
            not char.isprintable() and char not in {"\n", "\t", "\u200c", "\u200d"}
            for char in value
        )
    ):
        raise ValueError("Ticket message must be readable and 1-4000 characters.")
    return value.strip()


def ticket_actions(
    *pairs: tuple[str, str],
) -> tuple[tuple[InlineAction, ...], ...]:
    """Create short callbacks for native Telegram/Bale inline keyboards."""
    return tuple((InlineAction(label, action),) for label, action in pairs)


def _verified_ticket_owners(context: BotContext, customer_id: int):
    """Resolve all explicitly linked Bot Identity PKs, not numeric IDs."""
    return select(ShopIdentity.id).where(
        ShopIdentity.store_id == context.store_id,
        ShopIdentity.customer_id == customer_id,
        customer_access_clause(),
    )


async def customer_ticket(
    db: AsyncSession, context: BotContext, *,
    customer_id: int, ticket_id: int,
) -> ShopSupportTicket | None:
    """Never return a ticket by ID alone, including after identity linking."""
    if type(ticket_id) is not int or not 1 <= ticket_id <= _MAX_DATABASE_ID:
        return None
    return await db.scalar(select(ShopSupportTicket).where(
        ShopSupportTicket.id == ticket_id,
        ShopSupportTicket.store_id == context.store_id,
        ShopSupportTicket.origin_identity_id.in_(
            _verified_ticket_owners(context, customer_id),
        ),
    ))


class CustomerSupportFlow:
    """Customer-facing new ticket, list, messages and reply-by-chat flows."""

    def __init__(self, *, bot_context: BotContext) -> None:
        """Bind a provider-authenticated Bot and its Store ownership."""
        self.context = bot_context

    async def reply(
        self, event: InboundEvent, db: AsyncSession,
    ) -> BotReply | None:
        """Dispatch a support callback or pending ticket message."""
        action = event.callback_data or ""
        text = (event.text or "").strip()
        if self.context.platform != event.platform:
            raise ValueError("Support bot/provider mismatch.")

        handled = (
            is_support_action(action)
            or text in {"/support", "/paysupport", "🆘 پشتیبانی", "/ticket"}
        )
        state = None
        if not handled and text and not text.startswith("/"):
            state = await db.get(
                ShopCustomerChatState,
                (self.context.bot_id, event.user_id),
            )
            if state is None or state.action != "ticket_input":
                return None
        if not handled and state is None:
            return None
        try:
            identity, customer = await customer_for_bot(
                db, self.context, platform_user_id=event.user_id,
            )
        except ValueError:
            return BotReply("برای پشتیبانی ابتدا /start را ارسال کنید.")

        if action == "ux:support" or text in {
            "/support", "/paysupport", "🆘 پشتیبانی",
        }:
            return BotReply(
                "🆘 مرکز پشتیبانی\n"
                "درخواست جدید ثبت کنید یا وضعیت درخواست‌هایتان را ببینید. "
                "برای مشکل پرداخت، شماره سفارش و رسید را در متن بنویسید.",
                ticket_actions(
                    ("❓ پرسش‌های متداول", "shop:faq"),
                    ("✍️ درخواست جدید", "ux:ticket:new"),
                    ("📨 درخواست‌های من", "ux:tickets"),
                    ("📦 سفارش‌های من", "shop:orders"),
                    ("🏠 منوی اصلی", "shop:home"),
                ),
            )

        if action == "ux:ticket:new" or text == "/ticket":
            return BotReply(
                "موضوع درخواست پشتیبانی را انتخاب کنید:",
                ticket_actions(
                    ("❓ سؤال عمومی", "ux:ticket:topic:general"),
                    ("📦 سفارش", "ux:ticket:topic:order"),
                    ("💳 پرداخت", "ux:ticket:topic:payment"),
                    ("🚚 ارسال و تحویل", "ux:ticket:topic:delivery"),
                    ("↩️ بازپرداخت", "ux:ticket:topic:refund"),
                    ("انصراف", "ux:support"),
                ),
            )

        topic_match = _TICKET_TOPIC.fullmatch(action)
        ticket_match = _TICKET_REPLY.fullmatch(action)
        if topic_match or ticket_match:
            if ticket_match:
                ticket = await customer_ticket(
                    db, self.context, customer_id=customer.id,
                    ticket_id=int(ticket_match.group(1)),
                )
                if ticket is None or ticket.status == "closed":
                    return BotReply("درخواست قابل پاسخ‌گویی پیدا نشد.")
                subject = f"reply:{ticket.id}"
            else:
                subject = f"topic:{topic_match.group(1)}"
            if state is None:
                state = await db.get(
                    ShopCustomerChatState,
                    (self.context.bot_id, event.user_id),
                )
            if state is None:
                state = ShopCustomerChatState(
                    bot_id=self.context.bot_id,
                    platform_user_id=event.user_id,
                    store_id=self.context.store_id,
                    expires_at=datetime.now(UTC) + _TICKET_TTL,
                )
                db.add(state)
            if state.store_id != self.context.store_id:
                raise ValueError("Invalid chat State Store ownership.")
            state.action = "ticket_input"
            state.context_ref = subject
            state.expires_at = datetime.now(UTC) + _TICKET_TTL
            await db.commit()
            return BotReply(
                "توضیح درخواست خود را بنویسید (حداکثر ۴۰۰۰ کاراکتر).\n"
                "برای لغو /cancel را ارسال کنید.",
                ticket_actions(("لغو", "ux:support")),
            )

        if state is not None and state.action == "ticket_input":
            expiry = state.expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry <= datetime.now(UTC):
                state.action = "idle"
                state.context_ref = None
                await db.commit()
                return BotReply("مهلت ارسال پیام پایان یافت؛ دوباره درخواست بدهید.")
            try:
                message = validate_ticket_body(text)
            except ValueError:
                return BotReply("لطفاً متن قابل‌خواندن با حداکثر ۴۰۰۰ نویسه وارد کنید.")
            reference = state.context_ref or ""
            if reference.startswith("topic:"):
                topic = reference.removeprefix("topic:")
                if topic not in {"general", "order", "payment", "delivery", "refund"}:
                    return BotReply("نوع درخواست نامعتبر است.")
                ticket = ShopSupportTicket(
                    store_id=self.context.store_id,
                    customer_id=customer.id,
                    bot_id=self.context.bot_id,
                    origin_identity_id=identity.id,
                    topic=topic,
                )
                db.add(ticket)
                await db.flush()
            elif reference.startswith("reply:"):
                try:
                    ticket_id = int(reference.removeprefix("reply:"))
                except ValueError:
                    return BotReply("درخواست پشتیبانی معتبر نیست.")
                ticket = await customer_ticket(
                    db, self.context, customer_id=customer.id,
                    ticket_id=ticket_id,
                )
                if ticket is None or ticket.status == "closed":
                    return BotReply("درخواست پشتیبانی دیگر قابل پاسخ نیست.")
                ticket.status = "open"
                ticket.version += 1
            else:
                return BotReply("فرم درخواست پیدا نشد؛ دوباره شروع کنید.")
            db.add(ShopSupportMessage(
                store_id=self.context.store_id, ticket_id=ticket.id,
                sender_kind="customer", identity_id=identity.id,
                body=message,
            ))
            state.action = "idle"
            state.context_ref = None
            await db.commit()
            return BotReply(
                f"✅ درخواست پشتیبانی #{ticket.id} ثبت شد. "
                "پاسخ در بخش درخواست‌های من قابل مشاهده خواهد بود.",
                ticket_actions(
                    ("💬 مشاهده درخواست", f"ux:ticket:view:{ticket.id}"),
                    ("📨 درخواست‌های من", "ux:tickets"),
                ),
            )

        if action == "ux:tickets":
            rows = (await db.scalars(select(ShopSupportTicket).where(
                ShopSupportTicket.store_id == self.context.store_id,
                ShopSupportTicket.origin_identity_id.in_(
                    _verified_ticket_owners(self.context, customer.id),
                ),
            ).order_by(
                ShopSupportTicket.id.desc(),
            ).limit(20))).all()
            if not rows:
                return BotReply(
                    "هنوز درخواست پشتیبانی ثبت نکرده‌اید.",
                    ticket_actions(
                        ("✍️ درخواست جدید", "ux:ticket:new"),
                        ("🏠 منوی اصلی", "shop:home"),
                    ),
                )
            return BotReply(
                "📨 درخواست‌های من",
                ticket_actions(*(
                    (f"#{row.id} — {row.topic} — {row.status}",
                     f"ux:ticket:view:{row.id}")
                    for row in rows
                )) + ticket_actions(
                    ("درخواست جدید", "ux:ticket:new"),
                    ("بازگشت", "ux:support"),
                ),
            )

        match = _TICKET_ID.fullmatch(action)
        page_match = _TICKET_PAGE.fullmatch(action)
        if match or page_match:
            ticket_id = int((match or page_match).group(1))
            if ticket_id > _MAX_DATABASE_ID:
                return BotReply("شناسه درخواست پشتیبانی معتبر نیست.")
            ticket = await customer_ticket(
                db, self.context, customer_id=customer.id,
                ticket_id=ticket_id,
            )
            if ticket is None:
                return BotReply("درخواست متعلق به این حساب پیدا نشد.")
            query = select(ShopSupportMessage).where(
                ShopSupportMessage.ticket_id == ticket.id,
                ShopSupportMessage.store_id == self.context.store_id,
                ShopSupportMessage.sender_kind.in_(("customer", "staff")),
            )
            message_id = int(page_match.group(2)) if page_match else None
            part = int(page_match.group(3)) if page_match else 0
            if message_id is not None and message_id > _MAX_DATABASE_ID:
                return BotReply("شناسه پیام پشتیبانی معتبر نیست.")
            item = await db.scalar(
                query.where(ShopSupportMessage.id == message_id)
                if message_id is not None else
                query.order_by(ShopSupportMessage.id).limit(1)
            )
            header = f"#{ticket.id} — {ticket.topic}\nوضعیت: {ticket.status}"
            if item is None:
                return BotReply(
                    header + "\nپیام قابل‌نمایش پیدا نشد.",
                    ticket_actions(("بازگشت به درخواست", f"ux:ticket:view:{ticket.id}")),
                )
            pages = _message_pages(item.body)
            if part >= len(pages):
                return BotReply(
                    "این بخش از پیام پیدا نشد؛ درخواست را دوباره باز کنید.",
                    ticket_actions(("مشاهده درخواست", f"ux:ticket:view:{ticket.id}")),
                )
            navigation = []
            if part:
                previous_id, previous_part = item.id, part - 1
            else:
                previous = await db.scalar(query.where(
                    ShopSupportMessage.id < item.id,
                ).order_by(ShopSupportMessage.id.desc()).limit(1))
                previous_id = previous.id if previous else None
                previous_part = len(_message_pages(previous.body)) - 1 if previous else 0
            if previous_id is not None:
                navigation.append(InlineAction(
                    "قبلی", f"ux:ticket:page:{ticket.id}:{previous_id}:{previous_part}",
                ))
            if part + 1 < len(pages):
                following_id, following_part = item.id, part + 1
            else:
                following = await db.scalar(query.where(
                    ShopSupportMessage.id > item.id,
                ).order_by(ShopSupportMessage.id).limit(1))
                following_id = following.id if following else None
                following_part = 0
            if following_id is not None:
                navigation.append(InlineAction(
                    "بعدی", f"ux:ticket:page:{ticket.id}:{following_id}:{following_part}",
                ))
            author = "شما" if item.sender_kind == "customer" else "پشتیبانی"
            return BotReply(
                f"{header}\n{author} — بخش {part + 1} از {len(pages)}\n\n{pages[part]}",
                ((tuple(navigation),) if navigation else ()) + ticket_actions(
                    ("✉️ پاسخ جدید", f"ux:ticket:reply:{ticket.id}"),
                    ("📨 درخواست‌های من", "ux:tickets"),
                    ("🏠 منوی اصلی", "shop:home"),
                ),
            )
        return None


async def list_staff_tickets(
    db: AsyncSession, *, store_id: str, status: str | None = None,
) -> list[dict]:
    """Read the Store's bounded help desk queue with no cross-Store rows."""
    if status is not None and status not in {
        "open", "pending", "resolved", "closed",
    }:
        raise ValueError("Invalid ticket status.")
    query = select(ShopSupportTicket).where(
        ShopSupportTicket.store_id == store_id,
    )
    if status:
        query = query.where(ShopSupportTicket.status == status)
    rows = (await db.scalars(
        query.order_by(ShopSupportTicket.id.desc()).limit(100),
    )).all()
    return [{
        "id": row.id, "customer_id": row.customer_id,
        "bot_id": row.bot_id, "topic": row.topic,
        "status": row.status, "version": row.version,
        "created_at": row.created_at.isoformat(),
    } for row in rows]


async def staff_reply(
    db: AsyncSession, *, ticket_id: int, store_id: str,
    actor_id: int, message: str, expected_version: int,
    commit: bool = True,
) -> dict:
    """Append an audited staff response and mark the ticket awaiting customer."""
    body = validate_ticket_body(message)
    ticket = await db.scalar(select(ShopSupportTicket).where(
        ShopSupportTicket.id == ticket_id,
        ShopSupportTicket.store_id == store_id,
    ).with_for_update())
    if ticket is None:
        raise ValueError("Ticket not found in current Store.")
    if ticket.version != expected_version or ticket.status == "closed":
        raise ValueError("Ticket changed or closed.")
    db.add(ShopSupportMessage(
        ticket_id=ticket.id, store_id=store_id,
        sender_kind="staff", staff_id=actor_id, body=body,
    ))
    ticket.status = "pending"
    ticket.version += 1
    await db.flush()
    if commit:
        await db.commit()
    return {
        "id": ticket.id, "version": ticket.version,
        "status": ticket.status, "bot_id": ticket.bot_id,
        "store_id": ticket.store_id,
        "customer_id": ticket.customer_id,
        "identity_id": ticket.origin_identity_id,
    }
