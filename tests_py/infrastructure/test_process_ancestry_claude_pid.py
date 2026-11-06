"""``CLAUDE_PID`` before the ancestor walk on Windows (issue #835).

Runs on every platform over a fake process table: the environment value is
checked against the table (integer, ``claude.exe``, not younger than the
caller) before it is used, and the walk answers when it is rejected.

source: ADR-1124"""

from __future__ import annotations

from mcp_server.infrastructure import process_ancestry as pa
from tests_py.infrastructure.process_table_fakes import (
    CLAUDE_PID,
    HOOK_PID,
    FakeProcessTable,
)

# source: session_registry._MAX_ANCESTOR_DEPTH (ADR-0597, design T2-D3)
_DEPTH = 15

# The real-hook chain of #835: python.exe(3) <- bash.exe(2) <- exited pid 77;
# the window's claude.exe(1) is alive but no longer reachable by the walk.
_BROKEN_CHAIN = [
    (1, 0, "claude.exe", 100),
    (2, 77, "bash.exe", 200),
    (3, 2, "python.exe", 300),
]


def _resolve(table, start, environ):
    return pa.window_claude_pid(
        start,
        _DEPTH,
        environ=environ,
        snapshot=table.snapshot,
        creation=table.creation,
    )


def test_claude_pid_names_the_window_when_the_chain_is_broken():
    table = FakeProcessTable(_BROKEN_CHAIN)
    walk = pa.claude_ancestor_pid(
        3, _DEPTH, snapshot=table.snapshot, creation=table.creation
    )
    assert walk is None
    assert _resolve(table, 3, {"CLAUDE_PID": "1"}) == 1


def test_without_claude_pid_the_walk_answers():
    assert _resolve(FakeProcessTable(), HOOK_PID, {}) == CLAUDE_PID
    assert _resolve(FakeProcessTable(_BROKEN_CHAIN), 3, {}) is None


def test_claude_pid_that_is_not_an_integer_is_ignored():
    assert _resolve(FakeProcessTable(), HOOK_PID, {"CLAUDE_PID": "x"}) == CLAUDE_PID
    assert _resolve(FakeProcessTable(_BROKEN_CHAIN), 3, {"CLAUDE_PID": ""}) is None


def test_claude_pid_naming_another_program_is_ignored():
    # pid 2 is bash.exe: a recycled pid held by another executable
    assert _resolve(FakeProcessTable(_BROKEN_CHAIN), 3, {"CLAUDE_PID": "2"}) is None


def test_claude_pid_absent_from_the_table_is_ignored():
    table = FakeProcessTable()
    assert _resolve(table, HOOK_PID, {"CLAUDE_PID": "9999"}) == CLAUDE_PID


def test_claude_pid_younger_than_the_caller_is_a_recycled_pid():
    # claude.exe(1) was created after the hook (300): it cannot have started it
    rows = [
        (1, 0, "claude.exe", 900),
        (2, 77, "bash.exe", 200),
        (3, 2, "python.exe", 300),
    ]
    assert _resolve(FakeProcessTable(rows), 3, {"CLAUDE_PID": "1"}) is None


def test_unreadable_creation_time_rejects_claude_pid():
    table = FakeProcessTable(_BROKEN_CHAIN)
    del table.created[3]  # the caller's own creation time cannot be read
    assert _resolve(table, 3, {"CLAUDE_PID": "1"}) is None


def test_claude_pid_match_is_case_insensitive():
    rows = [(1, 0, "CLAUDE.EXE", 100), (3, 77, "python.exe", 300)]
    assert _resolve(FakeProcessTable(rows), 3, {"CLAUDE_PID": "1"}) == 1


def test_the_table_is_read_once():
    table = FakeProcessTable(_BROKEN_CHAIN)
    _resolve(table, 3, {"CLAUDE_PID": "2"})  # rejected, then walked
    assert table.snapshot_calls == 1
