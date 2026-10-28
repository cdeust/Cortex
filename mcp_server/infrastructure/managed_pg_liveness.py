"""Whether the postmaster a ``running`` status names still lives, and the wait
for the supervisor's answer when it does not — stdlib, POSIX, no timer.

``status.json`` says ``running`` from the moment the supervisor proved the
postmaster until it writes something else. If the postmaster dies in between,
the supervisor restarts it (``managed_pg_supervisor``), but a client reading
the status right after the death would get a dead URL. So a client checks the
recorded postmaster with kernel facts (PID alive as this user, same kernel
start time) and, when it is gone, waits for the next change in the root
directory (a new ``postmaster.json`` or ``status.json``) or for the
supervisor's exit, then looks again.

source: ADR-1114
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp_server.infrastructure import managed_pg_process as _process


def _record(root: Path, name: str) -> dict:
    import json  # noqa: PLC0415 — only here

    try:
        return json.loads((root / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def postmaster_alive(root: Path) -> bool:
    """Whether the postmaster ``postmaster.json`` records still runs."""
    record = _record(root, "postmaster.json")
    pid = record.get("pid")
    if not isinstance(pid, int) or not _process.alive_as_this_user(pid):
        return False
    return _process.started(pid) == record.get("started")


def await_change(root: Path, status: dict) -> None:
    """Block until the root directory changes or the supervisor exits; return
    at once when the postmaster lives again or ``status.json`` already moved
    on from ``status`` (both re-read after the watch is armed)."""
    gone = _process.released(root / "supervisor.lock", shared=True)
    watch = _process.watch(root, gone)
    try:
        if not postmaster_alive(root) and _record(root, "status.json") == status:
            watch.wait()
    finally:
        watch.close()
        os.close(gone)
