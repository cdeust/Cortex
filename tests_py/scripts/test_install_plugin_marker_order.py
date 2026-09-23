"""install-plugin.sh must persist the backend decision before scripts/setup.py
can fail and exit — issue #633.

Before the fix, ~/.claude/methodology/backend.json was written only after
the setup.py step, guarded by `|| fail ...`. Any setup.py failure (a
Windows torch/torchaudio conflict, a network blip during dependency
install, anything) discarded a correctly-made backend decision. On the
next launch, the missing marker left CORTEX_MEMORY_STORE_BACKEND unset,
and this plugin's "auto" default requires PostgreSQL in CLI-mode runtimes
(mcp_server/infrastructure/memory_store.py) — turning a chosen SQLite
install into a hard PostgreSQL requirement with no PostgreSQL ever
provisioned to satisfy it.

This test drives the real installer against a `python3` stub that fails
only the scripts/setup.py invocation, so the regression reproduces without
needing a genuine environment conflict.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER_PATH = REPO_ROOT / "scripts" / "install-plugin.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash is required to drive the installer"
)


def _write_setup_py_stub(bin_dir: Path, *, exit_code: int) -> None:
    """A `python3` on PATH: real Python for everything except
    scripts/setup.py, which exits with `exit_code` immediately -- standing
    in for issue #633's Defect 1 crash (or a clean run) without needing a
    real torch/torchaudio conflict to reproduce either."""
    stub = bin_dir / "python3"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'for arg in "$@"; do\n'
        '    case "$arg" in\n'
        f"        */scripts/setup.py) exit {exit_code} ;;\n"
        "    esac\n"
        "done\n"
        f'exec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    mode = stub.stat().st_mode
    stub.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run_installer(
    tmp_path: Path, *, setup_py_exit_code: int
) -> subprocess.CompletedProcess:
    """Drive the real installer, home/PATH isolated under tmp_path, against
    a python3 stub that only fakes scripts/setup.py's own exit code."""
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_setup_py_stub(bin_dir, exit_code=setup_py_exit_code)

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
        "CORTEX_BACKEND": "sqlite",
    }
    return subprocess.run(
        ["bash", str(INSTALLER_PATH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _marker_backend(tmp_path: Path) -> str:
    marker = tmp_path / "home" / ".claude" / "methodology" / "backend.json"
    assert marker.exists()
    return json.loads(marker.read_text(encoding="utf-8"))["backend"]


def test_marker_persists_backend_even_when_setup_py_fails(tmp_path):
    result = _run_installer(tmp_path, setup_py_exit_code=1)

    # The installer still fails overall — setup.py genuinely failed, and
    # that failure must not be hidden.
    assert result.returncode != 0
    assert "scripts/setup.py failed" in result.stderr

    # But the backend decision itself must survive: a subsequent launch
    # must not silently fall back to requiring PostgreSQL.
    assert _marker_backend(tmp_path) == "sqlite", (
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_marker_persists_backend_on_a_successful_sqlite_install(tmp_path):
    """Companion to the failure case: an ordinary successful install still
    persists the marker (the reordering did not just move the write, it
    kept it reachable on the happy path too)."""
    result = _run_installer(tmp_path, setup_py_exit_code=0)

    assert result.returncode == 0, result.stderr
    assert _marker_backend(tmp_path) == "sqlite"
