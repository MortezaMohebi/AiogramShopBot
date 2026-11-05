"""Accept Layer 3 against isolated PostgreSQL and the real signed admin HTTP API.

Run ``python -m scripts.workflow_runtime_e2e`` inside the API container from
``compose.workflow-runtime-qa.yml``, after ``beta_storefront_e2e.seed``. Only
provider I/O and explicit crash checkpoints are replaced. Customer identity,
SQL locks, immutable publications, authorization, Action Registry execution,
outbox rendering, and HTTP request signatures use production implementations.

The runner keeps additive synthetic rows. Its two JSON artifacts contain safe
identifiers and observed results only; customer answers, callback capabilities,
private file handles, provider tokens, and diagnostic session secrets stay out.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import socket
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from scripts.test_lab_safety import require_isolated_lab

# These checks deliberately precede every application or third-party import.
# Assertions are executable acceptance criteria, so optimized Python is unsafe.
require_isolated_lab()
if os.environ.get("SHOP_RUNTIME_QA") != "1" or not __debug__:
    raise RuntimeError("Use isolated Runtime QA mode with assertions enabled.")
if (
    os.environ.get("SHOP_BETA_QA") != "1"
    or os.environ.get("SHOP_WORKFLOW_RUNTIME_ENABLED") != "true"
    or os.environ.get("SHOP_WORKFLOW_RUNTIME_KILL_SWITCH", "false") != "false"
):
    raise RuntimeError("Use the named Workflow Runtime PostgreSQL QA stack.")

import httpx
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

import config
from channels.bale import BaleTransport
from channels.contracts import Platform
from db import engine, session_maker
from models.shop_action import ShopActionExecution
from models.shop_delivery import ShopInboundUpdate
from models.shop_multibot import ShopBot, ShopStore
from models.shop_wholesale import ShopWholesaleApplication
from models.shop_workflow_runtime import (
    PublishedWorkflow,
    RuntimeSlot,
    WorkflowActionJob,
    WorkflowCallback,
    WorkflowDeliveryAttempt,
    WorkflowEvent,
    WorkflowInbox,
    WorkflowOutbox,
    WorkflowRun,
    WorkflowUpload,
    WorkflowWait,
)
from scripts.beta_receiver_admin_e2e import SignedAdmin
from scripts.beta_storefront_e2e import MANIFEST, FakeTelegram
from scripts.codespace_dashboard_probe import (
    diagnostic_identity,
    revoke_diagnostic_session,
)
from services import shop_admin_security as security
from services import shop_bot_secrets, shop_multibot_client
from services import shop_multibot_supervisor as supervisor_module
from services.shop_bot_context import resolve_bot_context
from services.shop_identity import register_customer
from services.shop_runtime import adapters, ingress, sessions, workers

EVIDENCE = Path("/qa/workflow-runtime-evidence.json")
FIXTURE = Path("/qa/workflow-runtime-fixture.json")
RUNTIME = "/workflow-runtime"
PDF = b"%PDF-1.4\n% synthetic bounded QA evidence\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
CHECK_NAMES = (
    "isolated PostgreSQL and network boundary",
    "signed publication, exact retry, conflict and namespaced gates",
    "Telegram complete Wholesale, typed input, verified PDF and one receipt",
    "Bale complete Wholesale, typed input, verified PDF and one receipt",
    "callback ownership, forgery, expiry and stale replay",
    "durable Inbox commit crash and competing restart workers",
    "durable Inbox ordering while Action is pending",
    "Layer 2 commit crash reconciliation preserves one business effect",
    "concurrent outbox workers preserve per-Run order",
    "definite rejection retries are bounded",
    "ambiguous provider response is quarantined without resend",
    "process crash after send is quarantined without resend",
    "competing timeout workers and timeout versus input",
    "Back, optional document, cancellation and restart",
    "immutable snapshot, version pinning and rollback",
    "emergency gates preserve accepted ownership and legacy handoff",
    "receiver Runtime precedes legacy receipts and old claims stay quarantined",
    "legacy start, catalog, cart, checkout, orders and payment bypass",
    "signed Store isolation, private metadata and audited recovery",
    "commerce, stock and payment state remain unchanged",
)


class SimulatedCrash(BaseException):
    """Interrupt a real commit boundary without ordinary exception recovery."""


def require(condition: bool, code: str) -> None:
    """Raise a stable non-private assertion message for evidence and logs."""
    if not condition:
        raise AssertionError("qa_" + code)


@dataclass
class NetworkFence:
    """Deny every socket destination except the isolated DB/cache and loopback."""

    denied: int = 0
    addresses: set[str] = field(default_factory=lambda: {"127.0.0.1", "::1"})

    @contextmanager
    def install(self):
        """Resolve only named compose services, then guard DNS and TCP connects."""
        original_dns = socket.getaddrinfo
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        for name in ("postgres", "redis"):
            for result in original_dns(name, None, type=socket.SOCK_STREAM):
                self.addresses.add(result[4][0])

        def permitted(host):
            """Allow explicit local names or their captured private addresses."""
            if isinstance(host, bytes):
                host = host.decode("ascii", errors="strict")
            return (
                host in {"postgres", "redis", "localhost"}
                or str(host) in self.addresses
            )

        def dns(host, *args, **kwargs):
            """Stop provider DNS before an HTTP library can construct a socket."""
            if not permitted(host):
                self.denied += 1
                raise RuntimeError("qa_live_network_forbidden")
            return original_dns(host, *args, **kwargs)

        def validate(address):
            """Validate IP tuples while leaving local Unix sockets available."""
            if isinstance(address, tuple) and not permitted(address[0]):
                self.denied += 1
                raise RuntimeError("qa_live_network_forbidden")

        def connect(connection, address):
            """Guard regular and asyncio TCP connections at the socket boundary."""
            validate(address)
            return original_connect(connection, address)

        def connect_ex(connection, address):
            """Apply the same rule to nonblocking third-party socket clients."""
            validate(address)
            return original_connect_ex(connection, address)

        with (
            patch.object(socket, "getaddrinfo", dns),
            patch.object(socket.socket, "connect", connect),
            patch.object(socket.socket, "connect_ex", connect_ex),
        ):
            yield self


class RuntimeTelegram(FakeTelegram):
    """Double only native Telegram sends and authenticated bounded downloads."""

    def __init__(self, bot_id: str, token: str, provider_id: int | None):
        """Keep the synthetic provider's allowlist and one-shot failure mode."""
        super().__init__()
        self.token = token
        self.bot_id = bot_id
        self.id = provider_id
        self.files: dict[str, bytes] = {}
        self.downloads: list[str] = []
        self.mode = "normal"

    async def send_message(self, *args, **kwargs):
        """Return positive receipts, or inject a precisely classified send failure."""
        if args:
            kwargs["chat_id"] = args[0]
        mode, self.mode = self.mode, "normal"
        if mode == "retry":
            raise TelegramRetryAfter(
                method=SendMessage(chat_id=kwargs["chat_id"], text="QA"),
                message="Synthetic rate limit",
                retry_after=1,
            )
        message = await super().send_message(**kwargs)
        if mode == "unknown":
            raise TimeoutError("Synthetic accepted request with missing response")
        if mode == "crash":
            raise SimulatedCrash()
        return message

    async def get_file(self, file_id):
        """Return server-side metadata only for a fixture-owned opaque handle."""
        require(file_id in self.files, "unexpected_telegram_download")
        return SimpleNamespace(
            file_id=file_id,
            file_size=len(self.files[file_id]),
            file_path="documents/" + file_id,
        )

    async def download_file(self, file_path, destination, **kwargs):
        """Write actual bytes through the production adapter's bounded buffer."""
        file_id = file_path.removeprefix("documents/")
        require(file_id in self.files, "unexpected_telegram_file_path")
        require(kwargs.get("timeout") == 30, "telegram_download_timeout")
        self.downloads.append(file_id)
        destination.write(self.files[file_id])
        return destination


