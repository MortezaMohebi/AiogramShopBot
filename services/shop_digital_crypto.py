"""Purpose-separated authenticated encryption for merchant digital licenses.

Encrypted license text is bound to its Store and Asset ID. A cryptographic
HMAC fingerprint prevents reusing a license in a Store without exposing the
original code to database administrators, logs or customer export files.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os

from cryptography.fernet import Fernet, InvalidToken

from services.shop_digital_rules import (
    DeliveryPolicyError, validate_license_code,
)

_CONTEXT = b"aiogramshopbot:digital-license:fernet:v1"


def _secret() -> bytes:
    """Resolve a 256-bit deployment secret without creating a weak default."""
    raw = (
        os.environ.get("SHOP_DIGITAL_LICENSE_SECRET_KEY")
        or os.environ.get("SHOP_SECURITY_ENCRYPTION_KEY", "")
    )
    try:
        result = base64.urlsafe_b64decode(raw.encode("ascii"))
    except (UnicodeError, binascii.Error, ValueError):
        raise DeliveryPolicyError("License encryption key is unavailable.") from None
    if len(result) != 32:
        raise DeliveryPolicyError("License encryption key is unavailable.")
    return result


def _fernet() -> Fernet:
    """Derive a different key from payment and Bot secret encryption keys."""
    key = hmac.new(_secret(), _CONTEXT, hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_license(
    *, store_id: str, asset_id: int, value: str,
) -> tuple[str, str]:
    """Encrypt one code with authenticated Store/Asset ownership metadata."""
    code = validate_license_code(value)
    if not store_id or type(asset_id) is not int or asset_id <= 0:
        raise DeliveryPolicyError("Invalid digital license owner.")
    document = json.dumps({
        "version": 1, "store": store_id,
        "asset": asset_id, "code": code,
    }, ensure_ascii=False, separators=(",", ":"))
    encrypted = _fernet().encrypt(document.encode("utf-8")).decode("ascii")
    fingerprint = hmac.new(
        _secret(),
        ("digital-license-fingerprint:v1:" + store_id + ":" + code).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return encrypted, fingerprint


def decrypt_license(
    *, store_id: str, asset_id: int, ciphertext: str,
) -> str:
    """Unseal a code only for its original Store and immutable Asset."""
    try:
        record = json.loads(_fernet().decrypt(
            ciphertext.encode("ascii")
        ))
    except (InvalidToken, ValueError, UnicodeError, TypeError):
        raise DeliveryPolicyError("Digital license authentication failed.") from None
    if (
        not isinstance(record, dict)
        or record.get("version") != 1
        or record.get("store") != store_id
        or record.get("asset") != asset_id
    ):
        raise DeliveryPolicyError("Digital license Store/Asset mismatch.")
    return validate_license_code(record.get("code"))
