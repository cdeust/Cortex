"""Per-window session registry — T2-handlers increment H1 (foundation).

Windows (issue #665, ADR-1096): an unreadable process table or an undocumented
``OpenProcess`` error raises ``OSError`` from the functions that resolve a pid
or probe liveness. Hooks and handlers log it; ``scripts/groomer.py`` has no
handler, so a manual Windows run ends in a traceback and a nonzero exit.

source: ADR-1096 (Windows; POSIX: ADR-0597)"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from mcp_server.infrastructure import process_ancestry
from mcp_server.infrastructure.file_io import read_json
from mcp_server.shared import platform as host_platform
from mcp_server.shared.process_liveness import pid_alive as _pid_alive

# source: ADR-0597
_SCHEMA_VERSION = 1

# source: ADR-0597
_MAX_ANCESTOR_DEPTH = 15

# source: ADR-0597
_PS_TIMEOUT_S = 1.0

# source: ADR-0597
_PPID_COMM_PARTS = 2


def registry_dir() -> Path:
    """Return the session registry directory.

    source: ADR-0597"""
    return Path.home() / ".cache" / "cortex" / "session-registry"


def registry_path(claude_pid: int) -> Path:
    """Registry file for one window, keyed by its ``claude`` pid."""
    return registry_dir() / f"{claude_pid}.json"


# source: ADR-0597
_start_signature_cache: dict[int, str] = {}


def _cached_process_start_signature(pid: int) -> str | None:
    """Process-lifetime cache wrapper around ``_process_start_signature``.

    postcondition: same value as ``_process_start_signature(pid)``, read at
        most once per distinct ``pid`` for this server's lifetime. Windows
        keeps the cache too: the server is a descendant of the claude
        process and exits with it, so the pid cannot be recycled under a
        live server (ADR-1096 point 4).

    source: ADR-1096 (Windows; POSIX: ADR-0597)"""
    cached = _start_signature_cache.get(pid)
    if cached is not None:
        return cached
    sig = _process_start_signature(pid)
    if sig is not None:
        _start_signature_cache[pid] = sig
    return sig


def _process_start_signature(pid: int) -> str | None:
    """Opaque per-process start-time token.

    source: ADR-1096 (Windows branch; POSIX: ADR-0597)"""
    if host_platform.IS_WINDOWS:
        return process_ancestry.start_signature(pid)
    stat_path = Path(f"/proc/{pid}/stat")
    if stat_path.exists():
        try:
            raw = stat_path.read_text(encoding="utf-8")
            after_comm = raw.rsplit(")", 1)[1]
            fields = after_comm.split()
            return fields[19]  # field 22 overall = index 19 after comm+state
        except (OSError, IndexError, ValueError):
            return None
    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            encoding="utf-8",  # POSIX ps, whose locale is UTF-8 (PEP 540)
            timeout=_PS_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = out.stdout.strip()
    return line or None


def _ppid_and_comm(pid: int) -> tuple[int, str] | None:
    """One ancestor-walk step: ``(parent pid, comm)`` of ``pid``, or
    None on any probe failure (dead pid, unsupported platform)."""
    try:
        out = subprocess.run(
            ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
            capture_output=True,
            text=True,
            encoding="utf-8",  # POSIX ps, whose locale is UTF-8 (PEP 540)
            timeout=_PS_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    parts = out.stdout.strip().split(None, 1)
    if len(parts) != _PPID_COMM_PARTS:
        return None
    try:
        ppid = int(parts[0])
    except ValueError:
        return None
    return ppid, parts[1].strip()


def find_claude_ancestor(max_depth: int = _MAX_ANCESTOR_DEPTH) -> int | None:
    """Walk ancestors from os.getppid() and return the nearest process named
    claude. Return None on probe failure, reaching a root process, or exhausting
    max_depth. Intended for hook processes.

    source: ADR-1096 (Windows branch; POSIX: ADR-0597)"""
    if host_platform.IS_WINDOWS:
        return process_ancestry.claude_ancestor_pid(os.getpid(), max_depth)
    pid = os.getppid()
    for _ in range(max_depth):
        info = _ppid_and_comm(pid)
        if info is None:
            return None
        ppid, comm = info
        if os.path.basename(comm) == "claude":
            return pid
        if ppid <= 1:
            return None
        pid = ppid
    return None


def _atomic_write(path: Path, payload: dict) -> bool:
    """Atomically write payload as JSON to path. Return False on write failure.

    source: ADR-0597"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".tmp.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception:
            os.unlink(tmp)
            raise
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def write_session(session_id: str | None, *, claude_pid: int | None = None) -> bool:
    """Write/refresh this window's registry entry (writer side, H2).

    precondition: ``session_id`` is the transcript-stem identity the caller
    already computed (``session_id_from_transcript`` in
    ``handlers/injection_receipts.py`` — this module does not derive it, T2-D1);
    ``claude_pid``, if given, is a pre-resolved ancestor pid, else resolved here
    via ``find_claude_ancestor()``. postcondition: on success,
    ``registry_path(claude_pid)`` exists, holds valid JSON ``{v, session_id,
    claude_pid, claude_start_time, updated_at}``, replaced atomically. Returns
    False without writing when the ancestor pid or its start signature cannot be
    resolved. ``session_id=None`` writes a TOMBSTONE: entry stays present, valid
    lineage, but reads as no-session.

    source: ADR-0597"""
    pid = claude_pid if claude_pid is not None else find_claude_ancestor()
    if pid is None:
        return False
    start_sig = _process_start_signature(pid)
    if start_sig is None:
        return False
    payload = {
        "v": _SCHEMA_VERSION,
        "session_id": session_id,
        "claude_pid": pid,
        "claude_start_time": start_sig,
        "updated_at": time.time(),
    }
    return _atomic_write(registry_path(pid), payload)


