"""Exercise Runtime's provider boundary without any external API traffic."""

from contextlib import asynccontextmanager
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from channels.bale import BaleApiError, BaleTransport
from channels.contracts import Platform
from channels.telegram import TelegramTransport
from models.shop_multibot import DEFAULT_STORE_ID
from tests.schema_support import TEST_BOT_IDS, seed_customer
from models.shop_workflow_runtime import WorkflowUpload
from services.shop_bot_context import BotContext
from services.shop_runtime import adapters
from services.shop_runtime.contracts import RuntimeRejected
from tests.test_action_security import buyer as buyer, db as db


PNG = b"\x89PNG\r\n\x1a\n" + b"verified fixture" * 4


def context(platform="telegram"):
    """Represent an identity already authenticated by a receiver."""
    return BotContext(
        bot_id=TEST_BOT_IDS[platform],
        store_id=DEFAULT_STORE_ID,
        platform=Platform(platform),
        provider_bot_id=100,
        status="active",
        runtime_owner="registry",
        credential_version=1,
        registry_version=1,
    )


def message(**fields):
    """Build raw Bot API JSON names, never SDK aliases or Runtime values."""
    return {
        "update_id": 7,
        "message": {
            "from": {"id": 101, "is_bot": False},
            "chat": {"id": 101, "type": "private"},
            **fields,
        },
    }


@pytest.mark.parametrize("platform", ["telegram", "bale"])
def test_normalize_preserves_authoritative_sender_and_content(platform):
    """Both raw providers produce the same bounded neutral input."""
    event = adapters.normalize(context(platform), message(text="/wholesale"))
    assert event.kind == "command" and event.text == "/wholesale"
    assert event.update_id == "7" and event.platform == platform
    assert event.user_id == event.chat_id == 101
    assert adapters.normalize(context(platform), message(text="سلام")).kind == "text"


@pytest.mark.parametrize(
    "change",
    [
        {"update_id": None},
        {"update_id": True},
        {"update_id": -1},
        {"update_id": "7"},
        {"update_id": 2**64},
        {
            "message": {
                "from_user": {"id": 101},
                "chat": {"id": 101, "type": "private"},
                "text": "x",
            }
        },
        {
            "message": {
                "from": {"id": True},
                "chat": {"id": 101, "type": "private"},
                "text": "x",
            }
        },
        {
            "message": {
                "from": {"id": 102},
                "chat": {"id": 101, "type": "private"},
                "text": "x",
            }
        },
        {
            "message": {
                "from": {"id": 101},
                "chat": {"id": 101, "type": "group"},
                "text": "x",
            }
        },
    ],
)
def test_normalize_rejects_missing_or_spoofed_identity(change):
    """Untrusted aliases, booleans and mixed customer identity never enter Runs."""
    assert adapters.normalize(context(), message(text="hello") | change) is None


def test_normalize_rejects_financial_ambiguous_and_oversize_payloads():
    """Runtime cannot consume payment envelopes, two updates or truncated answers."""
    assert adapters.normalize(context(), message(text="x" * 4097)) is None
    assert (
        adapters.normalize(context(), message(text="x", successful_payment={})) is None
    )
    assert (
        adapters.normalize(context(), message(text="x") | {"pre_checkout_query": {}})
        is None
    )
    assert (
        adapters.normalize(context(), message(text="x") | {"callback_query": {}})
        is None
    )
    assert adapters.normalize(context(), message(text="x", document={})) is None


def test_normalize_contact_and_files_are_bounded_and_not_trusted_handles():
    """Only the sender's own contact and supported metadata survive normalization."""
    own = message(contact={"user_id": 101, "phone_number": "+989123456789"})
    event = adapters.normalize(context(), own)
    assert event.kind == "contact" and event.contact_owner == 101
    assert event.text == "+989123456789"
    assert (
        adapters.normalize(
            context(),
            message(contact={"user_id": 102, "phone_number": "+989123456789"}),
        )
        is None
    )
    event = adapters.normalize(
        context(),
        message(
            document={
                "file_id": "private_doc",
                "file_size": len(PNG),
                "mime_type": "image/png",
            }
        ),
    )
    assert (
        event.kind == "document"
        and event.text == ""
        and event.file.file_id == "private_doc"
    )
    for file_id, mime, size in [
        ("https://example.org/a.pdf", "application/pdf", 10),
        ("../../a.pdf", "application/pdf", 10),
        ("valid", "application/x-python", 10),
        ("valid", "image/png", 20_000_001),
        ("valid", "image/png", True),
    ]:
        assert (
            adapters.normalize(
                context(),
                message(
                    document={
                        "file_id": file_id,
                        "file_size": size,
                        "mime_type": mime,
                    }
                ),
            )
            is None
        )


