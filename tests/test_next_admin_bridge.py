"""Offline security invariants for the Next.js signed FastAPI bridge.

These tests are source-only additions in this phase; integration execution
with PostgreSQL/Redis and a real Next.js build is deferred by project policy.
"""

from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from dashboard.next_api import require_staff, verify_bridge_signature


SECRET = "offline-next-bridge-secret-with-sufficient-entropy"


def signed(
    *,
    method: str = "PATCH",
    path: str = "/internal/admin/v1/products/11",
    body: bytes = b'{"price_irr":"145000"}',
    user_id: int = 3,
    version: int = 2,
    stamp: str = "1800000000",
) -> str:
    """Create a properly signed synthetic server-side request."""
    digest = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(
        (stamp, method, path, digest, str(user_id), str(version))
    )
    return hmac.new(
        SECRET.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify(**changes: object) -> bool:
    """Check fixed-time request details with optional one-field tampering."""
    original = {
        "secret": SECRET,
        "timestamp": "1800000000",
        "method": "PATCH",
        "target": "/internal/admin/v1/products/11",
        "body": b'{"price_irr":"145000"}',
        "staff_id": 3,
        "session_version": 2,
        "signature": signed(),
        "now": 1800000000,
    }
    return verify_bridge_signature(**(original | changes))


def test_valid_signed_admin_call() -> None:
    """A matching method/body/path/staff/version is accepted."""
    assert verify()


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("method", "POST"),
        ("target", "/internal/admin/v1/products/12"),
        ("target", "/internal/admin/v1/products/11?force=1"),
        ("body", b'{"price_irr":"999999999999"}'),
        ("staff_id", 4),
        ("session_version", 3),
        ("timestamp", "1800000300"),
        ("signature", "a" * 64),
        ("secret", "not-an-authorized-bridge"),
    ],
)
def test_request_tampering_is_rejected(field: str, wrong_value: object) -> None:
    """A signed request cannot authorize a different mutation or identity."""
    assert not verify(**{field: wrong_value})


def test_expired_signature_cannot_be_replayed() -> None:
    """Reject a replay after the narrowly bounded authentication window."""
    assert not verify(now=1800000061)


def test_inactive_or_unauthorized_roles_never_gain_finance_rights() -> None:
    """Even valid HMAC is insufficient without an authorized live DB role."""
    with pytest.raises(HTTPException) as denied:
        require_staff(SimpleNamespace(role="content"), "finance")
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as missing:
        require_staff(None, "sales")
    assert missing.value.status_code == 401
    assert require_staff(
        SimpleNamespace(role="superadmin"), "finance"
    ).role == "superadmin"
