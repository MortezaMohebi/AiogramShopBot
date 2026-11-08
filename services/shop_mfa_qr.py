"""Generate standard TOTP enrollment QR images entirely inside the application.

The enrollment seed is sensitive and must never be sent to third-party QR
services or included in application logs. The output is an ephemeral PNG data
URI for a single authenticated browser response.
"""

from __future__ import annotations

import base64
from io import BytesIO
import re
from urllib.parse import quote

import qrcode

ISSUER = "Shop Admin"
_BASE32_160_BITS = re.compile(r"^[A-Z2-7]{32}$")


def make_otpauth_uri(secret: str, username: str) -> str:
    """Create an RFC 6238 enrollment URI accepted by authenticator apps.

    Args:
        secret: Valid 160-bit Base32 TOTP secret from MFA enrollment.
        username: Staff account label shown inside an authenticator app.

    Returns:
        A percent-encoded ``otpauth://totp`` URI.

    Raises:
        ValueError: If the secret or username cannot be represented safely.
    """
    if not isinstance(secret, str) or not _BASE32_160_BITS.fullmatch(secret):
        raise ValueError("Invalid TOTP enrollment secret")
    if (
        not isinstance(username, str)
        or not 1 <= len(username) <= 120
        or any(ord(character) < 32 for character in username)
    ):
        raise ValueError("Invalid TOTP account label")

    label = quote(f"{ISSUER}:{username}", safe="")
    issuer = quote(ISSUER, safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={issuer}"
        "&algorithm=SHA1&digits=6&period=30"
    )


def make_mfa_qr_data_uri(otpauth_uri: str) -> str:
    """Render the enrollment URI to a black-on-white PNG without network I/O.

    Args:
        otpauth_uri: Locally generated TOTP provisioning URI.

    Returns:
        A browser-renderable ``data:image/png;base64,...`` value.

    Raises:
        ValueError: If the input is not a bounded TOTP provisioning URI.
    """
    if (
        not isinstance(otpauth_uri, str)
        or not otpauth_uri.startswith("otpauth://totp/")
        or len(otpauth_uri) > 512
    ):
        raise ValueError("Invalid TOTP QR content")

    code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=4,
    )
    code.add_data(otpauth_uri)
    code.make(fit=True)
    output = BytesIO()
    code.make_image(fill_color="black", back_color="white").save(
        output, format="PNG"
    )
    image_bytes = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/png;base64,{image_bytes}"
