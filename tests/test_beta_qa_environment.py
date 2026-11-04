"""Test the isolated Codespace QA environment without Docker or network calls."""

import pytest


def test_beta_qa_secrets_are_private_and_provider_free(tmp_path):
    """Preparing QA must not copy live tokens or overwrite its own database key."""
    from scripts.beta_qa_environment import prepare_environment

    target = tmp_path / "qa.env"
    prepare_environment(target)
    original = target.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    assert b"POSTGRES_DB=shop_codespace\n" in original
    assert b"SHOP_BETA_QA=1\n" in original
    assert b"TOKEN=\n" in original
    prepare_environment(target)
    assert target.read_bytes() == original


def test_existing_unknown_environment_is_not_replaced(tmp_path):
    """An unrelated environment must never become a reset target."""
    from scripts.beta_qa_environment import prepare_environment

    target = tmp_path / "qa.env"
    target.write_text("POSTGRES_DB=production\n")
    with pytest.raises(RuntimeError):
        prepare_environment(target)
    assert target.read_text() == "POSTGRES_DB=production\n"


@pytest.mark.parametrize(
    "override",
    [
        None,
        ("TOKEN", "live-token"),
        ("POSTGRES_DB", "production"),
        ("SHOP_BROADCAST_WORKER_ENABLED", "true"),
        ("SHOP_BROADCAST_REGISTRY_ENABLED", "true"),
        ("MULTIBOT_V2_RUNTIME_ENABLED", "true"),
        ("SHOP_DIGITAL_DELIVERY_ENABLED", "true"),
    ],
)
def test_beta_lab_guard_requires_exact_identity_and_inert_providers(
    tmp_path, monkeypatch, override
):
    """A named QA database alone never authorizes provider or worker traffic."""
    from scripts.beta_qa_environment import prepare_environment
    from scripts.test_lab_safety import require_isolated_lab

    target = prepare_environment(tmp_path / "qa.env")
    for line in target.read_text().splitlines():
        key, value = line.split("=", 1)
        monkeypatch.setenv(key, value)
    if override is None:
        require_isolated_lab()
    else:
        monkeypatch.setenv(*override)
        with pytest.raises(RuntimeError):
            require_isolated_lab()


def test_beta_app_includes_real_admin_authorization_and_customer_routes(
    tmp_path,
):
    """The QA server must exercise the same signed session boundary as production."""
    import os
    from pathlib import Path
    import subprocess
    import sys

    from scripts.beta_qa_environment import prepare_environment

    target = prepare_environment(tmp_path / "qa.env")
    environment = dict(line.split("=", 1) for line in target.read_text().splitlines())
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from scripts.test_lab_app import app
paths = {getattr(route, "path", "") for route in app.routes}
assert "/internal/admin/v1/store-context" in paths, paths
assert "/internal/admin/v1/digital-deliveries" in paths, paths
assert any(getattr(item.kwargs.get("dispatch"), "__name__", "") == "session_boundary" for item in app.user_middleware)
from contextlib import asynccontextmanager
from types import SimpleNamespace
from fastapi.testclient import TestClient
import scripts.test_lab_app as lab
@asynccontextmanager
async def database():
    async def scalar(query):
        return "shop_codespace" if "current_database" in str(query) else 1
    async def execute(query):
        return None
    yield SimpleNamespace(scalar=scalar, execute=execute)
class Redis:
    def __init__(self, **kwargs):
        pass
    async def ping(self):
        return True
    async def aclose(self):
        pass
lab.session_maker=database
lab.Redis=Redis
response=TestClient(app).get("/healthz")
assert response.status_code == 200, response.text
assert response.json()["provider_dispatch_enabled"] is False
print("QA control plane composition verified")
""",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, **environment},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
