"""Check the browser prerequisite launcher without network or root changes."""

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "setup_browser.sh"


def run_setup(tmp_path: Path, fail: str = "") -> tuple[int, list[list[str]]]:
    """Replace only npm/npx/node processes; execute the real Bash launcher."""
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "commands.jsonl"
    for tool in ("npm", "npx", "node"):
        wrapper = binaries / tool
        wrapper.write_text(
            f"#!{sys.executable}\n"
            "import json, os, pathlib, sys\n"
            "tool = pathlib.Path(sys.argv[0]).name\n"
            "with open(os.environ['BROWSER_SETUP_LOG'], 'a') as out:\n"
            "    out.write(json.dumps([tool, *sys.argv[1:]]) + '\\n')\n"
            "sys.exit(9 if tool == os.environ.get('FAIL_TOOL') else 0)\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o700)
    env = {
        **os.environ,
        "PATH": str(binaries) + os.pathsep + os.environ.get("PATH", ""),
        "BROWSER_SETUP_LOG": str(log),
        "FAIL_TOOL": fail,
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)], env=env, cwd=tmp_path,
        capture_output=True, text=True, timeout=10, check=False,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result.returncode, calls


def test_setup_installs_chromium_system_dependencies_before_launch(tmp_path: Path) -> None:
    """Prevent reverting to a browser download that leaves OS libraries missing."""
    code, calls = run_setup(tmp_path)
    assert code == 0
    assert calls[0][0] == "npm"
    assert calls[0][1] in {"ci", "install"}
    assert calls[1] == ["npx", "--no-install", "playwright", "install", "--with-deps", "chromium"]
    assert calls[2][:2] == ["node", "--input-type=module"]
    assert len(calls) == 3


def test_package_install_failure_stops_before_browser_download(tmp_path: Path) -> None:
    """Do not continue with mismatched or missing Playwright package versions."""
    code, calls = run_setup(tmp_path, "npm")
    assert code == 9
    assert len(calls) == 1
    assert calls[0][0] == "npm"


def test_dependency_install_failure_stops_before_browser_launch(tmp_path: Path) -> None:
    """A failed apt/dependency installation must not be reported as ready."""
    code, calls = run_setup(tmp_path, "npx")
    assert code == 9
    assert [call[0] for call in calls] == ["npm", "npx"]
