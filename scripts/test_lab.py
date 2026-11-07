"""Manage an isolated Docker Compose lab without using production .env.

The lab has its own project name, generated credentials, named volumes,
localhost HTTPS endpoint and explicit deletion confirmation. The actual
Telegram/Bale webhook and payment services are never started.
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env.test.local"
COMPOSE_PATH = ROOT / "compose.test.yml"
ROLES = ("ADMIN", "CONTENT", "SALES", "MARKETING", "FINANCE", "VIEWER")


def create_lab_environment() -> None:
    """Create test-only secrets once, atomically and with private permissions."""
    if ENV_PATH.exists() or ENV_PATH.is_symlink():
        print(f"Existing lab secrets preserved: {ENV_PATH.name}")
        return

    secrets_by_name = {
        "LAB_POSTGRES_PASSWORD": secrets.token_hex(24),
        "LAB_REDIS_PASSWORD": secrets.token_hex(24),
        "LAB_BRIDGE_SECRET": secrets.token_hex(32),
        "LAB_SESSION_SECRET": secrets.token_hex(32),
        "LAB_SECURITY_ENCRYPTION_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode("ascii"),
    }
    for role in ROLES:
        secrets_by_name[f"LAB_{role}_PASSWORD"] = secrets.token_urlsafe(28)

    # O_EXCL prevents replacing existing/linked files, including via races.
    descriptor = os.open(
        ENV_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            destination.write(
                "# Disposable local test credentials. NEVER use on real bots.\n"
            )
            for key, value in secrets_by_name.items():
                destination.write(f"{key}={value}\n")
        if os.name == "posix":
            ENV_PATH.chmod(0o600)
    except BaseException:
        ENV_PATH.unlink(missing_ok=True)
        raise

    print(f"Created {ENV_PATH.name} with private, unique lab credentials.")
    print("Lab staff: labadmin, labcontent, labsales, labmarketing, "
          "labfinance, labviewer.")
    print("Passwords are in the local ignored file; none were logged.")


def compose(*arguments: str) -> int:
    """Run only the dedicated compose file with its private test env file."""
    if not COMPOSE_PATH.is_file() or not ENV_PATH.is_file():
        raise RuntimeError(
            "Test Compose or its environment is missing; run 'init' first."
        )
    command = [
        "docker", "compose",
        "--project-name", "dual-messenger-shop-lab",
        "--env-file", str(ENV_PATH),
        "-f", str(COMPOSE_PATH),
        *arguments,
    ]
    try:
        return subprocess.run(command, cwd=ROOT, check=False).returncode
    except FileNotFoundError:
        raise RuntimeError(
            "Docker Compose V2 is required; Docker is not available here."
        ) from None


def main() -> int:
    """Dispatch explicit lifecycle commands without touching production."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("init", "config", "up", "test", "smoke", "browser", "logs",
                 "status", "down", "reset"),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Explicitly allow deleting ONLY named test volumes with reset.",
    )
    args = parser.parse_args()
    if args.command == "init":
        create_lab_environment()
        return 0
    if args.command == "up" and not ENV_PATH.exists():
        create_lab_environment()
    if args.command == "reset" and not args.yes:
        parser.error(
            "Reset deletes isolated test DB, media and CA. Pass --yes."
        )

    commands = {
        "config": ("config", "--quiet"),
        "up": ("up", "--build", "-d"),
        "smoke": ("--profile", "qa", "run", "--rm", "smoke"),
        "browser": ("--profile", "browser", "run", "--rm", "browser"),
        "logs": ("logs", "--tail=200", "-f"),
        "status": ("ps", "-a"),
        "down": ("down", "--remove-orphans"),
        "reset": ("down", "--remove-orphans", "--volumes"),
    }
    if args.command == "test":
        # Always run integration smoke after unit tests so both failures
        # are visible while preserving a nonzero final status.
        unit = compose("--profile", "qa", "run", "--rm", "pytest")
        smoke = compose("--profile", "qa", "run", "--rm", "smoke")
        return 1 if unit or smoke else 0
    return compose(*commands[args.command])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError) as error:
        print(f"Lab command error: {error}", file=sys.stderr)
        sys.exit(1)
