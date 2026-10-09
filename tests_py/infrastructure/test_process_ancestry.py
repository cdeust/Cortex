"""Windows ancestor walk over a fake process table (issue #665).

Runs on every platform: the walk, the ``claude.exe`` match, the pid-reuse
guard and the per-process cache are plain Python over an injected table.

source: ADR-1096"""

from __future__ import annotations

import os

import pytest

from mcp_server.infrastructure import process_ancestry as pa
from tests_py.infrastructure.process_table_fakes import (
    CLAUDE_PID,
    DESKTOP_PID,
    HOOK_PID,
    SERVER_PID,
    FakeProcessTable,
)

# source: session_registry._MAX_ANCESTOR_DEPTH (ADR-0597, design T2-D3)
_DEPTH = 15


@pytest.fixture(autouse=True)
def _fresh_cache():
    pa._window_pid_cache.clear()
    yield
    pa._window_pid_cache.clear()


def _walk(table, start, depth=_DEPTH):
    return pa.claude_ancestor_pid(
        start, depth, snapshot=table.snapshot, creation=table.creation
    )


def test_hook_walk_returns_nearest_claude_not_the_desktop_app():
    # python.exe -> bash x3 -> claude.exe -> Claude.exe (shared desktop app)
    assert _walk(FakeProcessTable(), HOOK_PID) == CLAUDE_PID != DESKTOP_PID


def test_server_walk_crosses_cmd_exe_to_claude():
    # the MCP server's parent is cmd.exe, not claude.exe (cause 3 of #665)
    assert _walk(FakeProcessTable(), SERVER_PID) == CLAUDE_PID


def test_exe_name_match_is_case_insensitive():
    rows = [(1, 0, "CLAUDE.EXE", 1), (2, 1, "bash.exe", 2), (3, 2, "python.exe", 3)]
    assert _walk(FakeProcessTable(rows), 3) == 1


def test_no_claude_in_chain_returns_none():
    rows = [(1, 0, "explorer.exe", 1), (2, 1, "cmd.exe", 2), (3, 2, "python.exe", 3)]
    assert _walk(FakeProcessTable(rows), 3) is None


def test_start_pid_absent_from_table_returns_none():
    assert _walk(FakeProcessTable(), 9999) is None


def test_parent_missing_from_table_returns_none():
    rows = [(2, 77, "bash.exe", 2), (3, 2, "python.exe", 3)]  # 77 exited
    assert _walk(FakeProcessTable(rows), 3) is None


def test_recycled_parent_pid_is_not_followed():
    # pid 1 now names a claude.exe started AFTER the child: the recorded
    # parent exited and its pid was reused, so this is not an ancestor.
    rows = [(1, 0, "claude.exe", 900), (2, 1, "python.exe", 100)]
    assert _walk(FakeProcessTable(rows), 2) is None


def test_equal_creation_time_is_still_an_ancestor():
    rows = [(1, 0, "claude.exe", 5), (2, 1, "python.exe", 5)]
    assert _walk(FakeProcessTable(rows), 2) == 1


def test_unreadable_creation_time_stops_the_walk():
    table = FakeProcessTable()
    del table.created[CLAUDE_PID]  # e.g. access denied on the parent
    assert _walk(table, HOOK_PID) is None


def test_row_that_is_its_own_parent_terminates():
    assert _walk(FakeProcessTable([(5, 5, "python.exe", 1)]), 5) is None


def test_cycle_terminates_at_depth_bound():
    rows = [(1, 2, "a.exe", 1), (2, 1, "b.exe", 1)]
    assert _walk(FakeProcessTable(rows), 1, depth=7) is None


def test_depth_bound_is_exact():
    # claude.exe is the 3rd parent edge from pid 4
    rows = [
        (1, 0, "claude.exe", 1),
        (2, 1, "a.exe", 2),
        (3, 2, "b.exe", 3),
        (4, 3, "c.exe", 4),
    ]
    table = FakeProcessTable(rows)
    assert _walk(table, 4, depth=3) == 1
    assert _walk(table, 4, depth=2) is None


def test_snapshot_failure_propagates_not_none():
    def broken():
        raise OSError(24, "Process32FirstW/NextW ended abnormally")

    with pytest.raises(OSError):
        pa.claude_ancestor_pid(HOOK_PID, _DEPTH, snapshot=broken, creation=lambda p: 1)


def test_start_signature_is_the_creation_filetime_text():
    assert pa.start_signature(20, creation=lambda pid: 133_000_000_000_000_000) == (
        "133000000000000000"
    )


def test_start_signature_none_when_process_gone():
    assert pa.start_signature(20, creation=lambda pid: None) is None


def test_start_signature_differs_for_a_recycled_pid():
    first = pa.start_signature(20, creation=lambda pid: 100)
    second = pa.start_signature(20, creation=lambda pid: 200)
    assert first != second


def test_cached_window_pid_resolves_once():
    calls = []

    def find():
        calls.append(1)
        return CLAUDE_PID

    assert pa.cached_window_pid(find) == CLAUDE_PID
    assert pa.cached_window_pid(find) == CLAUDE_PID
    assert calls == [1]


def test_cached_window_pid_never_caches_none():
    answers = iter([None, CLAUDE_PID])
    assert pa.cached_window_pid(lambda: next(answers)) is None
    assert pa.cached_window_pid(lambda: next(answers)) == CLAUDE_PID


def test_cached_window_pid_is_keyed_by_the_server_process(monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 111)
    assert pa.cached_window_pid(lambda: 1) == 1
    monkeypatch.setattr(os, "getpid", lambda: 222)
    assert pa.cached_window_pid(lambda: 2) == 2


def test_cached_window_pid_propagates_walk_failure():
    def broken():
        raise OSError("table unreadable")

    with pytest.raises(OSError):
        pa.cached_window_pid(broken)
