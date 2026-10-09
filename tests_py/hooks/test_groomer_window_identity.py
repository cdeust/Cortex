"""#666: the groomer coordinator keys a session by its window's ``claude`` pid.

The SessionStart / SessionEnd hooks are short-lived processes. Registering the
hook's own pid made every registration dead within a second, so every
SessionEnd saw zero live sessions and took the last-exit path.

Each hook below runs in a REAL child process that exits before the next hook
starts, with the ancestor walk answering the pid of a long-lived stand-in for
the window's ``claude`` process.

source: ADR-0527 (coordinator; window identity: ADR-0597; Windows walk: ADR-1096)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from mcp_server.infrastructure import session_registry
from mcp_server.infrastructure import process_ancestry
from mcp_server.shared import platform as host_platform
from mcp_server.shared import process_liveness
from mcp_server.shared import win32_process
from tests_py.infrastructure.process_table_fakes import FakeProcessTable
from mcp_server.infrastructure.groomer_coordinator import (
    GroomerCoordinator,
    WindowIdentityUnavailableError,
    resolve_store_key,
    window_pid,
)

_HOOK_DRIVER = textwrap.dedent(
    """
    import sys
    from mcp_server.infrastructure import session_registry

    mode, claude_pid, groomer_pid = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    session_registry.find_claude_ancestor = lambda *a, **k: claude_pid

    if mode == "start":
        from mcp_server.hooks import session_start
        session_start._spawn_consolidate_cycle = lambda: groomer_pid
        session_start._maybe_background_consolidate()
    else:
        from mcp_server.hooks import session_lifecycle
        session_lifecycle._deregister_groomer_coordinator()
    """
)


def _run_hook(mode: str, cache: Path, claude_pid: int, groomer_pid: int) -> None:
    """Run one hook in its own process; it has exited when this returns."""
    subprocess.run(
        [sys.executable, "-c", _HOOK_DRIVER, mode, str(claude_pid), str(groomer_pid)],
        env={**os.environ, "XDG_CACHE_HOME": str(cache)},
        check=True,
    )


@pytest.fixture
def live_pids():
    """Three long-lived processes: windows A and B, and the groomer."""
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdin.read()"],
            stdin=subprocess.PIPE,
        )
        for _ in range(3)
    ]
    try:
        yield [p.pid for p in procs]
    finally:
        for p in procs:
            p.stdin.close()
            p.wait()


@pytest.fixture
def cache(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return tmp_path


def _coord(_cache: Path) -> GroomerCoordinator:
    return GroomerCoordinator(resolve_store_key())


def _outcomes(coord: GroomerCoordinator) -> list[str]:
    lines = coord.log_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["outcome"] for line in lines]


def test_registration_outlives_the_start_hook(cache, live_pids):
    win_a, _win_b, groomer = live_pids
    _run_hook("start", cache, win_a, groomer)

    coord = _coord(cache)
    assert [p for _, p in coord._iter_session_files()] == [win_a]
    assert coord.live_session_count() == 1


def test_overlapping_sessions_keep_groomer_until_the_second_ends(cache, live_pids):
    win_a, win_b, groomer = live_pids
    _run_hook("start", cache, win_a, groomer)
    _run_hook("start", cache, win_b, groomer)
    coord = _coord(cache)
    assert coord.live_session_count() == 2

    _run_hook("end", cache, win_a, groomer)
    assert coord.is_groomer_running(), "session A is not the last: B is live"
    assert "stopped_last_exit" not in _outcomes(coord)
    assert [p for _, p in coord._iter_session_files()] == [win_b]

    _run_hook("end", cache, win_b, groomer)
    assert not coord.is_groomer_running()
    assert _outcomes(coord).count("stopped_last_exit") == 1


def test_window_pid_is_the_claude_ancestor(monkeypatch):
    monkeypatch.setattr(session_registry, "find_claude_ancestor", lambda: 4242)
    assert window_pid() == 4242


def test_window_pid_fails_loudly_without_a_claude_ancestor(monkeypatch):
    monkeypatch.setattr(session_registry, "find_claude_ancestor", lambda: None)
    with pytest.raises(WindowIdentityUnavailableError):
        window_pid()


def test_session_end_without_window_identity_stops_nothing(
    cache, live_pids, monkeypatch
):
    """The hook boundary logs the failure; it never takes the last-exit path."""
    from mcp_server.hooks import session_lifecycle

    win_a, _win_b, groomer = live_pids
    _run_hook("start", cache, win_a, groomer)
    coord = _coord(cache)

    monkeypatch.setattr(session_registry, "find_claude_ancestor", lambda: None)
    session_lifecycle._deregister_groomer_coordinator()

    assert coord.is_groomer_running()
    assert coord.live_session_count() == 1
    assert "stopped_last_exit" not in _outcomes(coord)


# A Windows chain with no claude.exe anywhere: init -> bash.exe -> python.exe.
# source: process_table_fakes.WINDOWS_WINDOW_TREE minus its claude.exe rows
_NO_CLAUDE_TREE = [
    (1, 0, "init", 10),
    (30, 1, "bash.exe", 300),
    (40, 30, "python.exe", 400),
]
# source: the python.exe pid in _NO_CLAUDE_TREE
_HOOK_PID = 40


@pytest.fixture
def windows_walk(monkeypatch):
    """The real Windows ancestor walk over a fake table; yields a setter."""
    state = {"table": FakeProcessTable(_NO_CLAUDE_TREE)}

    def snapshot():
        return state["table"].snapshot()

    monkeypatch.setattr(host_platform, "IS_WINDOWS", True)
    monkeypatch.setattr(win32_process, "snapshot_rows", snapshot)
    monkeypatch.setattr(
        win32_process, "creation_filetime", lambda p: state["table"].creation(p)
    )
    # liveness of the REAL stand-in processes stays the POSIX probe
    monkeypatch.setattr(win32_process, "pid_alive", process_liveness._posix_pid_alive)
    monkeypatch.setattr(os, "getpid", lambda: _HOOK_PID)
    process_ancestry._window_pid_cache.clear()
    yield state
    process_ancestry._window_pid_cache.clear()


def _unreadable_table():
    raise OSError("process table unreadable")


@pytest.fixture
def start_hook(monkeypatch, cache):
    """session_start with the spawn and the legacy path recorded."""
    from mcp_server.hooks import session_start

    calls = {"spawn": 0, "legacy": 0, "log": []}

    def spawn():
        calls["spawn"] += 1
        return os.getpid()

    def legacy():
        calls["legacy"] += 1

    monkeypatch.setattr(session_start, "_spawn_consolidate_cycle", spawn)
    monkeypatch.setattr(session_start, "_legacy_background_consolidate", legacy)
    monkeypatch.setattr(session_start, "_log", calls["log"].append)
    return session_start, calls


def test_session_start_without_ancestor_registers_and_spawns_nothing(
    windows_walk, start_hook, cache
):
    session_start, calls = start_hook
    session_start._maybe_background_consolidate()
    session_start._maybe_background_consolidate()  # an overlapping second window

    coord = _coord(cache)
    assert calls["spawn"] == 0
    assert calls["legacy"] == 0, "no legacy bypass of the coordinator"
    assert not coord.sessions_dir.exists()
    assert not coord.stamp_path.exists()
    assert not coord.pid_path.exists()
    assert sum("no claude ancestor" in m for m in calls["log"]) == 2


def test_session_start_with_unreadable_process_table_fails_hard(
    windows_walk, start_hook, cache
):
    session_start, calls = start_hook
    windows_walk["table"].snapshot = _unreadable_table
    session_start._maybe_background_consolidate()

    coord = _coord(cache)
    assert calls["spawn"] == 0
    assert calls["legacy"] == 0
    assert not coord.sessions_dir.exists()
    assert any("process table unreadable" in m for m in calls["log"])


def test_session_end_with_unreadable_process_table_stops_nothing(
    windows_walk, live_pids, cache, monkeypatch
):
    from mcp_server.hooks import session_lifecycle

    win_a, _win_b, groomer = live_pids
    _run_hook("start", cache, win_a, groomer)
    coord = _coord(cache)
    logged: list[str] = []
    monkeypatch.setattr(session_lifecycle, "_log", logged.append)
    windows_walk["table"].snapshot = _unreadable_table

    session_lifecycle._deregister_groomer_coordinator()

    assert coord.is_groomer_running()
    assert coord.live_session_count() == 1
    assert any("process table unreadable" in m for m in logged)