class FakeHTTPResponse:
    """Implement aiohttp response and streaming protocols without a connection."""

    status = 200

    def __init__(self, *, result=None, content=None, rejected=False):
        """Retain one Bot API envelope or a bounded byte stream."""
        self.result, self.raw, self.rejected = result, content, rejected
        self.content_length = len(content) if content is not None else None
        self.content = self

    async def __aenter__(self):
        """Enter the same response protocol used by real Bale HTTP calls."""
        return self

    async def __aexit__(self, *_args):
        """Release no external resource and propagate injected failures."""
        return False

    async def json(self, **_kwargs):
        """Make the native Bale parser verify the official envelope itself."""
        if self.rejected:
            return {"ok": False, "error_code": 429}
        return {"ok": True, "result": self.result}

    async def iter_chunked(self, maximum):
        """Yield real evidence bytes in bounded chunks through native download code."""
        for offset in range(0, len(self.raw), min(maximum, 17)):
            yield self.raw[offset : offset + min(maximum, 17)]


class RuntimeBaleHTTP:
    """Fake only Bale's native HTTP boundary; retain real BaleTransport parsing."""

    def __init__(self, token: str):
        """Allocate fixture-local sends, acknowledgements and private evidence."""
        self.token = token
        self.messages: list[dict] = []
        self.acknowledged: list[str] = []
        self.precheckout: list[dict] = []
        self.files: dict[str, bytes] = {}
        self.downloads: list[str] = []
        self.mode = "normal"

    def post(self, url, *, json=None, **kwargs):
        """Allow only methods reached by this runner's synthetic bot."""
        require(
            url.startswith(BaleTransport.BASE_URL + "/bot" + self.token + "/"),
            "unexpected_bale_origin",
        )
        method = url.rsplit("/", 1)[-1]
        body = json or {}
        if method == "getFile":
            file_id = body.get("file_id")
            require(file_id in self.files, "unexpected_bale_download")
            return FakeHTTPResponse(
                result={
                    "file_id": file_id,
                    "file_size": len(self.files[file_id]),
                    "file_path": "documents/" + file_id,
                }
            )
        if method == "answerCallbackQuery":
            self.acknowledged.append(body["callback_query_id"])
            return FakeHTTPResponse(result=True)
        if method == "answerPreCheckoutQuery":
            self.precheckout.append(body)
            return FakeHTTPResponse(result=True)
        require(method == "sendMessage", "unexpected_bale_method")
        mode, self.mode = self.mode, "normal"
        if mode == "retry":
            return FakeHTTPResponse(rejected=True)
        self.messages.append(body)
        if mode == "unknown":
            raise TimeoutError("Synthetic accepted request with missing response")
        if mode == "crash":
            raise SimulatedCrash()
        return FakeHTTPResponse(result={"message_id": len(self.messages) + 5000})

    def get(self, url, **kwargs):
        """Model fixed-origin no-redirect evidence downloads with real bytes."""
        prefix = BaleTransport.BASE_URL + "/file/bot" + self.token + "/documents/"
        require(url.startswith(prefix), "unexpected_bale_file_origin")
        require(kwargs.get("allow_redirects") is False, "bale_download_redirect")
        file_id = url.removeprefix(prefix)
        require(file_id in self.files, "unexpected_bale_file_path")
        self.downloads.append(file_id)
        return FakeHTTPResponse(content=self.files[file_id])


@dataclass
class Case:
    """Keep synthetic customer state in memory, outside evidence artifacts."""

    platform: str
    bot_id: str
    user_id: int
    run_id: str = ""
    confirmation: str = ""
    values: dict = field(default_factory=dict)


