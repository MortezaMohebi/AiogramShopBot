"""Exercise the QA entrypoint's test coverage and failure propagation."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("python_exit", [0, 7])
def test_acceptance_discovers_all_python_tests_and_preserves_failures(
    tmp_path, python_exit
):
    """New digital/split regressions cannot be omitted by a filename allowlist."""
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "scripts").mkdir()
    (tmp_path / "bin").mkdir()
    runner = tmp_path / "scripts/beta_storefront_acceptance.sh"
    shutil.copyfile(root / "scripts/beta_storefront_acceptance.sh", runner)
    trace = tmp_path / "commands.log"
    for name in ("python3", "npm", "node"):
        fake = tmp_path / "bin" / name
        fake.write_text(
            '#!/bin/sh\nprintf "%s %s\\n" "${0##*/}" "$*" >> "$QA_TRACE"\n'
            'if [ "${2:-}" = pytest ]; then\n'
            '  case " $* " in *" tests "*) exit "$QA_PYTEST_EXIT";; *) exit 77;; esac\n'
            "fi\n",
        )
        fake.chmod(0o700)
    result = subprocess.run(
        ["bash", str(runner)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
            "QA_TRACE": str(trace),
            "QA_PYTEST_EXIT": str(python_exit),
        },
        check=False,
    )
    assert result.returncode == python_exit, result.stdout + result.stderr
    commands = trace.read_text()
    assert "python3 -m pytest -q tests\n" in commands
    if python_exit:
        assert "npm " not in commands
