"""Wrap the existing Codespaces CLI with persistent security-key provisioning.

Only init/start/bootstrap generate a missing encryption key; an existing key
is never rotated. Tokens and passwords are not printed by this wrapper.
"""
from __future__ import annotations

import base64
import os
import secrets
import sys


def provision_key(setup) -> None:
    """Persist a dedicated 256-bit MFA encryption key in the private env file."""
    data = setup.read_env()
    value = data.get("LIVE_SECURITY_ENCRYPTION_KEY", "")
    if not value:
        data["LIVE_SECURITY_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
        setup.write_env(data)
        print("Persistent MFA encryption key initialized. Back up the private environment file securely.")
        return
    try:
        valid = len(base64.b64decode(value, altchars=b"-_", validate=True)) == 32
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise RuntimeError("Existing MFA encryption key is invalid; refusing to replace it")


def main() -> int:
    """Delegate normal lifecycle commands and retire untracked receiver changes."""
    from scripts import codespace_setup as setup
    command = sys.argv[1] if len(sys.argv) > 1 else "info"
    if command in {"init", "start", "config"}:
        if not setup.ENV_FILE.exists():
            if command == "init":
                setup.init()
                provision_key(setup)
                return 0
            raise RuntimeError("Run setup init before starting")
        provision_key(setup)
    # Preserve plaintext build diagnostics without deprecated COMPOSE_BAKE=false.
    os.environ.setdefault("BUILDKIT_PROGRESS", "plain")
    return setup.main()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError) as error:
        print(f"Security setup: {error}", file=sys.stderr)
        sys.exit(1)
