"""install-plugin.sh asks the launch whether the environment decides — issue #704.

ADR-1114 decision 7(a): a configured database (``DATABASE_URL``, or the host's
``CLAUDE_PLUGIN_OPTION_DATABASE_URL`` mapped onto it) or an explicit
``CORTEX_MEMORY_STORE_BACKEND`` wins before any marker is read. The installer
used its own ``-n`` tests and disagreed with the launch's
``backend_marker.environment_decides``; it now asks it. Driven with the harness
of ``test_install_plugin_no_implicit_postgres``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests_py.scripts.test_install_plugin_marker_order import (
    BASH,
    INSTALLER_PATH,
    REPO_ROOT,
    _marker_backend,
    _write_inert_pip_stubs,
    _write_setup_py_stub,
    _write_uname_stub,
)
from tests_py.scripts.test_install_plugin_no_implicit_postgres import (
    _DECIDING_VARIABLES,
    _MANAGED_MARKER,
    _run,
    _saved_marker,
)


def _setup_env(tmp_path: Path) -> dict:
    """The environment the stubbed scripts/setup.py was started with."""
    lines = (tmp_path / "setup_env").read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


@pytest.mark.parametrize("backend", ["postgresql", "sqlite"])
def test_an_explicit_store_backend_decides_and_leaves_the_managed_marker(
    tmp_path, backend
):
    # The other override of decision 7(a): an explicit CORTEX_* backend. Before
    # the fix `postgresql` took the managed path (Setup asked to provision the
    # managed server the launch ignores) and `sqlite` rewrote the marker,
    # losing its root (review of #1039).
    result, _ = _run(
        tmp_path,
        earlier_state=True,
        extra_env={"CORTEX_MEMORY_STORE_BACKEND": backend, "PGHOST": "x"},
        marker=_MANAGED_MARKER,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert f"Backend: {backend}" in result.stdout + result.stderr
    assert "CORTEX_SETUP_MANAGED_PG" not in _setup_env(tmp_path)
    assert _saved_marker(tmp_path) == _MANAGED_MARKER


@pytest.mark.parametrize("value", ["auto", "Postgres"])
def test_a_value_no_marker_holds_is_left_to_the_saved_marker(tmp_path, value):
    # "auto" is the engine's own choice, not a marker value: persisting it
    # would make read_backend_marker refuse every later launch (Codex review
    # of #1040). The saved choice stands, as before the environment check.
    result, _ = _run(
        tmp_path,
        earlier_state=True,
        extra_env={"CORTEX_MEMORY_STORE_BACKEND": value, "PGHOST": "x"},
        marker='{"backend": "sqlite"}',
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "Backend: sqlite" in result.stdout + result.stderr
    assert _marker_backend(tmp_path) == "sqlite"


def test_a_crlf_python_still_selects_the_environment_backend(tmp_path):
    # A native Windows Python ends print() with CRLF; $(...) drops only the
    # LF. Emulated by a python3 whose stdout gains a CR on every line.
    home = tmp_path / "home"
    (home / ".claude" / "methodology").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_setup_py_stub(bin_dir, exit_code=0)
    real = bin_dir / "python3-lf"
    (bin_dir / "python3").rename(real)
    crlf = bin_dir / "python3"
    crlf.write_text(
        f'#!/usr/bin/env bash\nset -o pipefail\n"{real}" "$@" | sed "s/$/\\r/"\n',
        encoding="utf-8",
    )
    crlf.chmod(0o755)
    _write_inert_pip_stubs(bin_dir)
    _write_uname_stub(bin_dir)
    env = {k: v for k, v in os.environ.items() if k not in _DECIDING_VARIABLES}
    env.update(
        HOME=str(home),
        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        CLAUDE_PLUGIN_ROOT=str(REPO_ROOT),
        CORTEX_MEMORY_STORE_BACKEND="sqlite",
    )
    result = subprocess.run(
        [BASH, str(INSTALLER_PATH)], env=env, capture_output=True, text=True, timeout=60
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    # The marker, not the log: text mode folds the CRLF of the log away.
    assert _marker_backend(tmp_path) == "sqlite"


def test_the_host_option_url_decides_and_reaches_setup_trimmed(tmp_path):
    # Hooks and Setup receive `database_url` as CLAUDE_PLUGIN_OPTION_DATABASE_URL,
    # mapped onto an empty DATABASE_URL first (launcher_backend). Before the
    # fix the installer ignored it and kept the managed path.
    result, _ = _run(
        tmp_path,
        earlier_state=True,
        extra_env={
            "CLAUDE_PLUGIN_OPTION_DATABASE_URL": " postgresql://db.example/cortex ",
            "DATABASE_URL": "  ",
        },
        marker=_MANAGED_MARKER,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "Backend: postgresql" in result.stdout + result.stderr
    assert _setup_env(tmp_path)["DATABASE_URL"] == "postgresql://db.example/cortex"
    assert _saved_marker(tmp_path) == _MANAGED_MARKER


def test_a_blank_url_decides_nothing_and_setup_provisions_the_managed_server(
    tmp_path,
):
    # environment_decides strips the URL: spaces configure nothing, so the
    # managed marker selects. Before the fix `-n` took them for a URL.
    result, calls = _run(
        tmp_path,
        earlier_state=True,
        extra_env={"DATABASE_URL": "   "},
        marker=_MANAGED_MARKER,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "Existing managed PostgreSQL kept" in result.stdout + result.stderr
    assert _setup_env(tmp_path)["CORTEX_SETUP_MANAGED_PG"] == "1"
    assert _saved_marker(tmp_path) == _MANAGED_MARKER
    assert not calls.exists()
