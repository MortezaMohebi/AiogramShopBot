"""Private signed WPMCP HTTP adapter over authorized services."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from db import session_maker
from services import shop_admin_security as security
from services.shop_mcp import grants
from services.shop_mcp.contracts import (
    AccessRequest,
    GatewayCaller,
    McpRejected,
)
from services.shop_mcp.proofs import decode_json_object, verify_delegation
from services.shop_mcp.settings import McpSettings, from_environment
from services.shop_mcp.tool_contracts import (
    PromptRequest,
    ResourceRequest,
    ToolCall,
)

router = APIRouter(prefix="/internal/mcp/v1", tags=["Private WPMCP adapter"])
MAX_BODY_BYTES = 262_144
MAX_RESPONSE_BYTES = 2_097_152


async def database():
    """Use the application's ordinary transaction factory, never another DB."""
    async with session_maker() as db:
        yield db


McpDb = Annotated[AsyncSession, Depends(database)]


def respond(value: dict, status: int = 200) -> JSONResponse:
    """Keep private responses out of intermediary caches."""
    response = JSONResponse(
        value,
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )
    if len(response.body) > MAX_RESPONSE_BYTES:
        # A domain service may already have committed. Report unavailable,
        # preserve its operation ID and let the compact receipt reconcile it.
        return JSONResponse(
            {"ok": False, "error": {"code": "mcp_response_too_large"}},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    return response


async def authenticated_request(request: Request):
    """Bound bytes, then verify the configured gateway and exact target."""
    settings = getattr(request.app.state, "mcp_settings", None)
    if settings is None:
        settings = from_environment()
    if not isinstance(settings, McpSettings) or not settings.enabled:
        raise McpRejected("mcp_disabled", 503)
    media_type = request.headers.get("content-type", "").partition(";")[0]
    if media_type.strip().lower() != "application/json":
        raise McpRejected("mcp_json_required", 415)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            raise McpRejected("mcp_request_too_large", 413)
        body.extend(chunk)
    try:
        raw_path = request.scope.get("raw_path", request.url.path.encode())
        target = raw_path.decode("ascii")
        query = request.scope.get("query_string", b"")
        if query:
            target += "?" + query.decode("ascii")
        delegation = verify_delegation(
            request.headers.get("x-wpmcp-delegation", ""),
            method=request.method,
            target=target,
            body=bytes(body),
            configuration=settings.proofs,
        )
        payload = decode_json_object(bytes(body))
    except McpRejected:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise McpRejected("mcp_invalid_request", 422) from None
    request.state.mcp_delegation = delegation
    request.state.mcp_proofs = settings.proofs
    return delegation, payload


@router.post("/pairings/prepare")
@router.post("/pairings/status")
async def pairing(request: Request, db: McpDb):
    """Transport consent requests without assigning a native human identity."""
    from services.shop_mcp import admin
    from services.shop_mcp.contracts import PairingRequest

    try:
        delegation, payload = await authenticated_request(request)
        await grants.consume_nonce(db, delegation)
        if request.url.path.endswith("/prepare"):
            try:
                arguments = PairingRequest.model_validate(payload)
            except (ValidationError, ValueError, TypeError):
                raise McpRejected("mcp_invalid_request", 422) from None
            result = await grants.prepare_pairing(
                db,
                delegation=delegation,
                **arguments.model_dump(mode="json"),
            )
        else:
            if payload:
                raise McpRejected("mcp_invalid_request", 422)
            result = await admin.pairing_status(db, delegation=delegation)
        await db.commit()
        return respond({"ok": True, "result": result})
    except McpRejected as error:
        await db.rollback()
        return respond(
            {"ok": False, "error": {"code": error.code}}, error.status
        )
    except Exception:  # noqa: BLE001 -- redact private boundary failures.
        await db.rollback()
        return respond(
            {"ok": False, "error": {"code": "mcp_unavailable"}}, 503
        )


@router.post("/access")
async def check_access(request: Request, db: McpDb):
    """Check native authority before WPMCP discloses or decides a review."""
    try:
        delegation, payload = await authenticated_request(request)
        try:
            arguments = AccessRequest.model_validate(payload)
        except (ValidationError, ValueError, TypeError):
            raise McpRejected("mcp_invalid_request", 422) from None
        principal = await grants.resolve_grant(
            db,
            delegation=delegation,
            store_id=arguments.store_id,
            required_scope=arguments.required_scope,
        )
        await grants.consume_nonce(db, delegation)
        await db.commit()
        return respond(
            {
                "ok": True,
                "store_id": principal.scope.current_store_id,
                "grant_id": principal.grant.id,
                "grant_version": principal.grant.version,
                "required_scope": arguments.required_scope,
            }
        )
    except McpRejected as rejected:
        await db.rollback()
        return respond(
            {"ok": False, "error": {"code": rejected.code}},
            rejected.status,
        )
    except Exception:  # noqa: BLE001 -- redact private boundary failures.
        # Database/provider exceptions may contain SQL parameters. The private
        # Return a controlled failure without granting approval authority.
        await db.rollback()
        return respond(
            {"ok": False, "error": {"code": "mcp_unavailable"}},
            503,
        )


async def _execute(request, db, kind):
    """Control private dispatcher errors and consume nonces atomically."""
    from services.shop_mcp import discovery, dispatch
    from services.shop_runtime.contracts import RuntimeRejected

    try:
        delegation, payload = await authenticated_request(request)
        if kind == "tool":
            envelope = _envelope(ToolCall, payload)
            tool, principal, data = await dispatch.authorize(
                db,
                delegation,
                envelope.name,
                envelope.arguments,
            )
            await grants.consume_nonce(db, delegation)
            result = await dispatch.invoke_authorized(
                db, tool, principal, data
            )
        else:
            model = ResourceRequest if kind == "resource" else PromptRequest
            envelope = _envelope(model, payload)
            principal = await grants.resolve_grant(
                db,
                delegation=delegation,
                store_id=envelope.store_id,
                required_scope="workflow:read",
            )
            await grants.consume_nonce(db, delegation)
            if kind == "resource":
                result = await discovery.resource(
                    db,
                    principal,
                    envelope.store_id,
                    envelope.name,
                    page=envelope.page,
                )
            else:
                result = await discovery.prompt(
                    db,
                    principal,
                    envelope.store_id,
                    envelope.name,
                    envelope.requirements,
                )
        await db.commit()
        return respond(
            {
                "ok": True,
                "result": result,
                "content_trust": {
                    "administrator_fields": "untrusted_data",
                    "customer_fields": "private_by_default",
                    "tool_output_is_authorization": False,
                },
            }
        )
    except (McpRejected, security.SecurityRejected, RuntimeRejected) as error:
        await db.rollback()
        return respond(
            {"ok": False, "error": {"code": error.code}}, error.status
        )
    except Exception:  # noqa: BLE001 -- redact private boundary failures.
        await db.rollback()
        return respond(
            {"ok": False, "error": {"code": "mcp_unavailable"}},
            503,
        )


def _envelope(model, payload):
    """Classify only input parsing failures as a definite invalid request.

    A later serialization or receipt failure can follow a committed effect;
    that is an unavailable/unknown result which needs receipt reconciliation.
    """
    try:
        return model.model_validate(payload)
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise McpRejected("mcp_invalid_request", 422) from None


@router.post("/tools/call")
async def call_tool(request: Request, db: McpDb):
    """Call an existing typed tool with current native Store authorization."""
    return await _execute(request, db, "tool")


@router.post("/resources/read")
async def read_resource(request: Request, db: McpDb):
    """Resolve a registered resource independently of network URLs."""
    return await _execute(request, db, "resource")


@router.post("/prompts/get")
async def get_prompt(request: Request, db: McpDb):
    """Produce authenticated guidance without creating any business effect."""
    return await _execute(request, db, "prompt")


async def _intent_execute(request, db, action):
    """Admit a signed private intent request in the same nonce transaction."""
    from services.shop_mcp import approval_contracts as contracts
    from services.shop_mcp import execution, preparations
    from services.shop_runtime.contracts import RuntimeRejected

    try:
        delegation, payload = await authenticated_request(request)
        caller = GatewayCaller(delegation)
        if action == "prepare":
            envelope = _envelope(contracts.PrivatePreparation, payload)
            data = _envelope(
                preparations.KINDS[envelope.kind][0],
                envelope.arguments,
            ).model_dump(mode="json")
            principal = await preparations.authority(
                db,
                caller,
                envelope.kind,
                data["store_id"],
                write=True,
            )
        else:
            model = {
                "review": contracts.IntentRequest,
                "commit": contracts.CommitRequest,
                "receipt": contracts.ReceiptRequest,
            }[action]
            envelope = _envelope(model, payload)
            identity = (
                envelope.operation_id
                if action == "receipt"
                else envelope.intent_id
            )
            row = await preparations.owned(db, caller, identity)
            if action == "receipt":
                principal = await grants.resolve_grant(
                    db,
                    delegation=delegation,
                    store_id=row.store_id,
                    required_scope=(
                        "runtime:read"
                        if row.kind.startswith("runtime.")
                        else "workflow:read"
                    ),
                )
            else:
                principal = await preparations.authority(
                    db,
                    caller,
                    row.kind,
                    row.store_id,
                    write=action in {"review", "commit"},
                )
        await grants.consume_nonce(db, delegation)
        if action == "prepare":
            result = await preparations.prepare(
                db,
                principal,
                envelope.kind,
                data,
            )
        elif action == "review":
            result = await preparations.review(
                db,
                principal,
                intent_id=envelope.intent_id,
            )
        elif action == "commit":
            result = await execution.commit(
                db,
                principal,
                intent_id=envelope.intent_id,
                approval_proof=envelope.approval_proof,
                configuration=request.state.mcp_proofs,
            )
        else:
            result = await execution.receipt(
                db,
                principal,
                operation_id=envelope.operation_id,
            )
        await db.commit()
        return respond({"ok": True, "result": result})
    except (McpRejected, security.SecurityRejected, RuntimeRejected) as error:
        await db.rollback()
        return respond(
            {"ok": False, "error": {"code": error.code}}, error.status
        )
    except Exception:  # noqa: BLE001 -- redact private boundary failures.
        await db.rollback()
        return respond(
            {"ok": False, "error": {"code": "mcp_unavailable"}},
            503,
        )


@router.post("/intents/prepare")
async def prepare_intent(request: Request, db: McpDb):
    """Freeze one closed request without deciding or executing it."""
    return await _intent_execute(request, db, "prepare")


@router.post("/intents/review")
async def review_intent(request: Request, db: McpDb):
    """Disclose review bytes only to the current native Store manager."""
    return await _intent_execute(request, db, "review")


@router.post("/commit")
async def commit_intent(request: Request, db: McpDb):
    """Execute stored evidence with an exact WPMCP human decision proof."""
    return await _intent_execute(request, db, "commit")


@router.post("/receipts/get")
async def native_receipt(request: Request, db: McpDb):
    """Reconcile a receipt without a business effect or fresh approval."""
    return await _intent_execute(request, db, "receipt")