class Harness:
    """Coordinate executable acceptance scenarios using independent DB sessions."""

    def __init__(self, fixture: dict, api: SignedAdmin, evidence: dict):
        """Keep one revocable signed identity and explicitly allowed fixture bots."""
        self.fixture, self.api, self.evidence = fixture, api, evidence
        self.store_id = fixture["stores"][0]
        self.contexts, self.native, self.tokens = {}, {}, {}
        self.cases: list[Case] = []
        self.record: dict = {}
        self.publication_id = ""
        self.new_publication_id = ""
        self.sequence = 4_000_000_000 + uuid4().int % 1_000_000_000
        self.private_values: set[str] = set()
        self.fence = NetworkFence()
        self.initial_commerce: dict = {}

    def next_id(self) -> int:
        """Allocate non-reused exact provider update identifiers in this process."""
        self.sequence += 1
        return self.sequence

    def contains_private(self, value) -> bool:
        """Find customer answers without confusing short numbers with timestamp fragments."""
        if isinstance(value, dict):
            return any(self.contains_private(item) for item in value.values())
        if isinstance(value, list):
            return any(self.contains_private(item) for item in value)
        rendered = str(value)
        return rendered in self.private_values or any(
            len(secret) >= 8 and secret in rendered for secret in self.private_values
        )

    async def check(self, name, operation):
        """Persist each observed result immediately and continue independent checks."""
        item = next(x for x in self.evidence["checks"] if x["check"] == name)
        try:
            async with asyncio.timeout(120):
                await operation()
            item["status"] = "PASS"
            print("PASS  " + name, flush=True)
            return True
        except Exception as error:  # noqa: BLE001 - preserve redacted FAIL evidence.
            # SQL/SDK/HTTP exceptions may contain answers or credential URLs.
            # Retain only a stable runner assertion or the exception class.
            reason = str(error) if isinstance(error, AssertionError) else ""
            if not reason.startswith(("qa_", "Signed ")) or len(reason) > 240:
                reason = type(error).__name__
            item.update(status="FAIL", reason=reason)
            print("FAIL  " + name + ": " + reason, flush=True)
            return False
        finally:
            self.write_evidence()

    def write_evidence(self):
        """Write only bounded safe metadata, never traceback or raw response data."""
        self.evidence["denied_network_calls"] = self.fence.denied
        EVIDENCE.write_text(json.dumps(self.evidence, ensure_ascii=False, indent=2))

    def write_fixture(self):
        """Expose browser-reusable identifiers without synthetic customer answers."""
        FIXTURE.write_text(
            json.dumps(
                {
                    "store_id": self.store_id,
                    "foreign_store_id": self.fixture["stores"][1],
                    "workflow_id": self.record.get("id"),
                    "revision": self.record.get("revision"),
                    "publication_id": self.publication_id or None,
                    "new_publication_id": self.new_publication_id or None,
                    "bots": {
                        key: self.fixture["bots"][key] for key in ("telegram", "bale")
                    },
                    "runs": [
                        {"run_id": case.run_id, "platform": case.platform}
                        for case in self.cases
                        if case.run_id
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    @contextmanager
    def providers(self):
        """Replace only provider factories/token lookups, with an exact bot allowlist."""

        def token_lookup(_db, *, bot_id):
            """Avoid reading stored credentials for every synthetic transport call."""
            require(bot_id in self.tokens, "non_fixture_token_lookup")
            return self.tokens[bot_id]

        async def fake_provider(platform, token, *, bot_id=None):
            """Yield an official transport's in-memory native client only."""
            require(bot_id in self.native, "non_fixture_provider_access")
            require(
                self.contexts[bot_id].platform.value == platform
                and hmac.compare_digest(token, self.tokens[bot_id]),
                "fake_provider_scope",
            )
            native = self.native[bot_id]
            if platform == "telegram":
                yield native
            else:
                yield BaleTransport(token, native, bot_id=bot_id)

        from contextlib import asynccontextmanager

        factory = asynccontextmanager(fake_provider)
        with ExitStack() as stack:
            for module in (shop_multibot_client, supervisor_module, ingress, adapters):
                stack.enter_context(patch.object(module, "provider_client", factory))
            for module in (shop_bot_secrets, supervisor_module, ingress, adapters):
                stack.enter_context(
                    patch.object(module, "resolve_active_token", token_lookup)
                )
            yield

    def raw(self, case, *, text_value=None, callback=None, contact=None, document=None):
        """Build real provider field names; callers may preserve an exact update ID."""
        actor = {"id": case.user_id, "is_bot": False, "first_name": "Runtime QA"}
        message = {
            "message_id": self.next_id(),
            "date": 1_790_000_000,
            "from": actor,
            "chat": {"id": case.user_id, "type": "private"},
        }
        update = {"update_id": self.next_id()}
        if callback is not None:
            self.private_values.add(callback)
            update["callback_query"] = {
                "id": uuid4().hex,
                "from": actor,
                "message": message,
                "data": callback,
            }
        else:
            if contact is not None:
                self.private_values.add(contact["phone_number"])
                message["contact"] = contact
            elif document is not None:
                self.private_values.add(document["file_id"])
                message["document"] = document
            else:
                message["text"] = text_value or "/start"
                if text_value and not text_value.startswith("/"):
                    self.private_values.add(text_value)
            update["message"] = message
        return update

    async def offer(self, case, payload):
        """Enter the real receiver coordinator with its real session_maker unchanged."""
        return await ingress.try_ingress(self.contexts[case.bot_id], payload)

    async def run(self, case):
        """Read a fresh committed snapshot, never the producing session's identity map."""
        async with session_maker() as db:
            return await db.get(WorkflowRun, case.run_id)

    async def outboxes(self, case):
        """Inspect exact per-Run sequencing from a separate PostgreSQL connection."""
        async with session_maker() as db:
            return (
                await db.scalars(
                    select(WorkflowOutbox)
                    .where(WorkflowOutbox.run_id == case.run_id)
                    .order_by(WorkflowOutbox.sequence)
                )
            ).all()

    async def drain(self, worker=workers.deliver_once):
        """Compete real worker sessions until a finite queue reaches its boundary."""
        for _ in range(100):
            worked = await asyncio.gather(worker(session_maker), worker(session_maker))
            if not any(worked):
                return
        raise AssertionError("qa_worker_batch_unbounded")

    async def new_case(self, platform="telegram", *, start=True, deep_link=False):
        """Enroll one real synthetic customer before racing Runtime transitions."""
        case = Case(
            platform=platform,
            bot_id=self.fixture["bots"][platform],
            user_id=8_000_000_000 + uuid4().int % 1_000_000_000,
        )
        self.cases.append(case)
        async with session_maker() as db:
            await register_customer(
                db,
                bot_id=case.bot_id,
                platform=Platform(platform),
                platform_user_id=case.user_id,
                first_name="Runtime QA",
            )
            await db.commit()
        if start:
            update = self.raw(
                case, text_value="/start wholesale" if deep_link else "/wholesale"
            )
            responses = await asyncio.gather(
                self.offer(case, update), self.offer(case, deepcopy(update))
            )
            case.run_id = next(
                (x.get("run_id") for x in responses if x.get("run_id")), ""
            )
            require(bool(case.run_id), "start_run_missing")
            async with session_maker() as db:
                count = await db.scalar(
                    select(func.count())
                    .select_from(WorkflowRun)
                    .where(
                        WorkflowRun.bot_id == case.bot_id,
                        WorkflowRun.user_id == case.user_id,
                    )
                )
                require(count == 1, "duplicate_start_created_two_runs")
                require(
                    await db.scalar(
                        select(func.count())
                        .select_from(WorkflowEvent)
                        .where(
                            WorkflowEvent.bot_id == case.bot_id,
                            WorkflowEvent.input_id == str(update["update_id"]),
                        )
                    )
                    == 1,
                    "duplicate_start_created_two_events",
                )
            require((await self.run(case)).node_id == "name", "start_not_at_name")
            await self.drain()
            self.write_fixture()
        return case

    async def input(self, case, expected_node, **content):
        """Verify one real normalized input advances to the intended boundary."""
        response = await self.offer(case, self.raw(case, **content))
        row = await self.run(case)
        require(response.get("handled") is True, "input_not_owned")
        require(
            row.status == "cancelled"
            if expected_node == "cancelled"
            else row.node_id == expected_node,
            "input_wrong_node_" + expected_node,
        )
        await self.drain()
        return row

    async def prepare_form(self, case, *, document=True, invalid=False):
        """Submit the mandatory full form through raw own-contact and file updates."""
        marker = uuid4().hex[:12]
        case.values = {
            "name": "QA_PRIVATE_NAME_" + marker,
            "phone": "+98910" + str(case.user_id)[-7:],
            "company": "QA_PRIVATE_COMPANY_" + marker,
            "city": "QA_PRIVATE_CITY_" + marker,
            "estimated_monthly_amount": 7_654_321,
        }
        self.private_values.update(str(v) for v in case.values.values())
        if invalid:
            await self.offer(case, self.raw(case, text_value="n" * 161))
            require((await self.run(case)).node_id == "name", "oversize_name_accepted")
            await self.drain()
        await self.input(case, "phone", text_value=case.values["name"])
        native = self.native[case.bot_id]
        phone_message = next(
            message
            for message in reversed(native.messages)
            if int(message["chat_id"]) == case.user_id
        )
        require(
            any(
                button.get("request_contact") is True
                for row in phone_message["reply_markup"]["keyboard"]
                for button in row
            ),
            "own_contact_control_missing",
        )
        if invalid:
            await self.offer(case, self.raw(case, text_value=case.values["phone"]))
            require((await self.run(case)).node_id == "phone", "typed_phone_accepted")
            await self.offer(
                case,
                self.raw(
                    case,
                    contact={
                        "user_id": case.user_id + 1,
                        "phone_number": case.values["phone"],
                        "first_name": "Other QA",
                    },
                ),
            )
            require(
                (await self.run(case)).node_id == "phone", "foreign_contact_accepted"
            )
            await self.drain()
        await self.input(
            case,
            "company",
            contact={
                "user_id": case.user_id,
                "phone_number": case.values["phone"],
                "first_name": "Runtime QA",
            },
        )
        await self.input(case, "city", text_value=case.values["company"])
        await self.input(
            case, "estimated_monthly_amount", text_value=case.values["city"]
        )
        if invalid:
            await self.offer(case, self.raw(case, text_value="12.5"))
            require(
                (await self.run(case)).node_id == "estimated_monthly_amount",
                "fractional_integer_accepted",
            )
            await self.drain()
        await self.input(
            case,
            "document",
            text_value=str(case.values["estimated_monthly_amount"]),
        )
        if document:
            file_id = "qa_pdf_" + uuid4().hex
            native.files[file_id] = PDF
            self.private_values.add(file_id)
            if invalid:
                bad_id = "qa_invalid_" + uuid4().hex
                native.files[bad_id] = b"plain text falsely labeled as PDF"
                await self.offer(
                    case,
                    self.raw(
                        case,
                        document={
                            "file_id": bad_id,
                            "file_size": len(native.files[bad_id]),
                            "mime_type": "application/pdf",
                        },
                    ),
                )
                require(
                    (await self.run(case)).node_id == "document", "false_pdf_accepted"
                )
                await self.drain()
            await self.input(
                case,
                "review",
                document={
                    "file_id": file_id,
                    "file_size": len(PDF),
                    "mime_type": "application/pdf",
                },
            )
            row = await self.run(case)
            async with session_maker() as db:
                upload = await db.get(WorkflowUpload, row.values["document"])
                require(
                    upload is not None
                    and upload.verified
                    and upload.store_id == self.store_id
                    and upload.bot_id == case.bot_id
                    and upload.customer_id == row.customer_id
                    and upload.user_id == case.user_id
                    and upload.size == len(PDF)
                    and upload.mime_type == "application/pdf"
                    and upload.sha256 == hashlib.sha256(PDF).hexdigest(),
                    "verified_upload_scope_or_bytes",
                )
            require(file_id in native.downloads, "native_download_not_used")
        else:
            await self.input(case, "review", text_value="/skip")
        row = await self.run(case)
        for name, value in case.values.items():
            require(row.values.get(name) == value, "typed_value_" + name)
        require(
            type(row.values["estimated_monthly_amount"]) is int,
            "amount_type_not_integer",
        )
        outbox = (await self.outboxes(case))[-1]
        async with session_maker() as db:
            for button in outbox.payload["buttons"]:
                token = button["callback_data"]
                callback = await db.scalar(
                    select(WorkflowCallback).where(
                        WorkflowCallback.token_hash == sessions.token_hash(token)
                    )
                )
                if callback.value == "confirm":
                    case.confirmation = token
        require(bool(case.confirmation), "confirmation_capability_missing")
        require(
            len(case.confirmation.encode()) <= 64
            and case.confirmation.startswith("wf:"),
            "callback_not_short_opaque_capability",
        )

    async def confirm(self, case):
        """Race duplicate raw confirmation updates without mocking the Action boundary."""
        payload = self.raw(case, callback=case.confirmation)
        results = await asyncio.gather(
            self.offer(case, payload), self.offer(case, deepcopy(payload))
        )
        require(all(x.get("handled") for x in results), "confirmation_not_owned")
        async with session_maker() as db:
            jobs = (
                await db.scalars(
                    select(WorkflowActionJob).where(
                        WorkflowActionJob.run_id == case.run_id
                    )
                )
            ).all()
            require(len(jobs) == 1, "duplicate_confirmation_created_two_jobs")
            require(
                jobs[0].action_key == "wholesale.create_application"
                and jobs[0].action_version == "1.0.0",
                "wrong_action_contract",
            )
        require((await self.run(case)).status == "waiting_action", "action_not_pending")

    async def completed(self, case):
        """Assert the committed domain row, exact receipt, typed output and messages."""
        row = await self.run(case)
        require(
            row.status == "completed" and row.node_id == "done", "run_not_completed"
        )
        async with session_maker() as db:
            applications = (
                await db.scalars(
                    select(ShopWholesaleApplication).where(
                        ShopWholesaleApplication.bot_id == case.bot_id,
                        ShopWholesaleApplication.platform_user_id == case.user_id,
                    )
                )
            ).all()
            jobs = (
                await db.scalars(
                    select(WorkflowActionJob).where(
                        WorkflowActionJob.run_id == case.run_id
                    )
                )
            ).all()
            receipts = (
                await db.scalars(
                    select(ShopActionExecution).where(
                        ShopActionExecution.workflow_run_id == case.run_id
                    )
                )
            ).all()
            require(
                len(applications) == len(jobs) == len(receipts) == 1,
                "duplicate_business_effect",
            )
            application, job, receipt = applications[0], jobs[0], receipts[0]
            require(
                application.store_id == self.store_id
                and application.bot_id == case.bot_id
                and application.customer_id == row.customer_id
                and application.origin_identity_id == row.identity_id
                and application.platform == case.platform,
                "application_owner_mismatch",
            )
            for name, value in case.values.items():
                require(
                    getattr(application, name) == value, "application_value_" + name
                )
            require(
                application.document_handle == row.values.get("document"),
                "application_document_mismatch",
            )
            require(
                receipt.id == job.invocation_id == job.receipt_id
                and job.status == receipt.status == "succeeded"
                and receipt.correlation_id == row.correlation_id,
                "action_receipt_not_reconciled",
            )
            require(
                row.values.get("application_id") == application.id,
                "action_output_not_mapped",
            )
            require(
                not self.contains_private(json.loads(receipt.result_json)),
                "receipt_contains_private_values",
            )
        await self.drain()
        outboxes = await self.outboxes(case)
        require(
            all(x.status == "sent" for x in outboxes), "completed_delivery_not_sent"
        )
        require(
            all(
                x.message_ids and all(int(i) > 0 for i in x.message_ids)
                for x in outboxes
            ),
            "provider_receipt_not_positive",
        )
        self.write_fixture()

    async def bootstrap(self):
        """Verify the exact lab DB/user, seeded ownership and independent sessions."""
        async with session_maker() as db:
            require(
                await db.scalar(text("SELECT current_database()")) == "shop_codespace"
                and await db.scalar(text("SELECT current_user")) == "shop_codespace"
                and db.bind.dialect.name == "postgresql",
                "wrong_database_identity",
            )
            for store_id in self.fixture["stores"]:
                store = await db.get(ShopStore, store_id)
                require(
                    store is not None and store.state == "active",
                    "fixture_store_unavailable",
                )
            for key in ("telegram", "bale", "foreign"):
                bot_id = self.fixture["bots"][key]
                bot = await db.get(ShopBot, bot_id)
                require(
                    bot is not None
                    and bot.store_id == self.fixture["stores"][int(key == "foreign")],
                    "fixture_bot_store_mismatch",
                )
                context = await resolve_bot_context(
                    db,
                    authenticated_bot_id=bot_id,
                    authenticated_platform=Platform(bot.platform),
                )
                self.contexts[bot_id] = context
                token = "990000:" + uuid4().hex + uuid4().hex
                self.tokens[bot_id] = token
                self.native[bot_id] = (
                    RuntimeTelegram(bot_id, token, bot.provider_bot_id)
                    if bot.platform == "telegram"
                    else RuntimeBaleHTTP(token)
                )
        async with session_maker() as first, session_maker() as second:
            a, b = await asyncio.gather(
                first.scalar(text("SELECT pg_backend_pid()")),
                second.scalar(text("SELECT pg_backend_pid()")),
            )
            require(a != b, "workers_do_not_have_independent_connections")
        require(config.SHOP_WORKFLOW_RUNTIME_ENABLED, "global_runtime_disabled")
        require(not config.MULTIBOT_V2_RUNTIME_ENABLED, "live_receiver_enabled")
        self.initial_commerce = await self.commerce_fingerprint()

    def bindings(self):
        """Assign only declared safe entry points on the two Store A fixture bots."""
        return [
            {
                "bot_id": self.fixture["bots"][platform],
                "kind": kind,
                "key": "wholesale",
                "node_id": "start",
            }
            for platform in ("telegram", "bale")
            for kind in ("command", "start")
        ]

    async def set_gate(self, *, bot_id=None, enabled=True, killed=False):
        """Use the signed manager API and its real optimistic version, never raw inserts."""
        overview = await self.api.call("GET", RUNTIME)
        key = sessions.gate_key(self.store_id, bot_id)
        current = next((x for x in overview["gates"] if x["scope_key"] == key), None)
        payload = {
            "operation_id": str(uuid4()),
            "bot_id": bot_id,
            "expected_version": current["version"] if current else 0,
            "enabled": enabled,
            "killed": killed,
        }
        result = await self.api.call("POST", RUNTIME + "/gates", payload=payload)
        require(
            result["enabled"] == enabled and result["killed"] == killed,
            "gate_write_failed",
        )
        replay = await self.api.call("POST", RUNTIME + "/gates", payload=payload)
        require(replay["replayed"], "gate_retry_not_idempotent")

    async def publish(self, revision):
        """Review and approve the exact saved definition through signed HTTP."""
        payload = {
            "workflow_id": self.record["id"],
            "revision": revision,
            "bindings": self.bindings(),
        }
        preview = await self.api.call(
            "POST", RUNTIME + "/publications/preview", payload=payload
        )
        require(preview["ready"], "publication_not_ready")
        require(
            any(
                x["key"] == "wholesale.create_application" and x["version"] == "1.0.0"
                for x in preview["dependencies"]
            ),
            "publication_missing_action_dependency",
        )
        activation = {"preview_id": preview["preview_id"], "approved": True}
        result = await self.api.call(
            "POST", RUNTIME + "/publications/activate", payload=activation
        )
        replay = await self.api.call(
            "POST", RUNTIME + "/publications/activate", payload=activation
        )
        require(
            replay["replayed"] and replay["publication_id"] == result["publication_id"],
            "activation_exact_retry_changed_publication",
        )
        return result["publication_id"]

    async def publication(self):
        """Create the full template, enforce Store boundaries and enable explicit gates."""
        await self.api.select(self.store_id, [self.store_id])
        previous = json.loads(FIXTURE.read_text()) if FIXTURE.exists() else {}
        if previous.get("store_id") == self.store_id and previous.get("workflow_id"):
            self.record = await self.api.call(
                "GET", "/workflows/" + previous["workflow_id"]
            )
        else:
            self.record = await self.api.call(
                "POST",
                "/workflows",
                expected=201,
                payload={
                    "id": str(uuid4()),
                    "operation_id": str(uuid4()),
                    "key": "qa_runtime_" + uuid4().hex[:12],
                    "name": "درخواست همکاری عمده — آزمون Runtime",
                    "description": "Synthetic isolated PostgreSQL Runtime acceptance",
                    "template": "wholesale_application",
                },
            )
            self.write_fixture()
        payload = {
            "workflow_id": self.record["id"],
            "revision": self.record["revision"],
            "bindings": [
                self.bindings()[0] | {"bot_id": self.fixture["bots"]["foreign"]}
            ],
        }
        await self.api.call(
            "POST", RUNTIME + "/publications/preview", payload=payload, expected=422
        )
        self.publication_id = await self.publish(self.record["revision"])
        await self.set_gate()
        for platform in ("telegram", "bale"):
            await self.set_gate(bot_id=self.fixture["bots"][platform])
        await self.api.call(
            "POST",
            RUNTIME + "/gates",
            payload={
                "operation_id": str(uuid4()),
                "bot_id": self.fixture["bots"]["foreign"],
                "expected_version": 0,
                "enabled": True,
                "killed": False,
            },
            expected=404,
        )
        overview = await self.api.call("GET", RUNTIME)
        require(
            overview["global_enabled"]
            and overview["can_publish"]
            and overview["can_manage"],
            "manager_runtime_capabilities_missing",
        )
        keys = {x["scope_key"] for x in overview["gates"]}
        require(
            "store:" + self.store_id in keys
            and all(
                "bot:" + self.fixture["bots"][p] in keys for p in ("telegram", "bale")
            ),
            "gates_not_namespaced",
        )
        self.write_fixture()

    async def full_flow(self, platform):
        """Exercise both providers' mandatory workflow using real Action workers."""
        case = await self.new_case(platform, deep_link=platform == "bale")
        await self.prepare_form(case, invalid=True)
        await self.confirm(case)
        await self.drain(workers.action_once)
        await self.completed(case)

    async def callback_security(self):
        """Reject capabilities for another customer/Bot, altered data and expired epochs."""
        case = await self.new_case()
        await self.prepare_form(case, document=False)
        row = await self.run(case)
        before = (row.node_id, row.lock_version, deepcopy(row.values))
        for platform in ("telegram", "bale"):
            intruder = await self.new_case(platform, start=False)
            result = await self.offer(
                intruder, self.raw(intruder, callback=case.confirmation)
            )
            require(result.get("handled"), "foreign_capability_not_quarantined")
        await self.offer(case, self.raw(case, callback=case.confirmation[:-1] + "!"))
        row = await self.run(case)
        require(
            (row.node_id, row.lock_version, row.values) == before,
            "forged_callback_changed_run",
        )
        async with session_maker() as db:
            callback = await db.scalar(
                select(WorkflowCallback).where(
                    WorkflowCallback.token_hash
                    == sessions.token_hash(case.confirmation)
                )
            )
            callback.expires_at = security.clock() - timedelta(seconds=1)
            await db.commit()
        result = await self.offer(case, self.raw(case, callback=case.confirmation))
        require(result.get("status") == "callback_expired", "expired_callback_accepted")
        await self.input(case, "cancelled", text_value="/cancel")
        await self.offer(case, self.raw(case, callback=case.confirmation))
        require(
            (await self.run(case)).status == "cancelled", "stale_callback_reopened_run"
        )
        async with session_maker() as db:
            require(
                await db.scalar(
                    select(func.count())
                    .select_from(WorkflowActionJob)
                    .where(WorkflowActionJob.run_id == case.run_id)
                )
                == 0,
                "forged_callback_created_action",
            )

    async def inbox_crash(self):
        """Crash after the real Inbox commit; a fresh worker must consume it once."""
        case = await self.new_case()
        payload = self.raw(case, text_value="QA_PRIVATE_CRASH_NAME_" + uuid4().hex)
        self.private_values.add(payload["message"]["text"])
        original = sessions._consume

        async def crash_after_commit(*args, **kwargs):
            """Interrupt before consumption, after sessions.handle has committed Inbox."""
            raise SimulatedCrash()

        with patch.object(sessions, "_consume", crash_after_commit):
            try:
                await self.offer(case, payload)
            except SimulatedCrash:
                pass
            else:
                raise AssertionError("qa_inbox_crash_checkpoint_not_reached")
        require(sessions._consume is original, "crash_patch_not_restored")
        async with session_maker() as db:
            inbox = await db.scalar(
                select(WorkflowInbox).where(
                    WorkflowInbox.bot_id == case.bot_id,
                    WorkflowInbox.input_id == str(payload["update_id"]),
                )
            )
            require(
                inbox is not None and inbox.status == "pending" and bool(inbox.payload),
                "inbox_not_durable",
            )
            require(
                (await db.get(WorkflowRun, case.run_id)).node_id == "name",
                "crash_advanced_run",
            )
        # The old producing session has closed; workers obtain separate connections.
        await self.drain(workers.inbox_once)
        require(
            (await self.run(case)).node_id == "phone", "inbox_restart_did_not_resume"
        )
        replay = await self.offer(case, payload)
        require(replay.get("duplicate"), "recovered_input_replayed")
        async with session_maker() as db:
            inbox = await db.scalar(
                select(WorkflowInbox).where(
                    WorkflowInbox.bot_id == case.bot_id,
                    WorkflowInbox.input_id == str(payload["update_id"]),
                )
            )
            count = await db.scalar(
                select(func.count())
                .select_from(WorkflowEvent)
                .where(
                    WorkflowEvent.bot_id == case.bot_id,
                    WorkflowEvent.input_id == str(payload["update_id"]),
                )
            )
            require(
                inbox.status == "processed" and inbox.payload == {} and count == 1,
                "inbox_recovery_not_unique_or_private",
            )
        await self.input(case, "cancelled", text_value="/cancel")

    async def inbox_order(self):
        """Keep valid updates queued in sequence while an Action is in flight."""
        case = await self.new_case("bale")
        await self.prepare_form(case, document=False)
        await self.confirm(case)
        updates = [
            self.raw(case, text_value="QA_QUEUED_" + uuid4().hex) for _ in range(2)
        ]
        for payload in updates:
            self.private_values.add(payload["message"]["text"])
            result = await self.offer(case, payload)
            require(result.get("status") == "queued", "action_input_not_queued")
        async with session_maker() as db:
            rows = (
                await db.scalars(
                    select(WorkflowInbox)
                    .where(
                        WorkflowInbox.bot_id == case.bot_id,
                        WorkflowInbox.input_id.in_(
                            [str(p["update_id"]) for p in updates]
                        ),
                    )
                    .order_by(WorkflowInbox.sequence)
                )
            ).all()
            require(
                len(rows) == 2 and all(r.status == "pending" for r in rows),
                "queued_input_not_durable",
            )
            require(
                rows[0].input_id == str(updates[0]["update_id"])
                and rows[0].sequence < rows[1].sequence,
                "inbox_sequence_not_ordered",
            )
        require(
            not await workers.inbox_once(session_maker),
            "inbox_ran_through_pending_action",
        )
        await self.drain(workers.action_once)
        await self.drain(workers.inbox_once)
        await self.completed(case)
        async with session_maker() as db:
            rows = (
                await db.scalars(
                    select(WorkflowInbox).where(
                        WorkflowInbox.bot_id == case.bot_id,
                        WorkflowInbox.input_id.in_(
                            [str(p["update_id"]) for p in updates]
                        ),
                    )
                )
            ).all()
            require(
                all(r.status == "rejected" and r.payload == {} for r in rows),
                "queued_input_silently_lost",
            )

    async def action_crash(self):
        """Interrupt after invoke's real business commit, before Run/job commit."""
        case = await self.new_case()
        await self.prepare_form(case, document=False)
        await self.confirm(case)
        original = workers.invoke

        async def committed_then_crash(*args, **kwargs):
            """Execute the real Layer 2 boundary before killing its Runtime caller."""
            result = await original(*args, **kwargs)
            require(result.status == "succeeded", "layer2_crash_effect_not_committed")
            raise SimulatedCrash()

        with patch.object(workers, "invoke", committed_then_crash):
            try:
                await workers.action_once(session_maker)
            except SimulatedCrash:
                pass
            else:
                raise AssertionError("qa_action_crash_checkpoint_not_reached")
        async with session_maker() as db:
            job = await db.scalar(
                select(WorkflowActionJob).where(WorkflowActionJob.run_id == case.run_id)
            )
            require(
                job.status == "pending" and job.receipt_id is None,
                "runtime_action_commit_not_interrupted",
            )
            receipt = await db.get(ShopActionExecution, job.invocation_id)
            require(
                receipt is not None and receipt.status == "succeeded",
                "layer2_receipt_not_durable",
            )
        await self.drain(workers.action_once)
        await self.completed(case)

    async def ordered_outbox(self):
        """Observe physical prompt order from two concurrently competing real workers."""
        case = await self.new_case("bale")
        native = self.native[case.bot_id]
        offset = len(native.messages)
        for _ in range(2):
            await self.offer(case, self.raw(case, text_value="n" * 161))
        await self.drain()
        ordered = (await self.outboxes(case))[-2:]
        require(
            all(row.status == "sent" for row in ordered)
            and int(ordered[0].message_ids[0]) < int(ordered[1].message_ids[0]),
            "competing_workers_reordered_messages",
        )
        require(
            len(native.messages) == offset + 2,
            "concurrent_worker_duplicated_message",
        )
        offset = len(native.messages)
        # Enqueue two real state transitions before any sender is allowed to run.
        await self.offer(case, self.raw(case, text_value="QA_PRIVATE_ORDERED_NAME"))
        await self.offer(
            case,
            self.raw(
                case, contact={"user_id": case.user_id, "phone_number": "+989101234567"}
            ),
        )
        await self.drain()
        rows = await self.outboxes(case)
        require(
            [r.sequence for r in rows] == list(range(1, len(rows) + 1)),
            "outbox_sequence_gap",
        )
        require(len({r.id for r in rows}) == len(rows), "duplicate_outbox_intent")
        require(
            rows[-2].status == "cancelled" and rows[-1].status == "sent",
            "obsolete_prompt_not_cancelled",
        )
        sent = [
            m for m in native.messages[offset:] if int(m["chat_id"]) == case.user_id
        ]
        require(
            len(sent) == 1 and sent[0]["text"] == rows[-1].payload["text"],
            "obsolete_prompt_physically_sent",
        )
        await self.input(case, "cancelled", text_value="/cancel")

    async def delivery_failure(self, mode):
        """Distinguish definite rejection, ambiguous response and process death."""
        case = await self.new_case(
            "telegram" if mode != "unknown" else "bale", start=False
        )
        response = await self.offer(case, self.raw(case, text_value="/wholesale"))
        case.run_id = response["run_id"]
        native = self.native[case.bot_id]
        before = len(native.messages)
        native.mode = mode
        if mode == "crash":
            try:
                await workers.deliver_once(session_maker)
            except SimulatedCrash:
                pass
            else:
                raise AssertionError("qa_send_crash_checkpoint_not_reached")
            row = (await self.outboxes(case))[-1]
            require(row.status == "sending", "sending_claim_not_durable")
            async with session_maker() as db:
                row = await db.get(WorkflowOutbox, row.id)
                row.claimed_at = security.clock() - timedelta(minutes=6)
                await db.commit()
            require(
                await workers.recover_sending(session_maker) >= 1,
                "crashed_send_not_recovered",
            )
        else:
            require(await workers.deliver_once(session_maker), "delivery_not_claimed")
        row = (await self.outboxes(case))[-1]
        async with session_maker() as db:
            attempt = await db.scalar(
                select(WorkflowDeliveryAttempt).where(
                    WorkflowDeliveryAttempt.outbox_id == row.id
                )
            )
            if mode == "retry":
                require(
                    row.status == "retryable" and attempt.outcome == "rejected",
                    "definite_rejection_not_retryable",
                )
                require(len(native.messages) == before, "rejected_send_was_accepted")
            else:
                require(
                    row.status == "dead_letter"
                    and row.error_code == "runtime_delivery_unknown"
                    and attempt.outcome == "uncertain",
                    "unknown_send_not_quarantined",
                )
        retry_request = {
            "operation_id": str(uuid4()),
            "expected_attempts": row.attempts,
        }
        if mode == "retry":
            # An explicit audited retry advances real backoff without a clock mock.
            retry = await self.api.call(
                "POST", RUNTIME + "/outbox/" + row.id + "/retry", payload=retry_request
            )
            replay = await self.api.call(
                "POST", RUNTIME + "/outbox/" + row.id + "/retry", payload=retry_request
            )
            require(
                retry["status"] == "retryable" and replay["replayed"],
                "signed_delivery_retry_not_audited_or_idempotent",
            )
        else:
            await self.api.call(
                "POST",
                RUNTIME + "/outbox/" + row.id + "/retry",
                payload=retry_request,
                expected=409,
            )
        await self.drain()
        row = (await self.outboxes(case))[-1]
        require(len(native.messages) == before + 1, "provider_send_repeated")
        require(
            row.status == ("sent" if mode == "retry" else "dead_letter"),
            "delivery_final_state",
        )
        if mode != "retry":
            require(row.attempts == 1, "unknown_delivery_automatically_retried")
        await self.offer(case, self.raw(case, text_value="/cancel"))
        # Dead-lettered rows deliberately block later messages for that Run only.
        await self.drain()
        if mode == "retry":
            # Exercise exhaustion through Bale's real error-envelope parser too.
            exhausted = await self.new_case("bale", start=False)
            response = await self.offer(
                exhausted, self.raw(exhausted, text_value="/wholesale")
            )
            exhausted.run_id = response["run_id"]
            native = self.native[exhausted.bot_id]
            before = len(native.messages)
            for number in range(1, 4):
                native.mode = "retry"
                require(
                    await workers.deliver_once(session_maker),
                    "bounded_retry_not_claimed",
                )
                row = (await self.outboxes(exhausted))[-1]
                require(
                    row.attempts == number
                    and row.status == ("retryable" if number < 3 else "dead_letter"),
                    "delivery_retry_limit_not_enforced",
                )
                if number < 3:
                    async with session_maker() as db:
                        row = await db.get(WorkflowOutbox, row.id)
                        row.available_at = security.clock() - timedelta(seconds=1)
                        await db.commit()
            await self.drain()
            require(
                len(native.messages) == before, "rejected_retry_physically_delivered"
            )
            require(
                (await self.outboxes(exhausted))[-1].attempts == 3,
                "exhausted_retry_repeated",
            )
            await self.offer(exhausted, self.raw(exhausted, text_value="/cancel"))

    async def timeouts(self):
        """Run real SKIP LOCKED contenders, then race a due timeout against input."""
        first = await self.new_case()
        before = (await self.run(first)).lock_version
        async with session_maker() as db:
            wait = await db.scalar(
                select(WorkflowWait).where(WorkflowWait.run_id == first.run_id)
            )
            wait.deadline = security.clock() - timedelta(seconds=1)
            await db.commit()
        results = await asyncio.gather(
            workers.timeout_once(session_maker), workers.timeout_once(session_maker)
        )
        row = await self.run(first)
        require(
            sum(bool(x) for x in results) == 1
            and row.status == "expired"
            and row.lock_version == before + 1,
            "competing_timeout_advanced_twice",
        )
        second = await self.new_case("bale")
        async with session_maker() as db:
            wait = await db.scalar(
                select(WorkflowWait).where(WorkflowWait.run_id == second.run_id)
            )
            wait.deadline = security.clock() - timedelta(seconds=1)
            await db.commit()
        await asyncio.gather(
            workers.timeout_once(session_maker),
            self.offer(second, self.raw(second, text_value="QA_PRIVATE_TIMEOUT_RACE")),
        )
        row = await self.run(second)
        require(
            (row.status == "expired" and row.node_id == "name")
            or (row.status == "waiting_input" and row.node_id == "phone"),
            "timeout_input_race_corrupted_state",
        )
        if row.status == "waiting_input":
            await self.offer(second, self.raw(second, text_value="/cancel"))
        await self.drain()

    async def navigation(self):
        """Verify Back checkpoints, optional input, cancellation and fresh restart IDs."""
        case = await self.new_case()
        await self.input(case, "phone", text_value="QA_PRIVATE_BACK_NAME")
        await self.input(case, "name", text_value="/back")
        require("name" not in (await self.run(case)).values, "back_kept_later_value")
        await self.offer(case, self.raw(case, text_value="/restart"))
        old = await self.run(case)
        require(old.status == "cancelled", "restart_did_not_cancel_old_run")
        async with session_maker() as db:
            slot = await db.scalar(
                select(RuntimeSlot).where(
                    RuntimeSlot.bot_id == case.bot_id,
                    RuntimeSlot.user_id == case.user_id,
                )
            )
            require(slot.run_id != case.run_id, "restart_reused_run_identity")
            case.run_id = slot.run_id
        await self.drain()
        await self.prepare_form(case, document=False)
        require(
            not (await self.run(case)).values.get("document"),
            "skip_created_private_document",
        )
        await self.input(case, "cancelled", text_value="/cancel")
        async with session_maker() as db:
            require(
                await db.scalar(
                    select(func.count())
                    .select_from(ShopWholesaleApplication)
                    .where(
                        ShopWholesaleApplication.bot_id == case.bot_id,
                        ShopWholesaleApplication.platform_user_id == case.user_id,
                    )
                )
                == 0,
                "cancel_created_application",
            )

    async def versions(self):
        """Keep old Runs pinned while activation and rollback affect only new Runs."""
        old_case = await self.new_case()
        original_publication = (await self.run(old_case)).publication_id
        async with session_maker() as db:
            snapshot = await db.get(PublishedWorkflow, original_publication)
            original_definition, original_digest = (
                deepcopy(snapshot.definition),
                snapshot.digest,
            )
            original_revision = snapshot.revision
        saved = deepcopy(self.record)
        for node in saved["definition"]["nodes"]:
            if node["id"] == "name":
                node["config"]["prompt"] = "نام و نام خانوادگی — نسخهٔ تازه؟"
        self.record = await self.api.call(
            "PATCH",
            "/workflows/" + self.record["id"],
            payload={
                "operation_id": str(uuid4()),
                "expected_revision": self.record["revision"],
                "name": self.record["name"],
                "description": self.record["description"],
                "definition": saved["definition"],
                "layout": saved["layout"],
            },
        )
        stale = await self.api.call(
            "POST",
            RUNTIME + "/publications/preview",
            payload={
                "workflow_id": self.record["id"],
                "revision": original_revision,
                "bindings": self.bindings(),
            },
        )
        self.new_publication_id = await self.publish(self.record["revision"])
        require(
            self.new_publication_id != original_publication,
            "revision_reused_publication",
        )
        await self.api.call(
            "POST",
            RUNTIME + "/publications/activate",
            payload={"preview_id": stale["preview_id"], "approved": True},
            expected=409,
        )
        newest = await self.new_case("bale")
        require(
            (await self.run(newest)).publication_id == self.new_publication_id,
            "new_run_not_new_version",
        )
        await self.input(old_case, "phone", text_value="QA_PRIVATE_PINNED_NAME")
        require(
            (await self.run(old_case)).publication_id == original_publication,
            "active_run_version_changed",
        )
        rollback = await self.publish(original_revision)
        require(rollback == original_publication, "rollback_created_changed_snapshot")
        rolled_back = await self.new_case(deep_link=True)
        require(
            (await self.run(rolled_back)).publication_id == original_publication,
            "rollback_not_applied_to_new_run",
        )
        require(
            (await self.run(newest)).publication_id == self.new_publication_id,
            "rollback_migrated_existing_run",
        )
        async with session_maker() as db:
            snapshot = await db.get(PublishedWorkflow, original_publication)
            require(
                snapshot.digest == original_digest
                and snapshot.definition == original_definition,
                "published_snapshot_mutated",
            )
        # A direct SQL attempt must also meet the database immutability trigger.
        async with session_maker() as db:
            try:
                await db.execute(
                    text(
                        "UPDATE shop_workflow_publications SET digest = :digest WHERE id = :id"
                    ),
                    {"digest": "0" * 64, "id": original_publication},
                )
                await db.commit()
            except DBAPIError:
                await db.rollback()
            else:
                raise AssertionError("qa_postgresql_publication_trigger_missing")
        self.publication_id = original_publication
        for case in (old_case, newest, rolled_back):
            await self.offer(case, self.raw(case, text_value="/cancel"))
        await self.drain()
        self.write_fixture()

    async def gates(self):
        """Disable immediately; retain old Inbox ownership without accepting new input."""
        case = await self.new_case()
        accepted = self.raw(case, text_value="QA_PRIVATE_GATE_NAME")
        await self.offer(case, accepted)
        await self.drain()
        for bot_id, enabled, killed in (
            (case.bot_id, False, False),
            (case.bot_id, True, True),
            (None, False, False),
        ):
            await self.set_gate(bot_id=bot_id, enabled=enabled, killed=killed)
            try:
                replay = await self.offer(case, accepted)
                require(
                    replay.get("handled") and replay.get("duplicate"),
                    "disabled_runtime_lost_inbox_ownership",
                )
                fresh = await self.offer(case, self.raw(case, text_value="/wholesale"))
                require(
                    fresh == {"handled": False}, "disabled_runtime_accepted_fresh_input"
                )
                async with session_maker() as db:
                    require(
                        not await sessions.enabled(db, self.contexts[case.bot_id]),
                        "gate_not_enforced",
                    )
                require(
                    not await workers.action_once(session_maker),
                    "disabled_gate_executed_action",
                )
            finally:
                await self.set_gate(bot_id=bot_id)
        with patch.object(config, "SHOP_WORKFLOW_RUNTIME_KILL_SWITCH", True):
            require(
                await self.offer(case, self.raw(case, text_value="/wholesale"))
                == {"handled": False},
                "deployment_kill_switch_ignored",
            )
            require(
                (await self.offer(case, accepted)).get("duplicate"),
                "kill_switch_replayed_owned_input",
            )
        result = await self.offer(case, self.raw(case, text_value="/cart"))
        require(
            result == {"handled": False}
            and (await self.run(case)).status == "suspended",
            "legacy_navigation_did_not_suspend",
        )

    def supervisor(self):
        """Use production receiver routing with a trusted fixture-only identity boundary."""
        manager = supervisor_module.MultiBotSupervisor(FastAPI())

        async def identity(bot_id, **_kwargs):
            """Authenticate only the already-resolved QA Bot; never read live secrets."""
            require(bot_id in self.contexts, "receiver_non_fixture_identity")
            return self.contexts[bot_id], self.tokens[bot_id], "webhook", 0

        manager._identity = identity
        return manager

    async def receiver_receipts(self):
        """Route through real Supervisor._process without using live receiver credentials."""
        manager = self.supervisor()
        case = await self.new_case(start=False)
        payload = self.raw(case, text_value="/wholesale")
        result = await manager._process(
            case.bot_id, update_id=payload["update_id"], payload=payload
        )
        case.run_id = result["run_id"]
        async with session_maker() as db:
            require(
                await db.scalar(
                    select(func.count())
                    .select_from(ShopInboundUpdate)
                    .where(
                        ShopInboundUpdate.bot_id == case.bot_id,
                        ShopInboundUpdate.update_id == payload["update_id"],
                    )
                )
                == 0,
                "runtime_created_legacy_claim",
            )
        await self.drain()
        for status in ("processing", "processed", "needs_review"):
            quarantined = self.raw(case, text_value="/wholesale")
            async with session_maker() as db:
                db.add(
                    ShopInboundUpdate(
                        bot_id=case.bot_id,
                        platform=case.platform,
                        bot_fingerprint="a" * 64,
                        update_id=quarantined["update_id"],
                        status=status,
                    )
                )
                await db.commit()
            result = await manager._process(
                case.bot_id, update_id=quarantined["update_id"], payload=quarantined
            )
            require(
                result
                == {"handled": True, "status": "duplicate", "receipt_state": status},
                "legacy_claim_not_quarantined",
            )
            require(
                (await self.run(case)).node_id == "name",
                "legacy_claim_advanced_runtime",
            )
        await self.input(case, "cancelled", text_value="/cancel")

    async def legacy(self):
        """Exercise inherited shopping reads through real receiver/dispatcher handlers."""
        manager = self.supervisor()
        for platform in ("telegram", "bale"):
            case = await self.new_case(platform, start=False)
            native = self.native[case.bot_id]
            for command in ("/start", "/catalog", "/cart", "/checkout", "/orders"):
                payload = self.raw(case, text_value=command)
                before = len(native.messages)
                result = await manager._process(
                    case.bot_id, update_id=payload["update_id"], payload=payload
                )
                require(
                    result.get("status") == "processed"
                    and len(native.messages) > before,
                    "legacy_command_" + command.removeprefix("/"),
                )
                delivered = len(native.messages)
                again = await manager._process(
                    case.bot_id, update_id=payload["update_id"], payload=payload
                )
                require(
                    again.get("status") == "duplicate"
                    and len(native.messages) == delivered,
                    "legacy_receipt_did_not_deduplicate",
                )
            # Exact financial envelopes bypass Runtime before gates/identity checks.
            financial = [
                {"update_id": self.next_id(), "pre_checkout_query": {}},
                self.raw(case, text_value="payment"),
            ]
            financial[1]["message"]["successful_payment"] = {}
            for payload in financial:
                require(
                    await ingress.try_ingress(self.contexts[case.bot_id], payload)
                    == {"handled": False},
                    "financial_update_consumed_by_runtime",
                )
            precheckout = {
                "update_id": self.next_id(),
                "pre_checkout_query": {
                    "id": uuid4().hex,
                    "from": {"id": case.user_id},
                    "invoice_payload": "qa_invalid_invoice",
                    "currency": "XTR" if platform == "telegram" else "IRR",
                    "total_amount": 1,
                },
            }
            result = await manager._process(
                case.bot_id, update_id=precheckout["update_id"], payload=precheckout
            )
            require(
                result.get("status") == "declined"
                and native.precheckout[-1]["ok"] is False,
                "legacy_precheckout_not_reached",
            )

    async def security_http(self):
        """Check real signed Store isolation and every Runtime metadata projection."""
        completed = None
        for candidate in self.cases:
            if candidate.run_id and (await self.run(candidate)).status == "completed":
                completed = candidate
                break
        require(completed is not None, "no_completed_run_for_http_inspection")
        await self.api.select(self.fixture["stores"][1], [self.fixture["stores"][1]])
        try:
            await self.api.call(
                "GET", RUNTIME + "/runs/" + completed.run_id, expected=404
            )
            await self.api.call(
                "POST",
                RUNTIME + "/runs/" + completed.run_id + "/recover",
                payload={
                    "operation_id": str(uuid4()),
                    "expected_version": 0,
                    "operation": "cancel",
                },
                expected=404,
            )
            for endpoint in (
                "/runs",
                "/publications",
                "/bindings",
                "/outbox",
                "/history",
            ):
                body = await self.api.call("GET", RUNTIME + endpoint)
                require(
                    completed.run_id not in json.dumps(body)
                    and self.publication_id not in json.dumps(body),
                    "foreign_store_metadata_leak",
                )
        finally:
            await self.api.select(self.store_id, [self.store_id])
        for endpoint in (
            "",
            "/runs",
            "/runs/" + completed.run_id,
            "/publications",
            "/bindings",
            "/outbox",
            "/history",
        ):
            body = await self.api.call("GET", RUNTIME + endpoint)
            encoded = json.dumps(body, ensure_ascii=False)
            require(
                not self.contains_private(body),
                "runtime_metadata_contains_customer_values",
            )
            require(
                not any(token in encoded for token in self.tokens.values()),
                "runtime_metadata_contains_token",
            )
        detail = await self.api.call("GET", RUNTIME + "/runs/" + completed.run_id)
        require(
            all(value["value"] == "[private]" for value in detail["variables"]),
            "variables_not_private",
        )
        case = await self.new_case()
        await self.offer(case, self.raw(case, text_value="/cart"))
        row = await self.run(case)
        recovery = {
            "operation_id": str(uuid4()),
            "expected_version": row.lock_version,
            "operation": "resume",
        }
        result = await self.api.call(
            "POST", RUNTIME + "/runs/" + case.run_id + "/recover", payload=recovery
        )
        require(result["status"] == "waiting_input", "audited_resume_failed")
        replay = await self.api.call(
            "POST", RUNTIME + "/runs/" + case.run_id + "/recover", payload=recovery
        )
        require(replay["replayed"], "recovery_exact_retry_failed")
        await self.api.call(
            "POST",
            RUNTIME + "/runs/" + case.run_id + "/recover",
            payload=recovery | {"operation_id": str(uuid4())},
            expected=409,
        )
        history = await self.api.call("GET", RUNTIME + "/history")
        require(
            any(
                x["id"] == recovery["operation_id"] and x["action"] == "recover"
                for x in history["items"]
            ),
            "recovery_not_audited",
        )
        await self.input(case, "cancelled", text_value="/cancel")

    async def commerce_fingerprint(self):
        """Count every financial/order/delivery table and fingerprint inventory state."""
        async with session_maker() as db:
            names = (
                await db.scalars(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                        "AND (tablename LIKE 'shop_order%' OR tablename LIKE 'shop_payment%' "
                        "OR tablename LIKE 'shop_refund%' OR tablename LIKE 'shop_wallet%' "
                        "OR tablename LIKE 'shop_campaign%' OR tablename LIKE 'shop_digital_deliver%') "
                        "ORDER BY tablename"
                    )
                )
            ).all()
            require(bool(names), "commerce_tables_not_inspected")
            values = {}
            for name in names:
                require(name.replace("_", "").isalnum(), "unsafe_catalog_identifier")
                values[name] = await db.scalar(
                    text('SELECT count(*) FROM "' + name + '"')
                )
            values["inventory"] = (
                await db.execute(
                    text("SELECT id, stock_quantity FROM shop_products ORDER BY id")
                )
            ).all()
            values["inventory"] = [list(row) for row in values["inventory"]]
            return values

    async def unchanged_commerce(self):
        """Verify Runtime did not create an order, payment, refund or stock mutation."""
        require(
            await self.commerce_fingerprint() == self.initial_commerce,
            "commerce_rows_or_stock_changed",
        )
        require(self.fence.denied == 0, "unexpected_live_network_attempt")


async def main():
    """Execute bounded scenarios and preserve truthful PASS/FAIL/BLOCKED evidence."""
    evidence = {
        "status": "RUNNING",
        "environment": "aiogram-workflow-runtime-qa isolated PostgreSQL",
        "fake_providers_only": True,
        "live_provider_calls": 0,
        "checks": [{"check": name, "status": "BLOCKED"} for name in CHECK_NAMES],
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=2))
    identity, harness = None, None
    try:
        fixture = json.loads(MANIFEST.read_text())
        fence = NetworkFence()
        with fence.install():
            identity = await diagnostic_identity()
            async with httpx.AsyncClient(
                base_url="http://127.0.0.1:5000",
                timeout=30,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                harness = Harness(fixture, SignedAdmin(client, identity), evidence)
                harness.fence = fence
                if not await harness.check(CHECK_NAMES[0], harness.bootstrap):
                    return 1
                with harness.providers():
                    if not await harness.check(CHECK_NAMES[1], harness.publication):
                        return 1
                    scenarios = [
                        lambda: harness.full_flow("telegram"),
                        lambda: harness.full_flow("bale"),
                        harness.callback_security,
                        harness.inbox_crash,
                        harness.inbox_order,
                        harness.action_crash,
                        harness.ordered_outbox,
                        lambda: harness.delivery_failure("retry"),
                        lambda: harness.delivery_failure("unknown"),
                        lambda: harness.delivery_failure("crash"),
                        harness.timeouts,
                        harness.navigation,
                        harness.versions,
                        harness.gates,
                        harness.receiver_receipts,
                        harness.legacy,
                        harness.security_http,
                        harness.unchanged_commerce,
                    ]
                    for name, scenario in zip(CHECK_NAMES[2:], scenarios, strict=True):
                        await harness.check(name, scenario)
                    harness.write_fixture()
        return int(any(item["status"] != "PASS" for item in evidence["checks"]))
    except Exception as error:  # noqa: BLE001 - raw setup exceptions may contain secrets.
        evidence["fatal_error"] = type(error).__name__
        print("FAIL  Runtime acceptance setup: " + type(error).__name__, flush=True)
        return 1
    finally:
        if identity is not None:
            try:
                await revoke_diagnostic_session(identity[0], identity[3])
            except Exception as error:  # noqa: BLE001 - cleanup must preserve evidence.
                evidence["session_cleanup"] = type(error).__name__
        evidence["status"] = (
            "PASS"
            if all(item["status"] == "PASS" for item in evidence["checks"])
            and not evidence.get("session_cleanup")
            and not evidence.get("fatal_error")
            else "FAIL"
        )
        if harness is not None:
            harness.write_evidence()
        else:
            EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        await engine.dispose()
        if evidence.get("session_cleanup"):
            raise RuntimeError("qa_diagnostic_session_cleanup_failed")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