def test_normalize_callback_owner_and_utf8_bytes():
    """Callbacks use their actual sender and never an embedded message sender."""
    payload = {
        "update_id": 8,
        "callback_query": {
            "id": "query-1",
            "from": {"id": 101},
            "data": "wf:opaque",
            "message": {"from": {"id": 999}, "chat": {"id": 101, "type": "private"}},
        },
    }
    assert adapters.normalize(context(), payload).callback == "wf:opaque"
    payload["callback_query"]["from"]["id"] = 102
    assert adapters.normalize(context(), payload) is None
    payload["callback_query"]["from"]["id"] = 101
    payload["callback_query"]["data"] = "م" * 33
    assert adapters.normalize(context(), payload) is None


class DownloadBot:
    """Supply a provider-authenticated file through a bounded destination."""

    def __init__(self, content=PNG, path="photos/private.png"):
        """Keep bytes and the provider path under explicit test control."""
        self.content, self.path, self.calls = content, path, []

    async def get_file(self, file_id):
        """Return scoped provider metadata rather than trusting update paths."""
        self.calls.append(("get_file", file_id))
        return SimpleNamespace(
            file_id=file_id, file_size=len(self.content), file_path=self.path
        )

    async def download_file(self, file_path, destination, **kwargs):
        """Write to the destination used by Aiogram, with no real network."""
        self.calls.append(("download", file_path))
        destination.write(self.content)
        return destination


@pytest.mark.asyncio
async def test_verify_upload_reads_bytes_persists_private_handle_without_commit(buyer):
    """A verified upload is owned, typed and transactional; provider IDs stay private."""
    db, principal = buyer
    event = adapters.normalize(
        principal.bot,
        message(
            document={
                "file_id": "private_png",
                "file_size": len(PNG),
                "mime_type": "image/png",
            }
        ),
    )
    bot = DownloadBot()
    handle = await adapters.verify_upload(
        db, principal.bot, event, principal, client=bot
    )
    upload = await db.get(WorkflowUpload, handle)
    assert upload.verified and upload.customer_id == principal.customer_id
    assert upload.bot_id == principal.bot_id and upload.store_id == principal.store_id
    assert upload.user_id == 101 and upload.mime_type == "image/png"
    assert upload.size == len(PNG) and len(upload.sha256) == 64
    assert bot.calls == [
        ("get_file", "private_png"),
        ("download", "photos/private.png"),
    ]
    await db.rollback()
    assert await db.scalar(select(func.count()).select_from(WorkflowUpload)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content,path,mime",
    [
        (b"print('untrusted')", "documents/file.pdf", "application/pdf"),
        (PNG, "https://attacker.invalid/private", "image/png"),
        (PNG, "../secret", "image/png"),
        (PNG, "documents/file.pdf", "application/pdf"),
    ],
)
async def test_verify_upload_rejects_signatures_paths_and_mime_lies(
    buyer, content, path, mime
):
    """Metadata cannot turn arbitrary bytes, URLs or local paths into evidence."""
    db, principal = buyer
    event = adapters.normalize(
        principal.bot,
        message(
            document={
                "file_id": "private_file",
                "file_size": len(content),
                "mime_type": mime,
            }
        ),
    )
    with pytest.raises(RuntimeRejected):
        await adapters.verify_upload(
            db, principal.bot, event, principal, client=DownloadBot(content, path)
        )
    assert await db.scalar(select(func.count()).select_from(WorkflowUpload)) == 0


@pytest.mark.asyncio
async def test_verify_upload_rejects_changed_owner_and_sanitizes_provider_exception(
    buyer,
):
    """Wrong customer scope fails before download; secrets never escape SDK failures."""
    db, principal = buyer
    event = adapters.normalize(
        principal.bot,
        message(
            photo=[
                {
                    "file_id": "private_photo",
                    "file_size": len(PNG),
                    "width": 5,
                    "height": 5,
                }
            ]
        ),
    )
    bot = DownloadBot()
    with pytest.raises(RuntimeRejected):
        await adapters.verify_upload(
            db,
            principal.bot,
            event,
            replace(principal, platform_user_id=102),
            client=bot,
        )
    assert not bot.calls
    bot.get_file = AsyncMock(side_effect=RuntimeError("https://provider/token-secret"))
    with pytest.raises(RuntimeRejected) as error:
        await adapters.verify_upload(db, principal.bot, event, principal, client=bot)
    assert "token-secret" not in str(error.value)


