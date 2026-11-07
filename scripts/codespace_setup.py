"""Secure one-command Docker Compose setup for GitHub Codespaces.

Creates isolated service secrets and a private dashboard without accounts.
First owner setup, Bot registration and receiver changes belong to
the authenticated Bot Registry dashboard. Uses no third-party Python
dependencies on the Codespace host.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
PRIVATE_DIR = ROOT / ".codespaces"
ENV_FILE = PRIVATE_DIR / "live.env"
COMPOSE_FILE = ROOT / "compose.codespaces.yml"
PROJECT = "telegram-bale-codespace"
CODESPACE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{2,100}$")
DOMAIN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.-]{2,200}$")


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

    data = {
        "LIVE_WEBHOOK_BASE": webhook,
        "LIVE_DASHBOARD_ORIGIN": dashboard,
        "LIVE_POSTGRES_PASSWORD": secrets.token_hex(24),
        "LIVE_REDIS_PASSWORD": secrets.token_hex(24),
        "LIVE_BRIDGE_SECRET": secrets.token_hex(32),
        "LIVE_SESSION_SECRET": secrets.token_hex(32),
        "LIVE_SECURITY_ENCRYPTION_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode("ascii"),
        "LIVE_WORKFLOW_RUNTIME_ENABLED": "false",
        "LIVE_WORKFLOW_RUNTIME_KILL_SWITCH": "false",
        "LIVE_TELEGRAM_PROXY_ALLOWED_ENDPOINTS": "",
        "LIVE_TELEGRAM_WORKER_ALLOWED_ORIGINS": "",
        # Optional CAPTCHA/CDN stay off unless the owner configures them.
        "LIVE_ADMIN_CAPTCHA_PROVIDER": "none",
        "LIVE_ADMIN_CAPTCHA_SITE_KEY": "",
        "LIVE_ADMIN_CAPTCHA_SECRET_KEY": "",
        "LIVE_ADMIN_RECAPTCHA_V3_MIN_SCORE": "0.5",
        "LIVE_ADMIN_CDN_URL": "",
    }
    write_env(data)
    print("Codespaces service secrets created (mode 0600); no bots registered.")
    show_urls(data)
    print("After start, run 'python3 scripts/codespace_setup.py owner-setup-code' for browser setup.")


def show_urls(data: dict[str, str]) -> None:
    """Print safe URLs without leaking embedded webhook secrets."""
    print("Dashboard (keep Codespaces port 3000 PRIVATE):")
    print(data["LIVE_DASHBOARD_ORIGIN"] + "/login")
    print("Registry webhook ingress (port 8080 remains PRIVATE by default):")
    print(data["LIVE_WEBHOOK_BASE"])
    print("Register bot credentials through Dashboard > Bots after login.")


def configure_smtp() -> None:
    """Store optional TLS-only SMTP credentials in the private owner file."""
    from services.shop_smtp import configured_settings

    data = read_env()
    host = input("SMTP host: ").strip()
    port = input("SMTP port: ").strip()
    security = input("TLS mode (ssl/starttls): ").strip().lower()
    username = input("SMTP username: ").strip()
    sender = input("Sender email: ").strip()
    password = getpass.getpass("SMTP password: ")
    proposed = dict(zip(
        ("HOST", "PORT", "SECURITY", "USERNAME", "SENDER", "PASSWORD_B64"),
        (host, port, security, username, sender,
         base64.b64encode(password.encode("utf-8")).decode("ascii")),
    ))
    previous = {key: os.environ.get("SHOP_SMTP_" + key) for key in proposed}
    try:
        os.environ.update({"SHOP_SMTP_" + key: value for key, value in proposed.items()})
        if configured_settings() is None:
            raise ValueError("SMTP configuration is incomplete.")
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop("SHOP_SMTP_" + key, None)
            else:
                os.environ["SHOP_SMTP_" + key] = value
    data.update({"LIVE_SMTP_" + key: value for key, value in proposed.items()})
    write_env(data)
    print("SMTP settings saved. Restart application to apply them.")


def test_smtp() -> None:
    """Send one diagnostic message to an explicitly entered address."""
    from services.shop_email_templates import render_email
    from services.shop_smtp import configured_settings, send_email

    data = read_env()
    keys = ("HOST", "PORT", "SECURITY", "USERNAME", "SENDER", "PASSWORD_B64")
    previous = {key: os.environ.get("SHOP_SMTP_" + key) for key in keys}
    try:
        for key in keys:
            value = data.get("LIVE_SMTP_" + key)
            if value is None:
                os.environ.pop("SHOP_SMTP_" + key, None)
            else:
                os.environ["SHOP_SMTP_" + key] = value
        settings = configured_settings()
        if settings is None:
            raise RuntimeError("Configure SMTP before sending a test message.")
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop("SHOP_SMTP_" + key, None)
            else:
                os.environ["SHOP_SMTP_" + key] = value
    destination = input("Test recipient email: ").strip()
    send_email(settings, destination, render_email("smtp_test", recipient=destination))
    print("SMTP test message accepted by the configured server.")


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


def set_ports() -> None:
    """Keep both forwarded ports private; provider ingress is a separate cutover."""
    try:
        result = subprocess.run(
            ["gh", "codespace", "ports", "visibility",
             "8080:private", "3000:private", "-c", codespace_name()],
            timeout=20, check=False,
        )
        if result.returncode == 0:
            return
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    print("Keep Codespaces ports 3000 and 8080 Private in the PORTS panel.")


def doctor() -> int:
    """Check local application health without contacting messaging providers."""
    return compose(
        "exec", "-T", "app", "python", "-c",
        "from urllib.request import urlopen; "
        "assert urlopen('http://127.0.0.1:5000/healthz', timeout=5).status == 200; "
        "print('Registry application health verified')",
    )


def main() -> int:
    """Provide repeatable setup, QA and teardown without shell interpolation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "info", "init", "config", "start", "build-dashboard", "ports",
            "doctor", "auth-smoke", "dashboard-probe", "owner-setup",
            "owner-setup-code", "smtp-config", "smtp-test", "demo", "status", "logs", "test",
            "stop", "reset",
        ),
        nargs="?",
        default="info",
    )
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if args.command == "info":
        print("Private Codespaces Registry setup:")
        print("  python3 scripts/codespace_setup.py init")
        print("  python3 scripts/codespace_setup.py start")
        print("  python3 scripts/codespace_setup.py build-dashboard")
        print("  python3 scripts/codespace_setup.py ports")
        print("  python3 scripts/codespace_setup.py doctor")
        print("  python3 scripts/codespace_setup.py auth-smoke")
        print("  python3 scripts/codespace_setup.py dashboard-probe")
        print("  python3 scripts/codespace_setup.py owner-setup")
        print("  python3 scripts/codespace_setup.py owner-setup-code")
        print("  python3 scripts/codespace_setup.py smtp-config")
        print("  python3 scripts/codespace_setup.py smtp-test")
        print("  python3 scripts/codespace_setup.py demo")
        return 0
    if args.command == "init":
        init()
        return 0
    if args.command == "owner-setup":
        return compose("run", "--rm", "--no-deps", "app", "python", "-m", "scripts.first_owner_setup")
    if args.command == "owner-setup-code":
        return compose(
            "exec", "-T", "app", "python", "-m",
            "scripts.first_owner_setup", "--browser-code",
        )
    if args.command == "smtp-config":
        configure_smtp()
        return 0
    if args.command == "smtp-test":
        test_smtp()
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
            print("Services started with zero new bots. Register through Dashboard > Bots.")
            print("For first-run browser setup, get your code with owner-setup-code.")
        return code
    if args.command == "ports":
        set_ports()
        return 0
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
    if args.command == "dashboard-probe":
        # Only reads database and signed admin API; never checks real payments.
        return compose(
            "exec", "-T", "app", "python", "-m",
            "scripts.codespace_dashboard_probe",
        )
    if args.command == "doctor":
        return doctor()
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
