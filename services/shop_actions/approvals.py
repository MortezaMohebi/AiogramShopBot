"""Issue and consume expiring opaque proofs only at trusted Backend boundaries."""

from __future__ import annotations

import hmac
import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from models.shop_action import ShopActionAuthorization
from services import shop_admin_security as security
from services.shop_actions.context import refresh_principal
from services.shop_actions.contracts import ActionRejected
from services.shop_actions.hashing import request_hash, sha256
from services.shop_store_context import resolve_context


async def issue_authorization(
    db,
    *,
    subject,
    approver,
    invocation,
    purpose: str,
    registry,
    lifetime_seconds: int = 300,
) -> str:
    """Bind a verified confirmation/approval to one exact business operation.

    This is an internal service, deliberately absent from admin HTTP routes.
    The caller must first obtain an actual customer confirmation interaction or
    independently authenticated operator decision. A Boolean is never proof.
    """
    subject = await refresh_principal(db, subject)
    approver = await refresh_principal(db, approver)
    spec = registry.resolve(invocation.action_key, invocation.action_version)
    typed_input = spec.input(invocation.input)
    from services.shop_actions.policies import require_available

    await require_available(db, subject, spec, invocation)
    required = (
        {"customer_confirmation", "operator_approval"}
        if spec.descriptor.confirmation == "both"
        else {spec.descriptor.confirmation}
    )
    if purpose not in required:
        raise ActionRejected("action_approval_forbidden")
    if invocation.mode != "live" or not 1 <= lifetime_seconds <= 900:
        raise ActionRejected("action_approval_invalid")
    if purpose == "customer_confirmation":
        if approver.actor_kind != "customer" or approver.actor_key != subject.actor_key:
            raise ActionRejected("action_approval_forbidden")
    elif purpose == "operator_approval":
        if approver.actor_kind != "staff" or "actions.approve" not in approver.scopes:
            raise ActionRejected("action_approval_forbidden")
        try:
            scope = await resolve_context(
                db, staff_id=approver.staff_id, session_id=approver.session_id
            )
            scope.require(subject.store_id, manage=True)
        except security.SecurityRejected:
            raise ActionRejected("action_approval_forbidden") from None
    else:
        raise ActionRejected("action_approval_invalid")
    if approver.store_id != subject.store_id or approver.bot_id != subject.bot_id:
        raise ActionRejected("action_approval_forbidden")
    token = secrets.token_urlsafe(32)
    now = security.clock()
    db.add(
        ShopActionAuthorization(
            id=str(uuid4()),
            token_sha256=sha256(token),
            store_id=subject.store_id,
            bot_id=subject.bot_id,
            actor_key=subject.actor_key,
            action_key=invocation.action_key,
            action_version=invocation.action_version,
            invocation_id=invocation.invocation_id,
            input_sha256=request_hash(subject, invocation, typed_input),
            purpose=purpose,
            issued_by=approver.actor_key,
            issued_at=now,
            expires_at=now + timedelta(seconds=lifetime_seconds),
        )
    )
    await db.commit()
    return token


async def consume_authorizations(db, *, principal, invocation, spec, digest) -> bool:
    """Lock and validate all required proofs before marking any as consumed."""
    policy = spec.descriptor.confirmation
    needed = []
    if policy in {"customer_confirmation", "both"}:
        needed.append(("customer_confirmation", invocation.confirmation_receipt))
    if policy in {"operator_approval", "both"}:
        needed.append(("operator_approval", invocation.approval_receipt))
    if any(token is None for _, token in needed):
        return False
    rows = []
    for purpose, token in needed:
        row = await db.scalar(
            select(ShopActionAuthorization)
            .where(
                ShopActionAuthorization.token_sha256 == sha256(token),
                ShopActionAuthorization.store_id == principal.store_id,
                ShopActionAuthorization.actor_key == principal.actor_key,
                ShopActionAuthorization.bot_id == principal.bot_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            row is None
            or row.purpose != purpose
            or row.invocation_id != invocation.invocation_id
            or row.action_key != invocation.action_key
            or row.action_version != invocation.action_version
            or not hmac.compare_digest(row.input_sha256, digest)
            or row.consumed_invocation_id is not None
        ):
            raise ActionRejected("action_approval_invalid")
        if security.utc(row.expires_at) <= security.clock():
            raise ActionRejected("action_approval_expired")
        rows.append(row)
    for row in rows:
        row.consumed_invocation_id = invocation.invocation_id
        row.consumed_at = security.clock()
    return True
