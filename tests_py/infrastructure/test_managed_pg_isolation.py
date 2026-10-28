"""The managed server's supervisor is Cortex's own code, whatever the cwd.

Review F1 of #748 (round 6): ``managed_pg`` spawned the supervisor, which
holds the cluster's superuser password and lock fds, as ``python -m
mcp_server.infrastructure.managed_pg_supervisor`` with the caller's working
directory and without ``-I``. A project directory holding its own top-level
``mcp_server`` package (a common name for MCP servers, and every Cortex
checkout) then supplied the module that ran. The postmaster is
``fake_postgres``; the supervisor, locks and marker are the real ones.

source: ADR-1114
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests_py.infrastructure.fake_pg_lifeline import fake_pg_lifeline
from tests_py.infrastructure.test_managed_pg_attach import (
    REPO_ROOT,
    _env,
    _wait_supervisor_gone,
    home,
)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX only (ADR-1114)")
__all__ = ["fake_pg_lifeline", "home"]  # fixtures, imported
# source: review F1 of #748 — the two exec forms the hosts use, run from a
# project directory: Codex's runtime.py (`python -I -c`, the package on
# sys.path explicitly) and the Claude Code launcher's attach (cwd = the project,
# as measured for Claude Code 2.1.296). The client runs under `-I` in both so
# that only the supervisor child can pick up the planted package: the assertion
# is about that child. Both print the URL they attached to.
_SURFACES = {
    "codex-hook": (
        "import os, sys; sys.path.insert(0, sys.argv[1]);"
        " from mcp_server.hooks.entry import prepare_environment;"
        " prepare_environment(os.environ);"
        " print(os.environ['DATABASE_URL'], flush=True)"
    ),
    "claude-launcher": (
        "import os, sys; repo = sys.argv[1];"
        " sys.path[:0] = [repo, os.path.join(repo, 'scripts')];"
        " import launcher_backend; launcher_backend.apply();"
        " print(os.environ['DATABASE_URL'], flush=True)"
    ),
}
# source: test helper — a benign stand-in for hostile code: it records that it ran
_PLANTED = (
    "import os, pathlib, sys\n"
    "pathlib.Path(os.environ['CORTEX_TEST_PLANTED_SENTINEL']).write_text(\n"
    "    f'planted supervisor ran: cwd={os.getcwd()} argv={sys.argv[1:]}')\n"
)


def _plant_mcp_server(project: Path) -> None:
    """A project directory that has its own top-level ``mcp_server`` package."""
    infrastructure = project / "mcp_server" / "infrastructure"
    infrastructure.mkdir(parents=True)
    (project / "mcp_server" / "__init__.py").write_text("")
    (infrastructure / "__init__.py").write_text("")
    (infrastructure / "managed_pg_supervisor.py").write_text(_PLANTED)


@pytest.mark.parametrize("surface", sorted(_SURFACES))
def test_a_project_directory_cannot_replace_the_supervisor(home, tmp_path, surface):
    claude, root = home
    project = tmp_path / "project"
    _plant_mcp_server(project)
    sentinel = tmp_path / "planted.ran"
    env = _env(claude, CORTEX_RUNTIME="cowork")
    env["CORTEX_TEST_PLANTED_SENTINEL"] = str(sentinel)
    done = subprocess.run(
        [sys.executable, "-I", "-c", _SURFACES[surface], str(REPO_ROOT)],
        cwd=project, env=env, capture_output=True, text=True, check=False,
    )  # fmt: skip
    planted = sentinel.read_text() if sentinel.exists() else ""
    assert not planted, planted
    assert done.returncode == 0, done.stderr
    port = json.loads((root / "postmaster.json").read_text())["port"]
    assert (
        done.stdout.strip() == f"postgresql://postgres:s3cret@127.0.0.1:{port}/cortex"
    )
    _wait_supervisor_gone(root)
    assert json.loads((root / "status.json").read_text()) == {"state": "stopped"}
