"""Pure request-signing helpers for the isolated admin diagnostic probe.

The diagnostic token is transient and must never be logged or included in a
browser response. These helpers share the signed bridge's canonical format.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def signed_headers(
    path: str,
    staff_id: int,
    version: int,
    token: str,
    secret: str,
    *,
    timestamp: int | None = None,
) -> dict[str, str]:
    """Sign a GET with its opaque database-backed session bearer.

    Reject malformed values before building a request or computing a proof.
    The return value is for transport only and must not be printed.
    """
    if (
        not path.startswith("/")
        or path.startswith("//")
        or "?" in path
        or "#" in path
        or not isinstance(staff_id, int)
        or staff_id <= 0
        or not isinstance(version, int)
        or version <= 0
        or not isinstance(token, str)
        or TOKEN_RE.fullmatch(token) is None
        or not isinstance(secret, str)
        or len(secret) < 32
    ):
        raise ValueError("Invalid diagnostic signing parameters.")

    stamp = str(int(time.time()) if timestamp is None else timestamp)
    target = "/internal/admin/v1" + path
    digest = hashlib.sha256(b"").hexdigest()
    canonical = "\n".join(
        (stamp, "GET", target, digest, str(staff_id), str(version))
    )
    signature = hmac.new(
        secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    proof = hmac.new(
        secret.encode("utf-8"),
        ("session-v1\n" + signature + "\n" + token).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "x-shop-time": stamp,
        "x-shop-signature": signature,
        "x-shop-staff": str(staff_id),
        "x-shop-version": str(version),
        "x-shop-session": token,
        "x-shop-session-proof": proof,
    }
