"""Canonical business identity excludes proof tokens, correlation and retry timing."""

import hashlib

from services.shop_actions.contracts import bounded_json


def sha256(value: str) -> str:
    """Hash an opaque token/key without retaining its raw reusable bearer value."""
    return hashlib.sha256(value.encode()).hexdigest()


def request_hash(principal, invocation, typed_input) -> str:
    """Bind exact operation, trusted owner, definition scope and normalized input."""
    return sha256(
        bounded_json(
            {
                "invocation_id": invocation.invocation_id,
                "action_key": invocation.action_key,
                "action_version": invocation.action_version,
                "store_id": principal.store_id,
                "bot_id": principal.bot_id,
                "platform": principal.platform,
                "actor": principal.actor_key,
                "customer_id": principal.customer_id,
                "identity_id": principal.identity_id,
                "workflow_id": invocation.workflow_id,
                "workflow_revision": invocation.workflow_revision,
                "workflow_run_id": invocation.workflow_run_id,
                "node_id": invocation.node_id,
                "input": typed_input.model_dump(mode="json"),
            }
        )
    )
