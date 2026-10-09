"""A fake Windows process table for the ancestor-walk tests (issue #665).

Shared by ``test_process_ancestry.py`` and ``test_session_registry_windows.py``
so the walk, the name match and the caching are exercised on every platform
without a Windows host. Rows are ``(pid, ppid, exe_name, creation_filetime)``.

source: ADR-1096"""

from __future__ import annotations

from mcp_server.shared.win32_process import ProcessRow

# Process trees measured on Windows 11 Pro 26200 with Git Bash (issue #665):
#   hook:   Claude.exe(10, shared desktop app) -> claude.exe(20) -> bash.exe(30)
#           -> bash.exe(31) -> bash.exe(32) -> python.exe(40)
#   server: claude.exe(20) -> cmd.exe(50) -> python.exe(60)
# Creation times grow with depth: a parent is always older than its child.
WINDOWS_WINDOW_TREE = [
    (10, 1, "Claude.exe", 100),
    (20, 10, "claude.exe", 200),
    (30, 20, "bash.exe", 300),
    (31, 30, "bash.exe", 310),
    (32, 31, "bash.exe", 320),
    (40, 32, "python.exe", 400),
    (50, 20, "cmd.exe", 500),
    (60, 50, "python.exe", 600),
]
# source: the pid of python.exe in the hook chain of WINDOWS_WINDOW_TREE
HOOK_PID = 40
# source: the pid of python.exe in the MCP server chain of WINDOWS_WINDOW_TREE
SERVER_PID = 60
# source: the pid of the nearest claude.exe in WINDOWS_WINDOW_TREE
CLAUDE_PID = 20
# source: the pid of the shared desktop Claude.exe in WINDOWS_WINDOW_TREE
DESKTOP_PID = 10


class FakeProcessTable:
    """Injectable ``snapshot`` and ``creation`` callables over fixed rows."""

    def __init__(self, rows=WINDOWS_WINDOW_TREE) -> None:
        self.rows = list(rows)
        self.created = {pid: created for pid, _p, _n, created in self.rows}
        self.snapshot_calls = 0

    def snapshot(self) -> list[ProcessRow]:
        self.snapshot_calls += 1
        return [ProcessRow(pid, ppid, name) for pid, ppid, name, _c in self.rows]

    def creation(self, pid: int) -> int | None:
        return self.created.get(pid)
