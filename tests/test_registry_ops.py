"""Keep deployment credentials, ingress and isolated QA on Registry boundaries."""

from __future__ import annotations

import base64
from pathlib import Path
import re
import sys

import pytest

from scripts import codespace_setup

ROOT = Path(__file__).resolve().parents[1]


def test_codespaces_init_needs_no_provider_credentials(tmp_path, monkeypatch):
    """Fresh setup creates service keys and no environment-owned bot secrets."""
    monkeypatch.setenv("CODESPACE_NAME", "safe-registry-test")
    monkeypatch.setattr(codespace_setup, "PRIVATE_DIR", tmp_path)
    monkeypatch.setattr(codespace_setup, "ENV_FILE", tmp_path / "live.env")
    codespace_setup.init()
    values = codespace_setup.read_env()
    assert len(base64.urlsafe_b64decode(values["LIVE_SECURITY_ENCRYPTION_KEY"])) == 32
    assert len(values["LIVE_BRIDGE_SECRET"]) >= 32
    assert not any(key in values for key in (
        "LIVE_TELEGRAM_TOKEN", "LIVE_BALE_TOKEN", "LIVE_JWT_SECRET",
        "LIVE_TELEGRAM_UPDATE_MODE", "LIVE_TELEGRAM_API_MODE",
        "LIVE_TELEGRAM_PROXY_URL", "LIVE_TELEGRAM_WORKER_URL",
        "LIVE_TELEGRAM_WORKER_SECRET", "LIVE_BALE_PAYMENT_TOKEN",
    ))
    original = codespace_setup.ENV_FILE.read_bytes()
    codespace_setup.init()
    assert codespace_setup.ENV_FILE.read_bytes() == original


@pytest.mark.parametrize("command", ["connect", "disconnect", "apply-bot-mode"])
def test_retired_commands_cannot_contact_providers(command, monkeypatch):
    """Old lifecycle commands fail argument validation before any operation."""
    monkeypatch.setattr(sys, "argv", ["codespace_setup.py", command])
    with pytest.raises(SystemExit) as result:
        codespace_setup.main()
    assert result.value.code == 2


def test_port_setup_keeps_both_surfaces_private(monkeypatch):
    """The lifecycle CLI never makes an existing Codespace surface public."""
    from types import SimpleNamespace

    commands = []
    monkeypatch.setenv("CODESPACE_NAME", "safe-registry-test")
    monkeypatch.setattr(codespace_setup.subprocess, "run", lambda command, **kw: (
        commands.append(command) or SimpleNamespace(returncode=0)
    ))
    codespace_setup.set_ports()
    assert commands[0][4:6] == ["8080:private", "3000:private"]


def test_gateway_only_accepts_bounded_registry_callback_paths():
    """The edge cannot forward administration, old routes or oversized secrets."""
    nginx = (ROOT / "deploy/codespaces/nginx.conf").read_text()
    pattern = re.search(r'location ~ "([^"]+)"', nginx).group(1)
    valid = "/webhooks/v2/00000000-0000-4000-8000-000000000001/" + "a" * 43
    assert re.fullmatch(pattern, valid)
    for path in (
        "/admin", "/internal/admin/v1/auth/login", "/hooks/telegram",
        "/webhooks/bale/" + "a" * 43, valid + "/admin", valid + "a",
    ):
        assert re.fullmatch(pattern, path) is None
    assert "limit_except POST { deny all; }" in nginx
    assert "client_max_body_size 256000;" in nginx
    assert "location / { return 404; }" in nginx
    caddy = (ROOT / "Caddyfile.template").read_text()
    assert "method POST" in caddy
    assert "path_regexp registry ^/webhooks/v2/" in caddy
    assert "reverse_proxy /*" not in caddy
    assert "respond 404" in caddy


def test_deployment_surfaces_have_no_retired_bot_configuration():
    """Deployments must launch without a global token, JWT or receiver mode."""
    retired = re.compile(
        r"\b(?:TOKEN|BALE_BOT_TOKEN|JWT_SECRET_KEY|TELEGRAM_UPDATE_MODE|"
        r"WEBHOOK_HOST|SQLADMIN_RAW_PASSWORD|LEGACY_ADMIN_PUBLIC_URL|"
        r"TELEGRAM_WORKER_URL|TELEGRAM_WORKER_SECRET|TELEGRAM_API_MODE|"
        r"TELEGRAM_PROXY_URL|BALE_WALLET_PROVIDER_TOKEN|TELEGRAM_FIAT_PROVIDER_TOKEN|"
        r"BALE_BROADCAST_PREPARE_CHAT_ID)\b"
    )
    for name in (
        "compose.codespaces.yml", "compose.test.yml", "docker-compose.yml",
        ".env.template", ".env.next-admin.example", ".devcontainer/devcontainer.json",
        "scripts/deploy.sh",
    ):
        assert retired.search((ROOT / name).read_text()) is None, name
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "profiles: [edge]" in compose
    assert '"127.0.0.1:3000:3000"' in compose
    assert '"5000:5000"' not in compose
    assert '"5432:5432"' not in compose
    assert '"6379:6379"' not in compose


