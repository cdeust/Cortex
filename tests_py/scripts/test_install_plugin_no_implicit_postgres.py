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
    DECIDING_VARIABLES,
    INSTALLER_PATH,
    REPO_ROOT,
    _marker_backend,
    _write_inert_pip_stubs,
    _write_setup_py_stub,
    _write_uname_stub,
)

# The variables that decide the backend before detection; not inherited.
_DECIDING_VARIABLES = DECIDING_VARIABLES


def _write_answering_psql(bin_dir: Path, calls: Path) -> None:
    """A ``psql`` that succeeds like a reachable local ``cortex`` database."""
    stub = bin_dir / "psql"
    stub.write_text(
        f'#!/usr/bin/env bash\necho "$@" >> "{calls}"\necho 1\n', encoding="utf-8"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _make_home(tmp_path: Path, *, earlier_state: bool, marker: str) -> Path:
    """A HOME with optional earlier Cortex state and a saved backend marker."""
    home = tmp_path / "home"
    methodology = home / ".claude" / "methodology"
    methodology.mkdir(parents=True)
    if earlier_state:
        (methodology / "profiles.json").write_text("{}", encoding="utf-8")
    if marker:
        (methodology / "backend.json").write_text(marker, encoding="utf-8")
    return home


def _run(
    tmp_path: Path,
    *,
    earlier_state: bool,
    extra_env: dict,
    marker: str = "",
    setup_exit_code: int = 0,
    args: tuple = (),
) -> tuple:
    home = _make_home(tmp_path, earlier_state=earlier_state, marker=marker)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "psql_calls"
    env_log = tmp_path / "setup_env"
    _write_setup_py_stub(bin_dir, exit_code=setup_exit_code, env_log=env_log)
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
        [BASH, str(INSTALLER_PATH), *args],
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


def test_reinstall_keeps_a_managed_marker_as_setup_wrote_it(tmp_path):
    # A managed marker (ADR-1114) carries the server root and Setup's
    # identity. Before the fix it fell through to decide(), which assumes no
    # marker: with earlier state and PGHOST it was rewritten to postgresql,
    # detaching the store from the managed server.
    marker = (
        '{"backend": "managed", "root": "/srv/managed-pg",'
        ' "written_by": "Setup (managed PostgreSQL started, ADR-1114)"}'
    )
    result, calls = _run(
        tmp_path,
        earlier_state=True,
        extra_env={"PGHOST": "127.0.0.1"},
        marker=marker,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    saved = tmp_path / "home" / ".claude" / "methodology" / "backend.json"
    assert saved.read_text(encoding="utf-8") == marker
    assert "Existing managed PostgreSQL kept" in result.stdout + result.stderr
    assert not calls.exists()


_MANAGED_MARKER = (
    '{"backend": "managed", "root": "/srv/managed-pg",'
    ' "written_by": "Setup (managed PostgreSQL started, ADR-1114)"}\n'
)


def _saved_marker(tmp_path: Path) -> str:
    saved = tmp_path / "home" / ".claude" / "methodology" / "backend.json"
    return saved.read_text(encoding="utf-8")


def test_a_configured_url_wins_and_leaves_the_managed_marker_intact(tmp_path):
    # ADR-1114 decision 7(a): a configured database beats the managed marker,
    # which is then only ignored. Before the fix the installer rewrote it to
    # {"backend": "postgresql"}, losing the root, so removing the URL later
    # no longer reached the managed server (issue #704).
    result, calls = _run(
        tmp_path,
        earlier_state=True,
        extra_env={"DATABASE_URL": "postgresql://db.example:5432/cortex"},
        marker=_MANAGED_MARKER,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    out = result.stdout + result.stderr
    assert "Backend: postgresql" in out
    assert "Existing managed PostgreSQL kept" not in out
    assert _saved_marker(tmp_path) == _MANAGED_MARKER


def test_a_failed_switch_away_from_managed_restores_the_marker_with_its_root(
    tmp_path,
):
    # An explicit request (CORTEX_BACKEND) does replace the marker; when its
    # setup fails the earlier marker comes back byte for byte. Before the fix
    # it came back as {"backend": "managed"} with no root, which
    # read_backend_marker rejects (issue #704).
    result, _ = _run(
        tmp_path,
        earlier_state=True,
        extra_env={"CORTEX_BACKEND": "postgres"},
        marker=_MANAGED_MARKER,
        setup_exit_code=1,
    )

    assert result.returncode != 0
    assert "restored working marker to managed" in result.stdout + result.stderr
    assert _saved_marker(tmp_path) == _MANAGED_MARKER
