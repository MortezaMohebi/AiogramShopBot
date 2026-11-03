"""Secure one-command Docker Compose setup for GitHub Codespaces.

Creates isolated service secrets, a random first administrator password,
provider credentials entered without terminal echo, and provider webhooks
registered only after explicit confirmation. Uses no third-party Python
dependencies on the Codespace host.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent.parent
PRIVATE_DIR = ROOT / ".codespaces"
ENV_FILE = PRIVATE_DIR / "live.env"
COMPOSE_FILE = ROOT / "compose.codespaces.yml"
PROJECT = "telegram-bale-codespace"
CODESPACE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{2,100}$")
DOMAIN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.-]{2,200}$")
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9:_-]{16,256}$")


def codespace_name() -> str:
    """Use the exact Codespace name, never derive a provider URL from Host."""
    name = os.environ.get("CODESPACE_NAME", "").strip()
    if not CODESPACE_RE.fullmatch(name):
        raise RuntimeError(
            "Open this repository in GitHub Codespaces first. "
            "CODESPACE_NAME is missing or invalid."
        )
    return name


def codespace_domain() -> str:
    """Read the current GitHub Codespaces forwarding domain."""
    domain = os.environ.get(
        "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev"
    ).strip().lower()
    if not DOMAIN_RE.fullmatch(domain) or not domain.endswith(
        ".github.dev"
    ):
        raise RuntimeError("Invalid GitHub Codespaces forwarding domain.")
    return domain


def urls() -> tuple[str, str]:
    """Resolve the exact public webhook and private dashboard origins."""
    name, domain = codespace_name(), codespace_domain()
    return (
        f"https://{name}-8080.{domain}",
        f"https://{name}-3000.{domain}",
    )


def read_env() -> dict[str, str]:
    """Read only the generated private key-value file, without shell eval."""
    if ENV_FILE.is_symlink() or not ENV_FILE.is_file():
        raise RuntimeError(
            "Private Codespaces configuration not found. Run 'init'."
        )
    data: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError("Invalid private environment file.")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z0-9_]+", key):
            raise RuntimeError("Invalid private environment key.")
        data[key] = value
    return data


def write_env(data: dict[str, str]) -> None:
    """Atomically store private secrets with owner-only permissions."""
    if PRIVATE_DIR.is_symlink():
        raise RuntimeError("Refusing a symlinked private directory.")
    PRIVATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if ENV_FILE.is_symlink():
        raise RuntimeError("Refusing a symlinked secret file.")
    temp = PRIVATE_DIR / ("live.env." + secrets.token_hex(8) + ".tmp")
    descriptor = os.open(
        temp, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("# Private, Codespaces-only; DO NOT COMMIT.\n")
            for key, value in data.items():
                if not re.fullmatch(r"[A-Z0-9_]+", key):
                    raise RuntimeError("Invalid environment variable.")
                if "\n" in value or "\r" in value or "$" in value:
                    raise RuntimeError("Unsafe environment variable value.")
                handle.write(f"{key}={value}\n")
        os.replace(temp, ENV_FILE)
        os.chmod(ENV_FILE, 0o600)
    finally:
        temp.unlink(missing_ok=True)


def prompt_bot_token(key: str, label: str) -> str:
    """Receive a token through Codespaces Secrets or a hidden prompt."""
    value = os.environ.get(key, "").strip()
    if not value:
        if not sys.stdin.isatty():
            raise RuntimeError(
                f"{key} missing: configure a Codespaces secret or use a TTY."
            )
        value = getpass.getpass(f"{label} token (hidden input): ").strip()
    if SAFE_TOKEN.fullmatch(value) is None:
        raise RuntimeError(f"{label} token format/length is invalid.")
    return value


def init() -> None:
    """Initialize exactly once, without overwriting an existing password."""
    webhook, dashboard = urls()
    if ENV_FILE.exists():
        print("Existing Codespaces credentials preserved (no rotation).")
        data = read_env()
        if (
            data.get("LIVE_WEBHOOK_BASE") != webhook or
            data.get("LIVE_DASHBOARD_ORIGIN") != dashboard
        ):
            raise RuntimeError(
                "Codespace URL changed. Reset the isolated stack and "
                "reinitialize; existing webhooks must be reviewed."
            )
        show_urls(data)
        return

    telegram = prompt_bot_token("TELEGRAM_BOT_TOKEN", "Telegram")
    bale = prompt_bot_token("BALE_BOT_TOKEN", "Bale")
    data = {
        "LIVE_WEBHOOK_BASE": webhook,
        "LIVE_DASHBOARD_ORIGIN": dashboard,
        "LIVE_TELEGRAM_TOKEN": telegram,
        "LIVE_BALE_TOKEN": bale,
        "LIVE_POSTGRES_PASSWORD": secrets.token_hex(24),
        "LIVE_REDIS_PASSWORD": secrets.token_hex(24),
        "LIVE_JWT_SECRET": secrets.token_hex(32),
        "LIVE_BRIDGE_SECRET": secrets.token_hex(32),
        "LIVE_SESSION_SECRET": secrets.token_hex(32),
        "LIVE_TELEGRAM_WEBHOOK_SECRET": secrets.token_urlsafe(32),
        "LIVE_BALE_WEBHOOK_SECRET": secrets.token_urlsafe(36),
        "LIVE_ADMIN_PASSWORD": secrets.token_urlsafe(25),
        "LIVE_TELEGRAM_API_MODE": "direct",
        "LIVE_TELEGRAM_PROXY_URL": "",
        "LIVE_TELEGRAM_WORKER_URL": "",
        "LIVE_TELEGRAM_WORKER_SECRET": "",
        "LIVE_DEFAULT_MEDIA_FILE_ID": "",
        "LIVE_BALE_PAYMENT_TOKEN": "",
        # Optional CAPTCHA/CDN stay off unless the owner configures them.
        "LIVE_ADMIN_CAPTCHA_PROVIDER": "none",
        "LIVE_ADMIN_CAPTCHA_SITE_KEY": "",
        "LIVE_ADMIN_CAPTCHA_SECRET_KEY": "",
        "LIVE_ADMIN_RECAPTCHA_V3_MIN_SCORE": "0.5",
        "LIVE_ADMIN_CDN_URL": "",
    }
    write_env(data)
    print("Codespaces secrets created (mode 0600); real Bot API tokens stored.")
    show_urls(data)
    credentials(data)


def new_bootstrap_password() -> None:
    """Rotate the stored initial password for an administrator not yet created.

    This does NOT change an existing account's database hash. To rotate an
    already-created administrator, use the authenticated /staff dashboard.
    """
    data = read_env()
    data["LIVE_ADMIN_PASSWORD"] = secrets.token_urlsafe(32)
    write_env(data)
    print(
        "A new private bootstrap password was generated for a NEW account. "
        "Existing database accounts were not modified."
    )
    print(
        "If shopadmin already exists, change its password in /staff instead."
    )


def show_urls(data: dict[str, str]) -> None:
    """Print safe URLs without leaking embedded webhook secrets."""
    print("Dashboard (keep Codespaces port 3000 PRIVATE):")
    print(data["LIVE_DASHBOARD_ORIGIN"] + "/login")
    print("Webhook ingress (port 8080 PUBLIC):")
    print(data["LIVE_WEBHOOK_BASE"])
    print("The Bale secret path and all provider tokens are not displayed.")


def credentials(data: dict[str, str]) -> None:
    """Reveal only the first-login password inside the owner's terminal."""
    print("\nInitial dashboard credentials (Codespace owner terminal only):")
    print("  Username: shopadmin")
    print("  Password: " + data["LIVE_ADMIN_PASSWORD"])
    print(
        "This is only the bootstrap password. After changing it in /staff, "
        "the password cannot be recovered here."
    )