def tombstone(claude_pid: int) -> bool:
    """Clear the active session identity for claude_pid while retaining the
    registry entry and process lineage. Repeated calls are idempotent.

    source: ADR-0597"""
    return write_session(None, claude_pid=claude_pid)


def _window_claude_pid() -> int | None:
    """The ``claude`` pid of this MCP server's window: ``os.getppid()`` on
    POSIX; on Windows (server parent is ``cmd.exe``) the nearest
    ``claude.exe`` ancestor, cached per server process.

    source: ADR-1096"""
    if not host_platform.IS_WINDOWS:
        return os.getppid()
    return process_ancestry.cached_window_pid(find_claude_ancestor)


def current_window_session() -> str | None:
    """Return the current MCP server window session identity, or None when no valid
    session is registered. Called from the MCP server process (see
    ``_window_claude_pid`` for how its window is found). Rejects missing,
    unreadable, malformed, tombstoned, or stale-lineage registry entries.

    source: ADR-1096 (Windows branch; POSIX: ADR-0597)"""
    claude_pid = _window_claude_pid()
    if claude_pid is None:
        return None
    data = read_json(registry_path(claude_pid))
    if not isinstance(data, dict):
        return None
    if data.get("v") != _SCHEMA_VERSION:
        return None
    if data.get("claude_pid") != claude_pid:
        return None
    if not _pid_alive(claude_pid):
        return None
    recorded_start = data.get("claude_start_time")
    current_start = _cached_process_start_signature(claude_pid)
    if current_start is None or recorded_start != current_start:
        return None
    session_id = data.get("session_id")
    return session_id if isinstance(session_id, str) and session_id else None


def purge_dead_entries() -> int:
    """Delete registry files whose ``claude_pid`` is no longer alive
        (T2-D11, prior art ``viz_instance.py``'s pid-dead invalidation).
        Exposed for H2 to call from the SessionStart hook. No daemon, no
        TTL: the only leak is a closed window's file.

    postcondition: returns count of files removed; raises no I/O error (an
        unreadable directory or file is skipped) — Windows: see module note.

    source: ADR-1096 (Windows branch; POSIX: ADR-0597)"""
    removed = 0
    d = registry_dir()
    try:
        entries = list(d.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if entry.suffix != ".json":
            continue
        try:
            pid = int(entry.stem)
        except ValueError:
            continue
        if not _pid_alive(pid):
            try:
                entry.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def has_active_session_window() -> bool:
    """Precondition: none. Postcondition: scans every ``registry_dir()`` entry;
    True on the first live ``claude_pid`` whose entry has a non-empty
    ``session_id``. Windows: may raise ``OSError`` (see module note).

    source: ADR-1096 (Windows branch; POSIX: ADR-0597)"""
    d = registry_dir()
    try:
        entries = list(d.iterdir())
    except OSError:
        return False
    for entry in entries:
        if entry.suffix != ".json":
            continue
        try:
            pid = int(entry.stem)
        except ValueError:
            continue
        if not _pid_alive(pid):
            continue
        data = read_json(entry)
        if not isinstance(data, dict) or data.get("v") != _SCHEMA_VERSION:
            continue
        session_id = data.get("session_id")
        if isinstance(session_id, str) and session_id:
            return True
    return False
