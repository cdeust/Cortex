"""Windows ancestor walk to the window's ``claude`` process.

Layer: infrastructure. Pure logic over an injected process table (the
``snapshot`` and ``creation`` callables default to the ``win32_process``
ctypes layer, resolved at call time), so the walk, the name match and the
pid-reuse guard are tested on every platform with a fake tree.

Why a Windows-specific walk (issue #665): ``ps`` is absent from Git Bash, the
executable is ``claude.exe``, and the MCP server's parent is ``cmd.exe``, not
``claude``. Measured on Windows 11, Git Bash: a hook runs ``claude.exe ->
bash.exe -> bash.exe -> bash.exe -> python.exe`` and the MCP server runs
``claude.exe -> cmd.exe -> python.exe``; above ``claude.exe`` sits the shared
desktop app, also named ``Claude.exe``, so only the NEAREST match is the
window's own CLI.

Before the walk, ``window_claude_pid`` reads ``CLAUDE_PID`` (issue #835): in a
real hook the walk can meet an intermediate ``bash.exe`` that has already
exited, and the chain is broken; the desktop app exports the window's
``claude.exe`` pid to the processes it starts.

source: ADR-1124 (walk: ADR-1096)"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from mcp_server.shared import win32_process
from mcp_server.shared.win32_process import ProcessRow

# source: GitHub issue cdeust/Cortex#665 (process names measured on Windows 11
#   Pro 26200 with Git Bash); Windows file names are case-insensitive
_CLAUDE_EXE_NAME = "claude.exe"

# source: GitHub issue cdeust/Cortex#835 (seen in desktop-app hooks, Claude
#   Code 2.1.289 to 2.1.309; 879 of 892 window lookups, 2026-10-21 to
#   2026-10-29, on the reporter's Windows host); not documented by the host,
#   so its value is checked against the process table before it is used
_CLAUDE_PID_ENV = "CLAUDE_PID"

Snapshot = Callable[[], list[ProcessRow]]
Creation = Callable[[int], int | None]


def _is_older_or_equal(parent_pid: int, child_pid: int, created: Creation) -> bool:
    """True iff both creation times are known and the parent is not younger.

    A parent must exist before its child; ``th32ParentProcessID`` is not
    updated when the parent exits, so a younger "parent" is a recycled pid
    and the edge is not an ancestry edge."""
    parent_time, child_time = created(parent_pid), created(child_pid)
    if parent_time is None or child_time is None:
        return False
    return parent_time <= child_time


def _walk(
    table: dict[int, ProcessRow], start_pid: int, max_depth: int, created: Creation
) -> int | None:
    """The ancestor walk of ``claude_ancestor_pid`` over an already read table."""
    current = table.get(start_pid)
    for _ in range(max_depth):
        if current is None:
            return None
        parent = table.get(current.ppid)
        if parent is None or parent.pid == current.pid:
            return None
        if not _is_older_or_equal(parent.pid, current.pid, created):
            return None
        # Name match only: a chain with just the shared desktop ``Claude.exe``
        # and no session CLI returns the desktop pid (ADR-1096 point 7).
        if parent.exe_name.lower() == _CLAUDE_EXE_NAME:
            return parent.pid
        current = parent
    return None


def claude_ancestor_pid(
    start_pid: int,
    max_depth: int,
    *,
    snapshot: Snapshot | None = None,
    creation: Creation | None = None,
) -> int | None:
    """Nearest ancestor of ``start_pid`` whose executable is ``claude.exe``.

    precondition: none. postcondition: returns that ancestor's pid, or None
    when ``start_pid`` is absent from the table, an ancestor is missing from
    it, an edge fails the creation-time check, the chain ends (a row whose
    parent is itself), or ``max_depth`` edges were followed without a match.
    invariant: each iteration follows exactly one parent edge; termination:
    at most ``max_depth`` iterations. ``OSError`` from the table reader
    propagates (a failed read is not "no ancestor").

    source: ADR-1096"""
    rows = (snapshot or win32_process.snapshot_rows)()
    created = creation or win32_process.creation_filetime
    return _walk({row.pid: row for row in rows}, start_pid, max_depth, created)


def _env_claude_pid(
    table: dict[int, ProcessRow],
    start_pid: int,
    environ: Mapping[str, str],
    created: Creation,
) -> int | None:
    """``CLAUDE_PID`` when it names a ``claude.exe`` not younger than ``start_pid``.

    A process created after ``start_pid`` cannot be the window that started
    it: that pid was recycled after the window's ``claude.exe`` exited."""
    if _CLAUDE_PID_ENV not in environ:
        return None
    try:
        pid = int(environ[_CLAUDE_PID_ENV])
    except ValueError:
        return None
    row = table.get(pid)
    if row is None or row.exe_name.lower() != _CLAUDE_EXE_NAME:
        return None
    return pid if _is_older_or_equal(pid, start_pid, created) else None


def window_claude_pid(
    start_pid: int,
    max_depth: int,
    *,
    environ: Mapping[str, str] | None = None,
    snapshot: Snapshot | None = None,
    creation: Creation | None = None,
) -> int | None:
    """The window's ``claude.exe`` pid: ``CLAUDE_PID`` first, then the walk.

    precondition: none. postcondition: returns ``CLAUDE_PID`` when it parses
    as an integer and names a live ``claude.exe`` row (case-insensitive) whose
    creation time is known and not later than ``start_pid``'s; otherwise the
    result of the ancestor walk of ``claude_ancestor_pid`` over the same
    table read. The table is read once. ``OSError`` from the reader propagates.

    source: ADR-1124 (walk: ADR-1096)"""
    rows = (snapshot or win32_process.snapshot_rows)()
    created = creation or win32_process.creation_filetime
    table = {row.pid: row for row in rows}
    env = os.environ if environ is None else environ
    from_env = _env_claude_pid(table, start_pid, env, created)
    if from_env is not None:
        return from_env
    return _walk(table, start_pid, max_depth, created)


def start_signature(pid: int, *, creation: Creation | None = None) -> str | None:
    """Opaque start-time token of ``pid``: its creation FILETIME as text.

    postcondition: None when the process is gone or unreadable; equal tokens
    mean the same process incarnation (pid reuse yields a different token).

    source: ADR-1096"""
    filetime = (creation or win32_process.creation_filetime)(pid)
    return None if filetime is None else str(filetime)


# source: ADR-1096 — per-process cache of the window claude pid
_window_pid_cache: dict[int, int] = {}


def cached_window_pid(find: Callable[[], int | None]) -> int | None:
    """The window's ``claude`` pid for THIS process, resolved by ``find`` once.

    postcondition: a non-None answer is cached for the process's lifetime (an
    ancestor's identity cannot change while this process runs, and this
    process is a descendant of that claude process, so it exits with it;
    ADR-1096 point 4); a None answer is never cached, so a transient miss cannot poison
    later calls. ``OSError`` from ``find`` propagates.

    source: ADR-1096"""
    own_pid = os.getpid()
    cached = _window_pid_cache.get(own_pid)
    if cached is None:
        cached = find()
        if cached is not None:
            _window_pid_cache[own_pid] = cached
    return cached
