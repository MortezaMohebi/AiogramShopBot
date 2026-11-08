"""Purpose-isolated, authenticated at-rest encryption for one-time licenses.

The private secret value is never exposed in API responses, dashboards,
errors, or logs. Ciphertext is bound to exact Store+Product IDs. Bot
identity is checked separately at payment/delivery.
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


def _license_key(store_id: str, product_id: int) -> bytes:
    """Derive an isolated AES/HMAC Fernet key from the deployment root secret."""
    raw = os.environ.get("SHOP_SECURITY_ENCRYPTION_KEY", "")
    try:
        secret = base64.urlsafe_b64decode(raw.encode("ascii"))
    except (ValueError, UnicodeError, binascii.Error):
        raise DeliveryPolicyError("Digital license encryption key unavailable.") from None
    if len(secret) != 32 or not store_id or type(product_id) is not int:
        raise DeliveryPolicyError("Invalid digital-license encryption context.")
    return hmac.new(
        secret,
        f"shop-digital-license-v1:{store_id}:{product_id}".encode("ascii"),
        hashlib.sha256,
    ).digest()


def seal_license(
    *, store_id: str, product_id: int, code: str,
) -> tuple[str, str]:
    """Return encrypted value and purpose-keyed fingerprint, never plaintext."""
    value = validate_license_code(code)
    key = _license_key(store_id, product_id)
    payload = json.dumps(
        {"schema": 1, "store_id": store_id, "product_id": product_id,
         "code": value},
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    token = Fernet(base64.urlsafe_b64encode(key)).encrypt(payload)
    digest = hmac.new(
        key, value.encode("utf-8"), hashlib.sha256,
    ).hexdigest()
    return token.decode("ascii"), digest


def unseal_license(
    *, store_id: str, product_id: int, ciphertext: str,
) -> str:
    """Decrypt only the correct Store/product's authenticated license."""
    try:
        key = _license_key(store_id, product_id)
        clear = Fernet(base64.urlsafe_b64encode(key)).decrypt(
            ciphertext.encode("ascii"),
        )
        obj = json.loads(clear)
        if (
            obj.get("schema") != 1 or obj.get("store_id") != store_id
            or obj.get("product_id") != product_id
        ):
            raise DeliveryPolicyError("License binding does not match.")
        return validate_license_code(obj["code"])
    except (
        ValueError, UnicodeError, KeyError, InvalidToken, TypeError,
        json.JSONDecodeError,
    ):
        raise DeliveryPolicyError("Digital license cannot be decrypted.") from None
