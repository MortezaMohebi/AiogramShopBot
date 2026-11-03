"""Offline safety checks for the Codespaces live Docker integration.

These checks never run Docker, open sockets, contact a provider or handle real
bot tokens. They validate local setup boundaries before live activation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import codespace_setup


def test_codespace_urls_are_based_on_github_runtime_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never guess or hardcode a particular user's forwarded hostname."""
    monkeypatch.setenv("CODESPACE_NAME", "careful-test-codespace")
    monkeypatch.setenv(
        "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev"
    )
    gateway, dashboard = codespace_setup.urls()
    assert gateway == "https://careful-test-codespace-8080.app.github.dev"
    assert dashboard == "https://careful-test-codespace-3000.app.github.dev"


@pytest.mark.parametrize(
    "invalid",
    ["", "with spaces", "wrong/hostname", "../../etc/passwd"],
)
def test_invalid_codespace_name_fails_closed(
    invalid: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject unsafe Codespace names before generating public URLs."""
    monkeypatch.setenv("CODESPACE_NAME", invalid)
    with pytest.raises(RuntimeError):
        codespace_setup.urls()


def test_generated_secrets_are_private_and_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the dedicated Codespace file may hold the bootstrap password."""
    monkeypatch.setattr(codespace_setup, "PRIVATE_DIR", tmp_path)
    monkeypatch.setattr(
        codespace_setup, "ENV_FILE", tmp_path / "live.env"
    )
    expected = {
        "LIVE_ADMIN_PASSWORD": "not-a-default-random-placeholder",
        "LIVE_BRIDGE_SECRET": "example" * 8,
    }
    codespace_setup.write_env(expected)
    assert codespace_setup.read_env() == expected
    assert (tmp_path / "live.env").stat().st_mode & 0o077 == 0

    with pytest.raises(RuntimeError):
        codespace_setup.write_env({"BAD_KEY": "line\nINJECTED=1"})


def test_compose_ports_and_paid_flags_are_explicitly_bounded() -> None:
    """Keep only webhooks public and paid operations disabled by default."""
    root = Path(__file__).resolve().parent.parent
    compose = (root / "compose.codespaces.yml").read_text("utf-8")
    assert '"127.0.0.1:3000:3000"' in compose
    assert '"127.0.0.1:8080:8080"' in compose
    assert '"5000:5000"' not in compose
    for key in (
        "TELEGRAM_STARS_REFUNDS_ENABLED",
        "SHOP_CAMPAIGN_DISPATCH_ENABLED",
        "BALE_BROADCAST_PAID_ENABLED",
        "SHOP_BROADCAST_WORKER_ENABLED",
    ):
        assert f'{key}: "false"' in compose
    assert 'CODESPACE_MANUAL_WEBHOOK: "true"' in compose
    gateway = (root / "deploy/codespaces/nginx.conf").read_text("utf-8")
    assert "location = /hooks/telegram" in gateway
    assert "location ^~ /webhooks/bale/" in gateway
    assert "location / { return 404; }" in gateway
    # Restrict Nginx master/worker to UID/GID 101 and keep all
    # Linux capabilities dropped, with writable temporary paths.
    assert 'user: "101:101"' in compose
    assert 'cap_drop: ["ALL"]' in compose
    for path in (
        "client_body_temp_path /tmp/client_temp;",
        "proxy_temp_path /tmp/proxy_temp;",
        "fastcgi_temp_path /tmp/fastcgi_temp;",
        "uwsgi_temp_path /tmp/uwsgi_temp;",
        "scgi_temp_path /tmp/scgi_temp;",
    ):
        assert path in gateway


def test_admin_password_never_has_a_public_api_route() -> None:
    """Initial credentials must be retrieved from the Codespace terminal."""
    root = Path(__file__).resolve().parent.parent
    login = (
        root / "dashboard-next/app/(auth)/login/page.tsx"
    ).read_text("utf-8")
    assert "codespace_setup.py credentials" in login
    assert "LIVE_ADMIN_PASSWORD" not in login



def test_fresh_schema_classification_requires_empty_database() -> None:
    """Create a schema only from an empty test DB, not over actual records."""
    from scripts.codespace_bootstrap import classify_schema

    expected = {"shop_staff", "shop_products", "shop_orders"}

    assert classify_schema(set(), expected) == "create"
    assert classify_schema({"alembic_version"}, expected) == "create"
    assert classify_schema(expected, expected) == "verify"
    assert classify_schema(expected | {"alembic_version"}, expected) == "verify"

    with pytest.raises(RuntimeError, match="Partial or unexpected"):
        classify_schema({"shop_staff"}, expected)

    with pytest.raises(RuntimeError, match="Partial or unexpected"):
        classify_schema({"shop_staff", "other_table"}, expected)

    with pytest.raises(RuntimeError, match="revision"):
        classify_schema(
            {"alembic_version"}, expected, old_revisions_present=True,
        )


def test_fresh_schema_bootstrap_never_stamps_migrations() -> None:
    """Prevent reintroducing legacy SQLite Alembic history on fresh PG."""
    root = Path(__file__).resolve().parent.parent
    bootstrap = (root / "scripts/codespace_bootstrap.py").read_text("utf-8")
    assert "Base.metadata.create_all" in bootstrap
    assert "command.stamp(" not in bootstrap
    assert "command.upgrade(" not in bootstrap
    assert "checkfirst=False" in bootstrap

    db_source = (root / "db.py").read_text("utf-8")
    assert 'os.environ.get("CODESPACE_FRESH_SCHEMA") == "true"' in db_source
    assert "verify_codespace_schema(connection)" in db_source

    compose = (root / "compose.codespaces.yml").read_text("utf-8")
    assert 'CODESPACE_FRESH_SCHEMA: "true"' in compose
    assert "  bootstrap:" in compose
    assert "service_completed_successfully" in compose
