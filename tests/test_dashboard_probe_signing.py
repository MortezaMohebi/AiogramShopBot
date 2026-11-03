"""Verify diagnostic requests use the exact production session HMAC format."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from scripts.dashboard_probe_signing import signed_headers


TOKEN = "A" * 43
SECRET = "b" * 40


def test_probe_binds_session_to_signed_request() -> None:
    """Any changed method/path/session must invalidate the expected proof."""
    actual = signed_headers(
        "/overview", 7, 4, TOKEN, SECRET, timestamp=1720000000
    )
    digest = hashlib.sha256(b"").hexdigest()
    canonical = (
        "1720000000\nGET\n/internal/admin/v1/overview\n"
        + digest + "\n7\n4"
    )
    signature = hmac.new(
        SECRET.encode(), canonical.encode(), hashlib.sha256
    ).hexdigest()
    proof = hmac.new(
        SECRET.encode(),
        ("session-v1\n" + signature + "\n" + TOKEN).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert actual == {
        "x-shop-time": "1720000000",
        "x-shop-signature": signature,
        "x-shop-staff": "7",
        "x-shop-version": "4",
        "x-shop-session": TOKEN,
        "x-shop-session-proof": proof,
    }
    assert signed_headers(
        "/settings", 7, 4, TOKEN, SECRET, timestamp=1720000000
    )["x-shop-session-proof"] != proof
    assert signed_headers(
        "/overview", 7, 4, "C" * 43, SECRET, timestamp=1720000000
    )["x-shop-session-proof"] != proof


@pytest.mark.parametrize("invalid", ["", "//evil", "/settings?token=x"])
def test_probe_rejects_unsafe_paths(invalid: str) -> None:
    """Never allow an unsignable or host-override diagnostic target."""
    with pytest.raises(ValueError, match="Invalid diagnostic"):
        signed_headers(invalid, 7, 4, TOKEN, SECRET)


def test_probe_rejects_missing_session_bearer() -> None:
    """A bare bridge signature is insufficient after the security upgrade."""
    with pytest.raises(ValueError, match="Invalid diagnostic"):
        signed_headers("/auth/me", 7, 4, "", SECRET)
