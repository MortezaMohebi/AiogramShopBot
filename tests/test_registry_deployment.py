"""Pin supported deployment entrypoints and side-effect-free configuration."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_all_default_images_launch_registry_asgi():
    for name in ("Dockerfile", "Dockerfile.codespaces", "docker-compose.yml"):
        source = (ROOT / name).read_text()
        assert 'run.py' not in source
        assert 'scripts.secure_app:app' in source


def test_config_import_needs_no_legacy_jwt_or_public_ip_lookup(tmp_path):
    source = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import config; print('CONFIG_OK')"
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    result = subprocess.run([sys.executable, "-c", source], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CONFIG_OK"