class SendingBot:
    """Return explicit receipts from a single physical provider operation."""

    def __init__(self):
        """Start an empty send history."""
        self.calls = []

    async def send_message(self, **kwargs):
        """Record one message operation with native markup."""
        self.calls.append(("sendMessage", kwargs))
        return SimpleNamespace(message_id=501)

    async def send_media_group(self, **kwargs):
        """Return one ID for every media item from one album operation."""
        self.calls.append(("sendMediaGroup", kwargs))
        return [SimpleNamespace(message_id=501), SimpleNamespace(message_id=502)]


class RuntimeResponse:
    """Supply both response envelopes and streamed file bytes to fake HTTP."""

    def __init__(self, data=None, *, content=b"", status=200):
        """Bind one explicit fake response without opening a network session."""
        self.data, self.status, self.content_length = data, status, len(content)
        self.bytes = content
        self.content = self

    async def __aenter__(self):
        """Enter the same response interface as aiohttp."""
        return self

    async def __aexit__(self, *_):
        """Leave the fake response without hiding test failures."""
        return False

    async def json(self, **_):
        """Return the provider envelope selected by the fixture."""
        return self.data

    async def iter_chunked(self, maximum):
        """Stream bounded chunks so download size checks see actual bytes."""
        for offset in range(0, len(self.bytes), maximum):
            yield self.bytes[offset : offset + maximum]


class RuntimeHttp:
    """Record a finite set of HTTP operations and their response bodies."""

    def __init__(self, *responses):
        """Create only the responses explicitly required by the scenario."""
        self.responses, self.calls = iter(responses), []

    def post(self, url, **kwargs):
        """Capture one Bot API send/download-metadata operation."""
        self.calls.append(("POST", url, kwargs))
        return next(self.responses)

    def get(self, url, **kwargs):
        """Capture one authenticated streaming download operation."""
        self.calls.append(("GET", url, kwargs))
        return next(self.responses)


@pytest.mark.asyncio
async def test_telegram_runtime_text_and_contact_use_one_send_with_receipt():
    """Plain text does not inherit HTML; contact sharing is a real reply button."""
    bot = SendingBot()
    prepared = adapters.RuntimeMessage(
        kind="text",
        text="<literal>",
        reply_markup={
            "keyboard": [[{"text": "شماره تماس", "request_contact": True}]],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        },
    )
    assert await TelegramTransport(bot).send_runtime(101, prepared) == ["501"]
    assert len(bot.calls) == 1 and bot.calls[0][1]["parse_mode"] is None
    assert bot.calls[0][1]["reply_markup"].keyboard[0][0].request_contact


@pytest.mark.asyncio
async def test_reply_buttons_are_literal_unique_text_and_navigation_commands():
    """Reply keyboards send visible labels/commands instead of opaque callbacks."""
    payload = {
        "kind": "text",
        "text": "انتخاب کنید",
        "keyboard": "reply",
        "buttons": [
            {"label": "انتخاب الف", "callback_data": "wf:first"},
            {
                "label": "منوی اصلی",
                "callback_data": "wf:menu",
                "command": "/menu",
                "row": 1,
            },
        ],
    }
    markup = adapters._markup(payload)
    bot = SendingBot()
    await TelegramTransport(bot).send_runtime(
        101,
        adapters.RuntimeMessage(kind="text", text=payload["text"], reply_markup=markup),
    )
    keyboard = bot.calls[0][1]["reply_markup"].keyboard
    assert keyboard[0][0].text == "انتخاب الف" and keyboard[1][0].text == "/menu"
    assert not hasattr(keyboard[0][0], "callback_data")
    with pytest.raises(RuntimeRejected, match="runtime_reply_button_ambiguous"):
        adapters._markup(
            payload | {"buttons": [payload["buttons"][0], payload["buttons"][0]]}
        )
    with pytest.raises(RuntimeRejected, match="runtime_reply_button_unsupported"):
        adapters._markup(
            payload | {"buttons": [{"label": "وب‌سایت", "url": "https://example.org"}]}
        )


