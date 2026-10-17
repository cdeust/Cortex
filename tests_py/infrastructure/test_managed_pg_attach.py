"""Every surface attaches to the managed server the same way (ADR-1110, D1, B3).

Round-3 review: with a ``managed`` marker, ``python -m mcp_server``, the Codex
hook entry (``mcp_server.hooks.entry``, what ``runtime.py`` executes) and the
doctor raised ``BackendMarkerError``; the doctor printed a traceback (B3).
Owner decision D1: they attach to the managed server through the same locks
and supervisor as the Claude Code launcher, so Claude and Codex on one HOME
share one store. The postmaster is ``fake_postgres`` (real SCRAM, real
``postmaster.pid``); the supervisor, locks and marker are the real ones.

source: ADR-1110
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests_py.infrastructure import fake_postgres

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX only (ADR-1110)")
REPO_ROOT = Path(__file__).resolve().parents[2]
# source: ADR-1110 D1 — what runtime.py runs for a Codex hook, minus the event
_CODEX = (
    "import os; from mcp_server.hooks.entry import prepare_environment;"
    " prepare_environment(os.environ); print(os.environ['DATABASE_URL'], flush=True)"
)
# source: ADR-1110 — what the Claude Code launcher runs, then stays attached
_LAUNCHER = (
    "import os, sys; sys.path.insert(0, 'scripts'); import launcher_backend;"
    " launcher_backend.apply(); print(os.environ['DATABASE_URL'], flush=True);"
    " sys.stdin.read()"
)


@pytest.fixture
def home(tmp_path):
    """A Claude dir whose marker selects a provisioned managed root."""
    claude = tmp_path / "claude"
    root = claude / "methodology" / "managed-pg"
    (root / "cluster").mkdir(parents=True)
    (root / "password").write_text("s3cret\n")
    tree = tmp_path / "tree"
    fake_postgres.install(tree / "bin")
    (root / "installed.json").write_text(json.dumps({"tree": str(tree)}))
    marker = {"backend": "managed", "written_by": "t", "root": str(root)}
    (claude / "methodology" / "backend.json").write_text(json.dumps(marker))
    yield claude, root
    _wait_supervisor_gone(root)


def _wait_supervisor_gone(root: Path) -> None:
    """Block on supervisor.lock (held for the supervisor's life): no leak."""
    from mcp_server.infrastructure import managed_pg

    fd = managed_pg.open_lock(root / "supervisor.lock")
    try:
        managed_pg.flock(fd, exclusive=True)
    finally:
        os.close(fd)


def _env(claude: Path, **extra: str) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CORTEX_", "CLAUDE_PLUGIN_OPTION")) and k != "DATABASE_URL"
    }
    env.update(CORTEX_CLAUDE_DIR=str(claude), PYTHONPATH=str(REPO_ROOT), **extra)
    return env


def _run(code: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, env=env,
        capture_output=True, text=True, check=False,
    )  # fmt: skip


def test_a_codex_hook_attaches_to_the_managed_server(home):
    claude, root = home
    done = _run(_CODEX, _env(claude, CORTEX_RUNTIME="cowork"))
    assert done.returncode == 0, done.stderr
    # postmaster.json, not status.json: once the process exited the
    # supervisor may already have stopped the server and rewritten status.
    port = json.loads((root / "postmaster.json").read_text())["port"]
    assert (
        done.stdout.strip() == f"postgresql://postgres:s3cret@127.0.0.1:{port}/cortex"
    )
    _wait_supervisor_gone(root)
    assert json.loads((root / "status.json").read_text()) == {"state": "stopped"}


def test_claude_and_codex_on_one_home_share_one_server(home):
    claude, root = home
    launcher = subprocess.Popen(
        [sys.executable, "-c", _LAUNCHER], cwd=REPO_ROOT, env=_env(claude),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )  # fmt: skip
    try:
        claude_url = launcher.stdout.readline().strip()
        supervisor = json.loads((root / "status.json").read_text())["pid"]
        codex = _run(_CODEX, _env(claude, CORTEX_RUNTIME="cowork"))
        assert codex.stdout.strip() == claude_url, codex.stderr
        assert json.loads((root / "status.json").read_text())["pid"] == supervisor
    finally:
        launcher.stdin.close()
        launcher.wait()


def test_the_doctor_reports_the_managed_server_instead_of_crashing(home):
    # B3: `python -m mcp_server.doctor` raised BackendMarkerError on this marker.
    claude, root = home
    done = _run("from mcp_server.doctor import run; run()", _env(claude))
    assert "Traceback" not in done.stderr, done.stderr
    # postmaster.json, not status.json: once the process exited the
    # supervisor may already have stopped the server and rewritten status.
    port = json.loads((root / "postmaster.json").read_text())["port"]
    assert f"running on 127.0.0.1:{port}, cluster {root}" in done.stdout


def test_the_doctor_names_why_a_managed_server_cannot_run(home):
    claude, root = home
    (root / "installed.json").write_text("{}")  # the plugin's data was removed
    done = _run("from mcp_server.doctor import run; run()", _env(claude))
    assert "Traceback" not in done.stderr, done.stderr
    assert "Managed PostgreSQL server" in done.stdout
    assert "claude --init-only" in done.stdout


def test_effective_backend_names_a_managed_marker_and_starts_nothing(home):
    claude, root = home
    from mcp_server.infrastructure.backend_marker import effective_backend

    marker = claude / "methodology" / "backend.json"
    assert effective_backend({}, marker) == "postgresql"
    assert not (root / "status.json").exists()
