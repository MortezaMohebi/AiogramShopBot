"""Check the real Next.js login and CSRF behavior inside a running Codespace.

No administrator password, production identity or provider credential is read.
Tests only an invalid, randomly named staff account on localhost. Its expected
401 response proves the request reached FastAPI instead of failing at Origin.
"""

from __future__ import annotations

import json
import secrets
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPHandler,
    ProxyHandler,
    Request,
    build_opener,
)


BASE_URL = "http://127.0.0.1:3000"
OPENER = build_opener(ProxyHandler({}), HTTPHandler())


def json_request(
    path: str,
    *,
    payload: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict, list[str]]:
    """Return a bounded local HTTP result without leaking credentials."""
    is_post = payload is not None
    body = json.dumps(payload).encode("utf-8") if is_post else None
    request = Request(
        BASE_URL + path,
        data=body,
        method="POST" if is_post else "GET",
        headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if is_post else {}),
            **(headers or {}),
        },
    )
    try:
        response = OPENER.open(request, timeout=12)
    except HTTPError as error:
        response = error
    with response:
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            raise RuntimeError(
                "Next.js returned non-JSON. Check Codespaces forwarding "
                "and the dashboard container before testing credentials."
            )
        # Keep body bounded: never print tokens or backend response contents.
        value = json.loads(response.read(8192))
        if not isinstance(value, dict):
            raise RuntimeError("Unexpected login response structure.")
        cookies = response.headers.get_all("Set-Cookie") or []
        return response.status, value, cookies


def assert_result(status: int, body: dict, code: str) -> None:
    """Verify an exact expected failure code without echoing private data."""
    if body.get("code") != code:
        raise RuntimeError(
            "Unexpected authentication result: "
            f"HTTP {status} / expected code {code}."
        )


def main() -> None:
    """Validate login navigation, CSRF rejection and proxy-safe credential flow."""
    empty = {
        "username": "smoke_" + secrets.token_hex(12),
        "password": secrets.token_urlsafe(20),
    }

    # A cross-site or stale direct POST cannot bypass the challenge.
    status, body, _ = json_request(
        "/api/auth/login",
        payload=empty,
        headers={"Sec-Fetch-Site": "same-origin", "Origin": "null"},
    )
    if status != 403:
        raise RuntimeError("Missing CSRF token was not rejected.")
    assert_result(status, body, "security_check_failed")
    print("PASS: direct login POST rejected safely with JSON 403.")

    status, body, cookies = json_request(
        "/api/auth/challenge",
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    if status != 200:
        raise RuntimeError("Login challenge endpoint is unavailable.")
    token = body.get("challenge")
    if (
        not isinstance(token, str)
        or len(token) != 43
        or not cookies
    ):
        raise RuntimeError("Login CSRF challenge/cookie was not issued.")
    cookie = next(
        (
            entry.split(";", 1)[0]
            for entry in cookies
            if "shop_login_challenge" in entry
        ),
        None,
    )
    if not cookie:
        raise RuntimeError("Expected host-only login challenge cookie is missing.")
    print("PASS: random host-only login challenge issued.")

    # This test emulates the null Origin observed with privacy proxies while
    # proving that a legitimate challenge reaches the real Python backend.
    status, body, _ = json_request(
        "/api/auth/login",
        payload=empty,
        headers={
            "Sec-Fetch-Site": "same-origin",
            "Origin": "null",
            "X-Shop-Login-Challenge": token,
            "Cookie": cookie,
        },
    )
    if status != 401:
        raise RuntimeError(
            "Login did not reach the backend: expected 401 for a nonexistent "
            f"account, received HTTP {status}."
        )
    assert_result(status, body, "invalid_credentials")
    print("PASS: valid CSRF challenge reached FastAPI (expected 401).")
    print("Login smoke PASSED. No real admin credentials or bot APIs were used.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, URLError, TimeoutError) as error:
        raise SystemExit(
            "Auth smoke failed: "
            + str(error).replace(BASE_URL, "local dashboard")
        ) from None