def test_contact_reply_keyboard_preserves_only_available_literal_commands():
    """Phone input can expose Back/Skip/Cancel without inventing inline contact APIs."""
    markup = adapters._markup(
        {
            "request_contact": True,
            "buttons": [
                {"label": "بازگشت", "callback_data": "wf:back", "command": "/back"},
                {"label": "رد کردن", "callback_data": "wf:skip", "command": "/skip"},
                {"label": "لغو", "callback_data": "wf:cancel", "command": "/cancel"},
            ],
        }
    )
    assert markup["keyboard"][0][0]["request_contact"] is True
    assert [row[0]["text"] for row in markup["keyboard"][1:]] == [
        "/back",
        "/skip",
        "/cancel",
    ]


@pytest.mark.asyncio
async def test_telegram_runtime_album_is_one_send_not_album_plus_text(tmp_path):
    """An outbox intent never creates an unrecorded extra text operation."""
    path = tmp_path / "photo.png"
    path.write_bytes(PNG)
    media = adapters.RuntimeMedia(path=path, kind="photo", mime_type="image/png")
    prepared = adapters.RuntimeMessage(
        kind="media_group", text="caption", media=(media, media)
    )
    bot = SendingBot()
    assert await TelegramTransport(bot).send_runtime(101, prepared) == ["501", "502"]
    assert [call[0] for call in bot.calls] == ["sendMediaGroup"]
    assert bot.calls[0][1]["media"][0].caption == "caption"
    assert bot.calls[0][1]["media"][0].parse_mode is None


@pytest.mark.asyncio
async def test_bale_runtime_album_uses_one_multipart_request_and_all_receipts(tmp_path):
    """Bale albums include private originals and their caption in one request."""
    path = tmp_path / "photo.png"
    path.write_bytes(PNG)
    media = adapters.RuntimeMedia(path=path, kind="photo", mime_type="image/png")
    prepared = adapters.RuntimeMessage(
        kind="media_group", text="caption", media=(media, media)
    )
    http = RuntimeHttp(
        RuntimeResponse(
            {"ok": True, "result": [{"message_id": 41}, {"message_id": 42}]}
        )
    )
    result = await BaleTransport("fake-secret", http).send_runtime(101, prepared)
    assert result == ["41", "42"] and len(http.calls) == 1
    _, url, kwargs = http.calls[0]
    assert url.endswith("/sendMediaGroup") and kwargs["allow_redirects"] is False
    fields = {headers["name"]: value for headers, _, value in kwargs["data"]._fields}
    assert fields["chat_id"] == "101"
    group = json.loads(fields["media"])
    assert (
        group[0]["media"] == "attach://runtime_0" and group[0]["caption"] == "caption"
    )
    assert "caption" not in group[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [None, {}, {"message_id": True}, {"message_id": 0}])
async def test_bale_runtime_missing_receipt_stays_uncertain(result):
    """A successful envelope without a valid message ID cannot become sent."""
    http = RuntimeHttp(RuntimeResponse({"ok": True, "result": result}))
    with pytest.raises(RuntimeError, match="receipt_invalid"):
        await BaleTransport("fake-secret", http).send_runtime(
            101, adapters.RuntimeMessage(kind="text", text="x")
        )
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_bale_runtime_rate_limit_is_known_rejection_but_timeout_is_uncertain():
    """Only explicit API rejection can trigger the outbox's bounded retry path."""
    from services.shop_runtime.contracts import DeliveryRejected

    http = RuntimeHttp(RuntimeResponse({"ok": False, "error_code": 429}, status=429))
    with pytest.raises(DeliveryRejected) as error:
        await BaleTransport("fake-secret", http).send_runtime(
            101, adapters.RuntimeMessage(kind="text", text="x")
        )
    assert error.value.retryable and "fake-secret" not in str(error.value)
    transport = BaleTransport(
        "fake-secret",
        SimpleNamespace(
            post=lambda *a, **kw: (_ for _ in ()).throw(TimeoutError("fake-secret"))
        ),
    )
    with pytest.raises(RuntimeError, match="runtime_delivery_uncertain") as error:
        await transport.send_runtime(
            101, adapters.RuntimeMessage(kind="text", text="x")
        )
    assert not isinstance(error.value, DeliveryRejected) and "fake-secret" not in str(
        error.value
    )


