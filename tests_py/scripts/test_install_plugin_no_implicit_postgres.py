"""install-plugin.sh decides an undecided HOME with the launcher's rule — issue #704.

Before the fix the installer probed ``psql -h 127.0.0.1 -p 5432 -d cortex``
on every HOME nothing else decided, so a fresh profile on a machine that
happens to run a local ``cortex`` database was pointed at it. ADR-1104
(decision 1 and Consequences) keeps that detection only for a HOME that
holds earlier Cortex state; a fresh HOME is SQLite. The installer now calls
the launcher's ``backend_resolution.decide`` instead of its own probe.

The real installer is driven with the stubs of
``test_install_plugin_marker_order`` (a ``python3`` that fakes only
``scripts/setup.py``, inert ``pip``), plus a ``psql`` that answers like a
reachable ``cortex`` database and records every call.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from tests_py.scripts.test_install_plugin_marker_order import (
    BASH,
    INSTALLER_PATH,
    REPO_ROOT,
    _marker_backend,
    _write_inert_pip_stubs,
    _write_setup_py_stub,
    _write_uname_stub,
)

# source: backend_marker / memory_config — every variable that decides the
# backend before detection runs; the test must not inherit one.
_DECIDING_VARIABLES = (
    "DATABASE_URL",
    "CORTEX_MEMORY_DATABASE_URL",
    "CORTEX_MEMORY_STORE_BACKEND",
    "CORTEX_BACKEND",
)


def _write_answering_psql(bin_dir: Path, calls: Path) -> None:
    """A ``psql`` that succeeds like a reachable local ``cortex`` database."""
    stub = bin_dir / "psql"
    stub.write_text(
        f'#!/usr/bin/env bash\necho "$@" >> "{calls}"\necho 1\n', encoding="utf-8"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(
    tmp_path: Path, *, earlier_state: bool, extra_env: dict, marker: str = ""
) -> tuple:
    home = tmp_path / "home"
    methodology = home / ".claude" / "methodology"
    methodology.mkdir(parents=True)
    if earlier_state:
        (methodology / "profiles.json").write_text("{}", encoding="utf-8")
    if marker:
        (methodology / "backend.json").write_text(marker, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "psql_calls"
    _write_setup_py_stub(bin_dir, exit_code=0)
    _write_inert_pip_stubs(bin_dir)
    # Windows dispatch: the PostgreSQL branch then runs the stubbed setup.py
    # instead of scripts/setup.sh, which needs a real PostgreSQL.
    _write_uname_stub(bin_dir)
    _write_answering_psql(bin_dir, calls)
    env = {k: v for k, v in os.environ.items() if k not in _DECIDING_VARIABLES}
    env = {k: v for k, v in env.items() if not k.startswith("PG")}
    env.update(
        HOME=str(home),
        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        CLAUDE_PLUGIN_ROOT=str(REPO_ROOT),
        **extra_env,
    )
    result = subprocess.run(
        [BASH, str(INSTALLER_PATH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result, calls


def test_fresh_home_is_sqlite_even_when_a_local_cortex_database_answers(tmp_path):
    result, calls = _run(tmp_path, earlier_state=False, extra_env={})

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert _marker_backend(tmp_path) == "sqlite"
    assert "fresh install" in result.stdout + result.stderr
    assert not calls.exists(), "the installer queried a database nobody configured"


def test_home_with_earlier_state_keeps_postgresql_by_the_launcher_rule(tmp_path):
    # A configured libpq (PGHOST) is the launcher's deterministic "keep
    # PostgreSQL" answer: no socket is opened to decide (ADR-1104).
    result, calls = _run(
        tmp_path, earlier_state=True, extra_env={"PGHOST": "127.0.0.1"}
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert _marker_backend(tmp_path) == "postgresql"
    assert "earlier Cortex state" in result.stdout + result.stderr
    assert not calls.exists()


def test_reinstall_keeps_an_existing_sqlite_marker(tmp_path):
    # Same HOME as above (earlier state, PGHOST) but a saved `sqlite` choice:
    # the marker wins over the first-launch rule, as in settle_backend.
    result, calls = _run(
        tmp_path,
        earlier_state=True,
        extra_env={"PGHOST": "127.0.0.1"},
        marker='{"backend": "sqlite"}',
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert _marker_backend(tmp_path) == "sqlite"
    assert not calls.exists()
