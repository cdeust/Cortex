"""Issue #704: an unconfigured profile's hooks connect to no PostgreSQL.

The issue asks for "a test that runs every hook entry point with port 5432
listening on a throwaway server and asserts that nothing connects to it".
Each of the eleven hooks the plugin manifest wires (``entry.HOOK_MODULES``)
runs here as the host runs it, in a child process, through both front doors:
``scripts/launcher.py`` (Claude Code plugin) and ``mcp_server.hooks.entry``
(the wheel's ``hypermnesia-mcp-hook``, Codex). The child gets a fresh HOME
(no marker, no URL, no backend variable), so nothing decides PostgreSQL.

The throwaway server is a TCP listener on an ephemeral port that counts the
connections it accepts. ``PGHOST``/``PGPORT`` point libpq's defaults at it,
so a connection opened with an empty or default conninfo -- the residual of
issue #704 -- lands there. Port 5432 itself is not bound: on a developer's
machine it may hold the real store this test protects. A Python audit hook
(PEP 578) in the child records every ``socket.connect`` and every
``socket.getaddrinfo``; psycopg 3 resolves each host of a conninfo through
``socket.getaddrinfo`` before libpq dials (measured 2026-11-13, psycopg
3.3.5), so a literal ``localhost:5432`` URL is caught as well.

source: issue #704 ("Expected"); ADR-1104 decision 1 (fresh HOME -> SQLite)
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from mcp_server.hooks.entry import HOOK_MODULES
from mcp_server.infrastructure.backend_resolution import has_earlier_state
from tests_py._hermetic_hook_env import await_capture_worker_exit, hermetic_hook_env
from tests_py._launcher_ready import ready_launcher_argv, ready_plugin_env

LAUNCHER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "launcher.py"
LEGACY_PORT = 5432  # source: pre-ADR-1104 scripts/launcher.py default URL
# source: dated measurement 2026-11-13, Linux container, Python 3.11: the 22
# runs of this module took 9.4 s in all; 60 s per run only bounds a hang.
HOOK_SECONDS = 60
_SITECUSTOMIZE = """
import os, sys
_log = os.environ["CORTEX_TEST_CONNECT_LOG"]
def _audit(event, args):
    if event == "socket.connect" and isinstance(args[1], tuple):
        host, port = args[1][0], args[1][1]
    elif event == "socket.getaddrinfo":
        host, port = args[0], args[1]
    else:
        return
    with open(_log, "a", encoding="utf-8") as out:
        out.write(f"{event} {host} {port}\\n")
sys.addaudithook(_audit)
"""
# source: backend_marker / memory_config -- every variable that decides the
# backend; the child must inherit none of them.
_DECIDING = (
    "DATABASE_URL",
    "CORTEX_MEMORY_DATABASE_URL",
    "CORTEX_MEMORY_STORE_BACKEND",
    "CORTEX_BACKEND",
    "CORTEX_ALLOW_SQLITE_FALLBACK",
)


@pytest.fixture
def listener():
    """A throwaway server: accepts and counts, never answers."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    accepted: list[tuple] = []

    def serve() -> None:
        while True:
            try:
                conn, peer = server.accept()
            except OSError:
                return
            accepted.append(peer)
            conn.close()

    threading.Thread(target=serve, daemon=True).start()
    yield server.getsockname()[1], accepted
    server.close()


def _child_env(tmp_path: Path, port: int) -> tuple[dict, Path]:
    """The hermetic hook environment (no detached worker) of a fresh HOME."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    base = {
        k: v
        for k, v in os.environ.items()
        if k not in _DECIDING and not k.startswith("PG")
    }
    base["CORTEX_CLAUDE_DIR"] = str(tmp_path / "claude-dir")
    base.update(ready_plugin_env(tmp_path))
    # The helper's consolidate-period seed must stamp the store key the hook
    # will use once it settles on SQLite; the hook itself inherits no backend.
    base["CORTEX_MEMORY_STORE_BACKEND"] = "sqlite"
    env, project = hermetic_hook_env(base, tmp_path)
    del env["CORTEX_MEMORY_STORE_BACKEND"]
    env.update(
        PYTHONPATH=os.pathsep.join([str(site), env["PYTHONPATH"]]),
        PGHOST="127.0.0.1",
        PGPORT=str(port),
        PGDATABASE="cortex",
        CORTEX_TEST_CONNECT_LOG=str(tmp_path / "connects.log"),
    )
    return env, project


def _command(front_door: str, hook: str) -> list[str]:
    if front_door == "launcher":
        return ready_launcher_argv(LAUNCHER_PATH, f"mcp_server.hooks.{hook}")
    return [sys.executable, "-m", "mcp_server.hooks.entry", hook]


@pytest.mark.parametrize("front_door", ["launcher", "wheel"])
@pytest.mark.parametrize("hook", sorted(HOOK_MODULES))
def test_unconfigured_hook_connects_to_no_postgresql(
    front_door, hook, tmp_path, listener
):
    port, accepted = listener
    env, project = _child_env(tmp_path, port)
    marker = tmp_path / "claude-dir" / "methodology" / "backend.json"
    assert not has_earlier_state(marker.parent, marker.name)  # a fresh HOME
    # session_lifecycle with a session_id starts a detached dream cycle
    # nobody can wait on (tests_py/hooks/test_entry.py, _benign_event).
    session = None if hook == "session_lifecycle" else "issue-704"
    event = {"session_id": session, "cwd": str(project), "prompt": "hello"}
    result = subprocess.run(
        _command(front_door, hook),
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=env,
        cwd=project,
        timeout=HOOK_SECONDS,
    )
    await_capture_worker_exit(env)
    log = tmp_path / "connects.log"
    connects = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    dialed = [c for c in connects if c.split()[-1] in {str(port), str(LEGACY_PORT)}]
    assert result.returncode == 0, result.stderr
    assert accepted == [], f"{hook} via {front_door} reached the listener"
    assert dialed == [], f"{hook} via {front_door} dialed PostgreSQL: {dialed}"
    assert json.loads(marker.read_text(encoding="utf-8"))["backend"] == "sqlite"