@pytest.mark.asyncio
async def test_bale_download_uses_fixed_bot_route_and_actual_byte_budget():
    """GetFile metadata cannot redirect downloads or bypass streamed limits."""
    remote = {
        "file_id": "private_file",
        "file_path": "documents/private.png",
        "file_size": len(PNG),
    }
    http = RuntimeHttp(
        RuntimeResponse({"ok": True, "result": remote}), RuntimeResponse(content=PNG)
    )
    assert (
        await BaleTransport("fake-secret", http).download_runtime(
            "private_file", max_bytes=len(PNG)
        )
        == PNG
    )
    assert (
        http.calls[-1][1]
        == "https://tapi.bale.ai/file/botfake-secret/documents/private.png"
    )
    assert http.calls[-1][2]["allow_redirects"] is False
    remote["file_path"] = "https://attacker.invalid/file"
    bad = RuntimeHttp(RuntimeResponse({"ok": True, "result": remote}))
    with pytest.raises(BaleApiError):
        await BaleTransport("fake-secret", bad).download_runtime(
            "private_file", max_bytes=len(PNG)
        )
    assert len(bad.calls) == 1


@pytest.mark.asyncio
async def test_verify_upload_uses_bale_client_and_identical_customer_scope(buyer):
    """Bale evidence gets its own Bot/customer binding, despite equal numeric IDs."""
    from models.shop_content import ShopIdentity
    from services.shop_actions.context import customer_principal
    from services.shop_bot_context import resolve_bot_context

    db, principal = buyer
    identity = seed_customer(db.session, "bale", 101)
    identity.customer_id = principal.customer_id
    await db.commit()
    bot = await resolve_bot_context(
        db, authenticated_bot_id=identity.bot_id, authenticated_platform=Platform.BALE
    )
    scoped = await customer_principal(db, verified_bot=bot, platform_user_id=101)
    event = adapters.normalize(
        bot,
        message(
            document={
                "file_id": "bale_png",
                "file_size": len(PNG),
                "mime_type": "image/png",
            }
        ),
    )
    client = SimpleNamespace(
        bot_id=bot.bot_id, download_runtime=AsyncMock(return_value=PNG)
    )
    handle = await adapters.verify_upload(db, bot, event, scoped, client=client)
    assert (await db.get(WorkflowUpload, handle)).bot_id == TEST_BOT_IDS["bale"]
    client.download_runtime.assert_awaited_once_with("bale_png", max_bytes=len(PNG))


@pytest.mark.asyncio
async def test_telegram_stream_rejects_actual_bytes_larger_than_declared(buyer):
    """A dishonest declared or HTTP size cannot grow evidence past its budget."""
    db, principal = buyer
    event = adapters.normalize(
        principal.bot,
        message(document={"file_id": "png", "file_size": 8, "mime_type": "image/png"}),
    )
    bot = DownloadBot(PNG)
    bot.get_file = AsyncMock(
        return_value=SimpleNamespace(file_path="photos/private.png", file_size=8)
    )
    with pytest.raises(RuntimeRejected):
        await adapters.verify_upload(db, principal.bot, event, principal, client=bot)
    assert await db.scalar(select(func.count()).select_from(WorkflowUpload)) == 0


@pytest.mark.asyncio
async def test_deliver_resolves_provider_server_side_and_rejects_oversize_callback(
    monkeypatch,
):
    """Render validation precedes credentials and provider calls."""
    from services.shop_runtime import sessions

    class Db:
        """Expose only internal credential lookup to this delivery test."""

        async def run_sync(self, callback):
            """Resolve the test credential without loading environment secrets."""
            return "server-side-secret"

    @asynccontextmanager
    async def database():
        """Provide an isolated dependency to the adapter."""
        yield Db()

    bot, used = SendingBot(), []

    @asynccontextmanager
    async def provider(platform, token, **kwargs):
        """Record server-selected provider scope without making HTTP requests."""
        used.append((platform, token, kwargs))
        yield bot

    monkeypatch.setattr(adapters, "session_maker", database)
    monkeypatch.setattr(adapters, "provider_client", provider)
    monkeypatch.setattr(sessions, "enabled", AsyncMock(return_value=True))
    assert await adapters.deliver(
        context(), 101, {"kind": "text", "text": "plain", "buttons": []}
    ) == ["501"]
    assert used == [("telegram", "server-side-secret", {"bot_id": context().bot_id})]
    with pytest.raises(Exception):
        await adapters.deliver(
            context(),
            101,
            {
                "kind": "text",
                "text": "x",
                "buttons": [{"label": "x", "callback_data": "م" * 33}],
            },
        )
    assert len(bot.calls) == len(used) == 1