def compose(*args: str) -> int:
    """Run the isolated Compose project without loading production .env."""
    if not COMPOSE_FILE.exists():
        raise RuntimeError("compose.codespaces.yml is missing.")
    read_env()
    command = [
        "docker", "compose",
        "--project-name", PROJECT,
        "--env-file", str(ENV_FILE),
        "-f", str(COMPOSE_FILE),
        *args,
    ]
    # Always show raw build logs: compact Bake progress can hide npm errors.
    # Explicitly disable Compose Bake for reproducible Codespaces diagnosis.
    process_env = os.environ.copy()
    if "build" in args:
        process_env["COMPOSE_BAKE"] = "false"
        process_env["BUILDKIT_PROGRESS"] = "plain"
        process_env["COMPOSE_PROGRESS"] = "plain"
    try:
        return subprocess.run(
            command, check=False, cwd=ROOT, env=process_env
        ).returncode
    except FileNotFoundError:
        raise RuntimeError(
            "Docker Compose V2 is missing. Rebuild the devcontainer."
        ) from None


def gh_port_status() -> dict[int, str] | None:
    """Read Codespaces port visibility if the GitHub CLI supports it."""
    try:
        result = subprocess.run(
            [
                "gh", "codespace", "ports",
                "--codespace", codespace_name(),
                "--json", "sourcePort,visibility",
            ],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return {
            int(port["sourcePort"]): str(port["visibility"]).lower()
            for port in json.loads(result.stdout)
        }
    except (ValueError, KeyError, TypeError):
        return None


def port_instructions() -> None:
    """Show explicit visibility instructions without publicizing admin port."""
    print("Codespaces PORTS: make 8080 Public and 3000 Private.")
    print("Or run:")
    print(
        "  gh codespace ports visibility 8080:public 3000:private "
        "-c " + codespace_name()
    )


def check_public_gateway(data: dict[str, str]) -> None:
    """Prove a public webhook gateway is reachable, not GitHub login HTML."""
    status = gh_port_status()
    if status is not None:
        if status.get(3000) == "public":
            raise RuntimeError(
                "Admin port 3000 is PUBLIC. Make it PRIVATE immediately."
            )
        if status.get(8080) != "public":
            port_instructions()
            raise RuntimeError("Webhook port 8080 must be Public.")
    try:
        with urlopen(
            data["LIVE_WEBHOOK_BASE"] + "/_edge/health",
            timeout=10,
        ) as response:
            if response.status != 200 or response.read(100).strip() != b"ready":
                raise RuntimeError(
                    "Webhook tunnel is unavailable or behind GitHub login."
                )
    except (HTTPError, URLError, TimeoutError):
        raise RuntimeError(
            "Public Codespaces webhook gateway unreachable. "
            "Inspect the PORTS panel and Codespace health."
        ) from None


def set_ports() -> None:
    """Prefer GitHub CLI, but never silently make dashboard public."""
    port_instructions()
    try:
        result = subprocess.run(
            [
                "gh", "codespace", "ports", "visibility",
                "8080:public", "3000:private",
                "-c", codespace_name(),
            ],
            timeout=20, check=False,
        )
        if result.returncode != 0:
            print("Set port visibility manually in the Codespaces PORTS tab.")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("GitHub CLI is unavailable; use the Codespaces PORTS tab.")


def connect(*, yes: bool) -> int:
    """Register genuine webhooks only after user approval and public health."""
    data = read_env()
    check_public_gateway(data)
    print(
        "WARNING: Registering a webhook moves BOTH bot tokens' incoming "
        "updates to this Codespace and may disconnect other deployments."
    )
    if not yes:
        if not sys.stdin.isatty():
            raise RuntimeError("Interactive confirmation required; use --yes.")
        answer = input("Type REGISTER to set both real webhooks: ").strip()
        if answer != "REGISTER":
            print("Webhook registration cancelled.")
            return 1
    return compose(
        "exec", "-T", "app", "python", "-m",
        "scripts.codespace_connect", "--register",
    )


def main() -> int:
    """Provide repeatable setup, QA and teardown without shell interpolation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "info", "init", "config", "start", "build-dashboard", "ports", "connect",
            "disconnect",
            "doctor", "auth-smoke", "credentials", "new-bootstrap-password", "demo", "status", "logs", "test",
            "stop", "reset",
        ),
        nargs="?",
        default="info",
    )
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if args.command == "info":
        print("Live Codespaces Telegram+Bale setup:")
        print("  python3 scripts/codespace_setup.py init")
        print("  python3 scripts/codespace_setup.py start")
        print("  python3 scripts/codespace_setup.py build-dashboard")
        print("  python3 scripts/codespace_setup.py ports")
        print("  python3 scripts/codespace_setup.py connect")
        print("  python3 scripts/codespace_setup.py doctor")
        print("  python3 scripts/codespace_setup.py auth-smoke")
        print("  python3 scripts/codespace_setup.py disconnect")
        print("  python3 scripts/codespace_setup.py credentials")
        print("  python3 scripts/codespace_setup.py new-bootstrap-password")
        print("  python3 scripts/codespace_setup.py demo")
        return 0
    if args.command == "init":
        init()
        return 0
    if args.command == "credentials":
        credentials(read_env())
        return 0
    if args.command == "new-bootstrap-password":
        new_bootstrap_password()
        return 0
    if args.command == "config":
        return compose("config", "--quiet")
    if args.command == "build-dashboard":
        # Reuse already-cached npm layers; print which BuildKit stage fails.
        return compose("build", "dashboard")
    if args.command == "start":
        # Build sequentially to avoid exhausting 2-core/8GB Codespaces.
        backend = compose("build", "bootstrap")
        if backend:
            return backend
        frontend = compose("build", "dashboard")
        if frontend:
            return frontend
        code = compose(
            "up", "-d", "--no-build", "--wait", "--remove-orphans"
        )
        if code == 0:
            show_urls(read_env())
            print("Services started. Run 'ports', then 'connect' to register.")
        return code
    if args.command == "ports":
        set_ports()
        return 0
    if args.command == "connect":
        return connect(yes=args.yes)
    if args.command == "disconnect":
        if not args.yes:
            if not sys.stdin.isatty():
                raise RuntimeError("Type DISCONNECT interactively or pass --yes.")
            print("Only callbacks currently targeting this Codespace may be removed.")
            if input("Type DISCONNECT to unregister webhooks: ").strip() != "DISCONNECT":
                return 1
        return compose(
            "exec", "-T", "app", "python", "-m",
            "scripts.codespace_connect", "--unregister",
        )
    if args.command == "demo":
        return compose(
            "exec", "-T", "app", "python", "-m", "scripts.codespace_demo"
        )
    if args.command == "auth-smoke":
        # This test does not read private credentials, contact providers or
        # require a public Codespaces port; it calls loopback Next.js only.
        return subprocess.run(
            [sys.executable, "-m", "scripts.codespace_auth_smoke"],
            cwd=ROOT, check=False,
        ).returncode
    if args.command == "doctor":
        code = compose(
            "exec", "-T", "app", "python", "-m", "scripts.codespace_connect"
        )
        if code == 0:
            print("API diagnostics passed (no message or payment sent).")
        return code
    if args.command == "status":
        return compose("ps", "-a")
    if args.command == "logs":
        return compose("logs", "--tail=120", "-f", "app", "dashboard")
    if args.command == "test":
        return compose("--profile", "qa", "run", "--rm", "pytest")
    if args.command == "stop":
        return compose("down", "--remove-orphans")
    if args.command == "reset":
        if not args.yes:
            raise RuntimeError(
                "Deleting Codespace volumes requires reset --yes."
            )
        return compose("down", "--volumes", "--remove-orphans")
    raise RuntimeError("Unsupported action.")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError) as error:
        print(f"Codespace setup: {error}", file=sys.stderr)
        sys.exit(1)
