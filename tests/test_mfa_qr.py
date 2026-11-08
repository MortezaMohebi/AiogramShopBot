"""Validate offline QR enrollment for authenticator applications."""

from __future__ import annotations

import base64
from io import BytesIO
from urllib.parse import parse_qs, unquote, urlsplit

from PIL import Image
import pytest

from services.shop_mfa_qr import make_mfa_qr_data_uri, make_otpauth_uri


@pytest.fixture

def example_secret() -> str:
    """Supply a deterministic RFC 4648 Base32 seed without user data."""
    return "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def test_otpauth_uri_is_standard_and_escapes_username(example_secret: str) -> None:
    """Authenticator payload must contain a valid issuer, period and digits."""
    uri = make_otpauth_uri(example_secret, "user.name+test@example.com")
    parsed = urlsplit(uri)
    params = parse_qs(parsed.query)

    assert parsed.scheme == "otpauth"
    assert parsed.netloc == "totp"
    assert unquote(parsed.path).startswith("/Shop Admin:")
    assert unquote(parsed.path).endswith("user.name+test@example.com")
    assert params == {
        "secret": [example_secret],
        "issuer": ["Shop Admin"],
        "algorithm": ["SHA1"],
        "digits": ["6"],
        "period": ["30"],
    }


def test_qr_is_a_local_png_image(example_secret: str) -> None:
    """The server must return an offline generated image, not an API URL."""
    uri = make_otpauth_uri(example_secret, "operator")
    image_uri = make_mfa_qr_data_uri(uri)
    assert image_uri.startswith("data:image/png;base64,")
    assert "http" not in image_uri

    raw = base64.b64decode(image_uri.removeprefix("data:image/png;base64,"))
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(raw)) as qr:
        assert qr.format == "PNG"
        assert qr.width >= 180
        assert qr.height >= 180
        assert qr.width == qr.height
        assert qr.getpixel((0, 0)) in (255, (255, 255), (255, 255, 255))


@pytest.mark.parametrize("value", ["", "not base32?!", "abc", "A" * 256])
def test_invalid_totp_secrets_are_rejected(value: str) -> None:
    """Never generate invalid setup QR codes from malformed secrets."""
    with pytest.raises(ValueError):
        make_otpauth_uri(value, "operator")


def test_mfa_enrollment_api_and_wizard_use_private_qr_data() -> None:
    """Keep provisioning QR local and the manual secret behind disclosure."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    api = (root / "dashboard/admin_control_api.py").read_text("utf-8")
    wizard = (root / "dashboard-next/components/blocks/account-security-wizard.tsx").read_text(
        "utf-8"
    )
    types = (root / "dashboard-next/lib/account-control.ts").read_text("utf-8")

    assert "make_otpauth_uri(secret, member.username)" in api
    assert "make_mfa_qr_data_uri(uri)" in api
    assert '"qr_data_uri"' in api
    assert "qr_data_uri?: string" in types
    assert "<Image src={step.qr}" in wizard
    disclosure = wizard.split("<details", 1)[1].split("</details>", 1)[0]
    assert "{step.secret}" in disclosure
