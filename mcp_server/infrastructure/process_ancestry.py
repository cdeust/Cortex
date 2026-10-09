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

source: ADR-1096"""

from __future__ import annotations

import os
from collections.abc import Callable

from mcp_server.shared import win32_process
from mcp_server.shared.win32_process import ProcessRow

# source: GitHub issue cdeust/Cortex#665 (process names measured on Windows 11
#   Pro 26200 with Git Bash); Windows file names are case-insensitive
_CLAUDE_EXE_NAME = "claude.exe"

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
    table = {row.pid: row for row in rows}
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


def start_signature(pid: int, *, creation: Creation | None = None) -> str | None:
    """Opaque start-time token of ``pid``: its creation FILETIME as text.

    postcondition: None when the process is gone or unreadable; equal tokens
    mean the same process incarnation (pid reuse yields a different token).

    source: ADR-1096"""
    filetime = (creation or win32_process.creation_filetime)(pid)
    return None if filetime is None else str(filetime)


# source: ADR-1096
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
