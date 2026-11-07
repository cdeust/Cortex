"""Exercise the repository's coverage configuration across a Python child.

source: https://pytest-cov.readthedocs.io/en/latest/subprocess-support.html
pytest-cov 7 delegates child instrumentation to coverage.py's subprocess patch.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _write_fixture(root: Path) -> Path:
    """Use the actual coverage settings with a disposable package of that name."""
    config = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    section = config.split("[tool.coverage.run]", 1)[1].split("\n[", 1)[0]
    (root / "pyproject.toml").write_text(
        "[tool.coverage.run]" + section, encoding="utf-8"
    )
    package = root / "mcp_server"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    module = package / "child_only.py"
    module.write_text(
        'def called():\n    return "child ran"\n\n'
        'def uncalled():\n    return "not executed"\n',
        encoding="utf-8",
    )
    (root / "test_child.py").write_text(
        "import subprocess, sys\n\n"
        "def test_child():\n"
        "    result = subprocess.run([sys.executable, '-c', "
        "'from mcp_server.child_only import called; print(called())'], "
        "capture_output=True, text=True, check=True)\n"
        "    assert result.stdout.strip() == 'child ran'\n",
        encoding="utf-8",
    )
    return module


def test_pytest_cov_records_child_lines_without_claiming_uncalled_lines(tmp_path):
    module = _write_fixture(tmp_path)
    # A nested measurement owns its data and must not inherit the outer run.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("COVERAGE")
    }
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=str(tmp_path))
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "pytest_cov",
            "-q",
            "--cov=mcp_server",
            "--cov-report=json:coverage.json",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    files = json.loads((tmp_path / "coverage.json").read_text())["files"]
    measured = next(
        value for name, value in files.items() if name.endswith(module.name)
    )
    source = module.read_text().splitlines()
    called_line = source.index('    return "child ran"') + 1
    uncalled_line = source.index('    return "not executed"') + 1
    assert called_line in measured["executed_lines"]
    assert uncalled_line in measured["missing_lines"]
