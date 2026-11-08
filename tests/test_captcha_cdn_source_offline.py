"""Offline source guards for optional CAPTCHA and public static-asset CDN.

These tests inspect repository policy only. No network, Docker, provider keys
or administrator credentials are needed.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
NEXT = ROOT / "dashboard-next"


def source(path: Path) -> str:
    """Read a checked-in file as UTF-8 for security regression assertions."""
    return path.read_text(encoding="utf-8")


def test_login_keeps_csrf_and_verifies_captcha_before_credentials() -> None:
    """Never replace existing CSRF checks with a client-only CAPTCHA."""
    route = source(NEXT / "app/api/auth/login/route.ts")
    assert "verifyLoginChallenge(request)" in route
    assert "safeLoginFetchMetadata(request)" in route
    assert "serverCaptchaConfig()" in route
    assert "verifyCaptchaToken(" in route
    assert route.index("verifyCaptchaToken(") < route.index(
        'bridgeFetch<StaffLogin>('
    )
    assert '"captcha_unavailable", 503' in route
    assert '"captcha_failed"' in route
    assert 'verdict === "required" ? 422 : 403' in route
    assert "credentials.captchaToken" in route


def test_browser_never_receives_a_captcha_secret() -> None:
    """Only public site keys are transmitted to the login client."""
    config = source(NEXT / "lib/captcha-config.ts")
    widget = source(NEXT / "components/blocks/captcha-challenge.tsx")
    login = source(NEXT / "app/(auth)/login/page.tsx")
    assert "publicCaptchaConfig()" in login
    assert 'provider === "none" ? { provider } : { provider, siteKey }' in config
    assert "secretKey: process.env.NEXT_PUBLIC_" not in config
    assert "CAPTCHA_SECRET_KEY" not in widget
    assert "CAPTCHA_SECRET_KEY" not in login
    assert "captcha_unavailable" in widget


def test_cdn_is_opt_in_and_excludes_private_media() -> None:
    """No CDN should be required to start the dashboard or log in."""
    config = source(NEXT / "next.config.ts")
    compose = source(ROOT / "compose.codespaces.yml")
    preview = source(NEXT / "app/api/admin/preview/[kind]/[id]/route.ts")
    assert "assetPrefix: assetCdnOrigin()" in config
    assert 'process.env.NODE_ENV === "development"' in config
    assert '"https:"' in config
    assert "LIVE_ADMIN_CDN_URL:-" in compose
    assert '"Cache-Control": "private, no-store"' in preview
    assert "readSession()" in preview


def test_provider_choice_defaults_to_disabled_without_silent_bypass() -> None:
    """Enabled but broken settings must fail closed instead of switching off."""
    config = source(NEXT / "lib/captcha-config.ts")
    server = source(NEXT / "lib/captcha-verification.ts")
    assert '"none").trim()' in config
    assert 'throw new Error("Invalid CAPTCHA provider configuration.")' in config
    assert '"unavailable"' in config
    assert 'if (config.provider === "none") return "ok"' in server
    assert 'result.hostname !== config.expectedHostname' in server
    assert 'result.action !== "login"' in server
    assert "AbortSignal.timeout(8_000)" in server
