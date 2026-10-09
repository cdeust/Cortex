"""#666: the groomer coordinator keys a session by its window's ``claude`` pid.

The SessionStart / SessionEnd hooks are short-lived processes. Registering the
hook's own pid made every registration dead within a second, so every
SessionEnd saw zero live sessions and took the last-exit path.

Each hook below runs in a REAL child process that exits before the next hook
starts, with the ancestor walk answering the pid of a long-lived stand-in for
the window's ``claude`` process.

source: ADR-0527, ADR-0597
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