def test_generic_upgrade_preserves_existing_postgres_directory():
    """An application upgrade must keep the same owner, MFA and order cluster."""
    source = (ROOT / "docker-compose.yml").read_text()
    postgres = re.search(r"^  postgres:\n(.*?)(?=^volumes:)", source, re.M | re.S).group(1)
    assert 'volumes: ["./postgres_data:/var/lib/postgresql"]' in postgres
    assert 'volumes: ["postgres_data:/var/lib/postgresql"]' not in postgres


def test_supported_stacks_have_one_idle_safe_shared_runtime_worker():
    """Layer 3 queues can drain after opt-in with no per-Bot worker process."""
    command = '["python", "-m", "shop_workflow_runtime"]'
    for filename, backend in (
        ("docker-compose.yml", "bot"), ("compose.codespaces.yml", "app"),
    ):
        source = (ROOT / filename).read_text()
        assert source.count(command) == 1
        worker = re.search(
            r"^  runtime-worker:\n(.*?)(?=^  [a-zA-Z]|^volumes:|\Z)",
            source, re.M | re.S,
        ).group(1)
        assert "profiles:" not in worker
        assert "restart: on-failure" in worker
        assert "command: " + command in worker
        for dependency in (backend, "postgres", "redis"):
            assert dependency + ": {condition: service_healthy}" in worker
    codespaces = (ROOT / "compose.codespaces.yml").read_text()
    assert "runtime-worker:\n    <<: *backend-service" in codespaces
    assert 'SHOP_WORKFLOW_RUNTIME_ENABLED: "${LIVE_WORKFLOW_RUNTIME_ENABLED:-false}"' in codespaces
    assert 'SHOP_WORKFLOW_RUNTIME_KILL_SWITCH: "${LIVE_WORKFLOW_RUNTIME_KILL_SWITCH:-false}"' in codespaces


def test_migration_acknowledgement_is_required_before_docker_invocation(tmp_path):
    """A bare migrate command cannot auto-acknowledge destructive retirement."""
    import os
    import subprocess

    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\nexit 97\n")
    docker.chmod(0o700)
    environment = {**os.environ, "PATH": str(tmp_path) + ":" + os.environ["PATH"]}
    result = subprocess.run(
        ["sh", str(ROOT / "scripts/deploy.sh"), "migrate"],
        cwd=ROOT, env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert "--retire-original-schema" in result.stderr


@pytest.mark.parametrize("tables,revisions", [
    (set(), []), ({"alembic_version"}, []),
    ({"shop_orders"}, []), ({"alembic_version"}, ["one", "two"]),
])
def test_migration_preflight_rejects_unversioned_or_ambiguous_database(tables, revisions):
    """Only explicit existing migration state may enter the historical upgrade path."""
    from scripts.migrate_registry_database import require_revision

    with pytest.raises(RuntimeError, match="existing Alembic revision"):
        require_revision(tables, revisions)


def test_migration_preflight_retains_existing_revision():
    """A known versioned database keeps its revision for Alembic graph validation."""
    from scripts.migrate_registry_database import require_revision

    assert require_revision({"alembic_version", "shop_orders"}, ["20261107z001"]) == "20261107z001"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,killed", [(False, False), (True, True)])
async def test_disabled_runtime_worker_stays_idle_without_database_or_provider_work(
    monkeypatch, enabled, killed,
):
    """The default shared service stays alive until shutdown without activation."""
    from types import SimpleNamespace
    import shop_workflow_runtime as runtime

    calls = []

    class Stop:
        """Complete one bounded idle wait without sleeping in this offline test."""

        async def wait(self):
            calls.append("idle_wait")

        def set(self):
            calls.append("stop")

    class Loop:
        """Record signal wiring without changing the test process handlers."""

        def add_signal_handler(self, *_args):
            calls.append("signal_installed")

        def remove_signal_handler(self, *_args):
            calls.append("signal_removed")

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Disabled Runtime must not initialize or drain")

    monkeypatch.setattr(runtime, "asyncio", SimpleNamespace(
        Event=Stop, get_running_loop=lambda: Loop(),
    ))
    monkeypatch.setattr(runtime.config, "SHOP_WORKFLOW_RUNTIME_ENABLED", enabled)
    monkeypatch.setattr(runtime.config, "SHOP_WORKFLOW_RUNTIME_KILL_SWITCH", killed)
    monkeypatch.setattr(runtime, "create_db_and_tables", forbidden)
    monkeypatch.setattr(runtime, "run_workers", forbidden)
    await runtime.main()
    assert calls == ["signal_installed", "idle_wait", "signal_removed"]
