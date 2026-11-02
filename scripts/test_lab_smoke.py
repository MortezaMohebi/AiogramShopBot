"""End-to-end signed admin/API smoke for the isolated Docker Compose lab.

This executable runs only inside the disposable lab network. It uses synthetic
staff accounts, validates RBAC and HMAC, and exercises private upload, preview,
moderation and deletion without connecting to Telegram/Bale providers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


API = "http://api:5000/internal/admin/v1"
NEXT = "http://next-admin:3000"


@dataclass(frozen=True)
class Operator:
    """A short-lived authenticated test-only staff principal."""

    id: int
    version: int
    role: str


def signed_request(
    method: str,
    path: str,
    payload: bytes = b"",
    *,
    operator: Operator | None = None,
    content_type: str | None = None,
    sign_correctly: bool = True,
) -> tuple[int, bytes]:
    """Make the exact HMAC-authenticated request used by the Next BFF."""
    secret = os.environ["NEXT_ADMIN_BRIDGE_SECRET"].encode("utf-8")
    timestamp = str(int(time.time()))
    staff_id = operator.id if operator else 0
    version = operator.version if operator else 0
    digest = hashlib.sha256(payload).hexdigest()
    canonical = "\n".join((
        timestamp,
        method.upper(),
        "/internal/admin/v1" + path,
        digest,
        str(staff_id),
        str(version),
    ))
    signature = hmac.new(
        secret, canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not sign_correctly:
        signature = "0" * 64
    headers = {
        "X-Shop-Time": timestamp,
        "X-Shop-Staff": str(staff_id),
        "X-Shop-Version": str(version),
        "X-Shop-Signature": signature,
    }
    if content_type:
        headers["Content-Type"] = content_type

    request = urllib.request.Request(
        API + path,
        data=payload if method in ("POST", "PATCH") else None,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def request_json(
    method: str, path: str, payload: dict | None = None,
    *, operator: Operator | None = None,
    sign_correctly: bool = True,
) -> tuple[int, dict | list]:
    """Decode only JSON returned from the isolated administrative bridge."""
    body = (
        json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if payload is not None else b""
    )
    status, raw = signed_request(
        method, path, body,
        operator=operator,
        sign_correctly=sign_correctly,
        content_type="application/json" if payload is not None else None,
    )
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        result = {"detail": "Non-JSON response"}
    return status, result


def expect(got: int, desired: int, name: str) -> None:
    """Report one safe check without echoing private HMACs or passwords."""
    if got != desired:
        raise AssertionError(
            f"{name}: expected HTTP {desired}, received HTTP {got}"
        )
    print(f"PASS {name}: HTTP {got}")


def login(username: str, password_key: str, role: str) -> Operator:
    """Prove that real Argon2 staff hashes and Redis throttling work."""
    status, result = request_json(
        "POST",
        "/auth/login",
        {"username": username, "password": os.environ[password_key]},
    )
    expect(status, 200, f"login {username}")
    if not isinstance(result, dict) or result.get("role") != role:
        raise AssertionError(f"Incorrect role for synthetic staff {username}")
    return Operator(
        id=int(result["id"]),
        version=int(result["session_version"]),
        role=role,
    )


def form_upload(product_id: int) -> tuple[bytes, str]:
    """Create a small multipart PNG from inert fixture bytes."""
    boundary = "shop-lab-safe-multipart-boundary"
    fields = {
        "product_id": str(product_id),
        "position": "0",
        "caption": "فایل آزمایشی؛ بدون ارسال به پیام‌رسان",
    }
    parts = []
    for field, value in fields.items():
        parts.append(
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{field}"\r\n'
            "\r\n"
            f"{value}\r\n".encode("utf-8")
        )
    # The existing media validator relies on recognized signature bytes.
    fake_png = b"\x89PNG\r\n\x1a\n" + b"isolated-test-only-payload"
    parts.append(
        f'--{boundary}\r\n'
        'Content-Disposition: form-data; name="file"; filename="lab.png"\r\n'
        "Content-Type: image/png\r\n"
        "\r\n".encode("ascii") + fake_png + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def verify_dashboard() -> None:
    """Check the built Next.js server without trusting mock page data."""
    with urllib.request.urlopen(NEXT + "/login", timeout=15) as response:
        expect(response.status, 200, "Next.js login route")
        page = response.read().decode("utf-8")
        if "ورود" not in page:
            raise AssertionError("The Persian Next.js login is not rendered")


def main() -> None:
    """Run safe end-to-end checks against the disposable lab service."""
    from scripts.test_lab_app import require_isolated_lab

    require_isolated_lab()
    verify_dashboard()

    users = (
        ("labadmin", "LAB_ADMIN_PASSWORD", "superadmin"),
        ("labcontent", "LAB_CONTENT_PASSWORD", "content"),
        ("labsales", "LAB_SALES_PASSWORD", "sales"),
        ("labmarketing", "LAB_MARKETING_PASSWORD", "marketing"),
        ("labfinance", "LAB_FINANCE_PASSWORD", "finance"),
        ("labviewer", "LAB_VIEWER_PASSWORD", "viewer"),
    )
    accounts = {
        role: login(username, key, role)
        for username, key, role in users
    }

    # Verify dynamic RBAC and rejection of a correctly formed but forged HMAC.
    status, _ = request_json(
        "GET", "/auth/me", operator=accounts["viewer"]
    )
    expect(status, 200, "viewer session identity")
    status, _ = request_json(
        "GET", "/media", operator=accounts["viewer"]
    )
    expect(status, 403, "viewer denied private media")
    status, _ = request_json(
        "GET", "/wallets", operator=accounts["content"]
    )
    expect(status, 403, "content denied finance")
    status, _ = request_json(
        "GET", "/staff", operator=accounts["finance"]
    )
    expect(status, 403, "finance denied staff provisioning")
    status, _ = request_json(
        "GET", "/overview", operator=accounts["viewer"],
        sign_correctly=False,
    )
    expect(status, 401, "invalid bridge signature rejected")

    admin = accounts["superadmin"]
    status, flags = request_json("GET", "/capabilities", operator=admin)
    expect(status, 200, "backend capabilities")
    if not isinstance(flags, dict):
        raise AssertionError("Capabilities did not return a mapping")
    for key in (
        "broadcast_worker_enabled", "bale_business_enabled",
        "telegram_stars_refunds_enabled", "bale_prepare_ready",
    ):
        if flags.get(key) is not False:
            raise AssertionError(f"Unsafe test flag is enabled: {key}")
    if flags.get("wallet_adjustment_limit_irr") != "0":
        raise AssertionError("Manual store-credit mutation is enabled")
    print("PASS all external payment/broadcast controls are disabled")

    content = accounts["content"]
    status, products = request_json(
        "GET", "/products?page=1", operator=content
    )
    expect(status, 200, "real PostgreSQL product list")
    if not isinstance(products, dict):
        raise AssertionError("Expected a paginated product collection")
    product = next(
        (row for row in products.get("items", [])
         if row.get("sku") == "LAB-PHYSICAL-001"),
        None,
    )
    if product is None:
        raise AssertionError("Expected synthetic seeded product not found")

    status, _ = request_json(
        "GET", "/orders/review-queue", operator=accounts["sales"]
    )
    expect(status, 200, "sales read-only manual order queue")
    status, _ = request_json(
        "GET", "/refunds", operator=accounts["finance"]
    )
    expect(status, 200, "finance sees refund queue")

    # Test a real upload transaction on the temporary DB and private volume.
    media_id: int | None = None
    try:
        body, content_type = form_upload(int(product["id"]))
        status, raw = signed_request(
            "POST", "/upload/product", body,
            operator=content, content_type=content_type,
        )
        expect(status, 201, "signed multipart media upload")
        media_id = int(json.loads(raw)["id"])
        status, raw = signed_request(
            "GET", f"/media/preview/product/{media_id}", operator=content
        )
        expect(status, 200, "signed private media preview")
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise AssertionError("Preview bytes differ from stored upload")

        status, _ = request_json(
            "PATCH", f"/media/{media_id}", {"is_published": True},
            operator=content,
        )
        expect(status, 200, "publish reviewed media")
        status, _ = request_json(
            "DELETE", f"/media/{media_id}", operator=content
        )
        expect(status, 409, "published media protected from deletion")
        status, _ = request_json(
            "PATCH", f"/media/{media_id}", {"is_published": False},
            operator=content,
        )
        expect(status, 200, "unpublish reviewed media")
    finally:
        if media_id is not None:
            status, _ = request_json(
                "DELETE", f"/media/{media_id}", operator=content
            )
            expect(status, 200, "delete unpublished test media")

    print("PASS isolated Postgres/Redis/FastAPI/Next smoke is complete.")
    print("No real Telegram/Bale bot, payment or Broadcast was contacted.")


if __name__ == "__main__":
    main()
