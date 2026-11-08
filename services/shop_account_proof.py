"""Short-lived, session-bound proof for a single account operation."""

import hmac
import re
import time

PROOF_LIFETIME = 180
_TOKEN = re.compile(r"([0-9]{10})\.([a-f0-9]{64})")


def issue(secret: str, session_id: str, version: int, action: str, *, now=None) -> str:
    """Sign proof after the server verifies the current password."""
    timestamp = int(time.time()) if now is None else now
    message = f"account-wizard-v1\n{session_id}\n{version}\n{action}\n{timestamp}"
    return f"{timestamp}.{hmac.digest(secret.encode(), message.encode(), 'sha256').hex()}"


def valid(secret: str, token: str, session_id: str, version: int, action: str, *, now=None) -> bool:
    """Check expiry, action, session and version using a constant-time comparison."""
    match = _TOKEN.fullmatch(token)
    if not match or len(secret) < 32:
        return False
    issued = int(match[1])
    current = int(time.time()) if now is None else now
    return (
        0 <= current - issued < PROOF_LIFETIME
        and hmac.compare_digest(token, issue(secret, session_id, version, action, now=issued))
    )
