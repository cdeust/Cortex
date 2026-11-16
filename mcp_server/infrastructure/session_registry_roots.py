"""Project roots of the live Claude windows (issue #711, slice 3a).

The code-graph cache eviction (slice 3b) must never remove a graph in use. A
graph is in use when its recorded root (``cortex-root.json``) is the project of
a live window. ``write_session`` records that project in each window's registry
entry; this module reads it back.

A live entry with no recorded root (written before this slice, or by a hook
whose event carried no project) makes the set unknown: ``live_project_roots``
returns None, and a caller must then evict nothing.

source: issue #711 (decision comment of 2026-11-15), ADR-0597 (lineage rule)"""

from __future__ import annotations

from pathlib import Path

from mcp_server.infrastructure import session_registry
from mcp_server.infrastructure.file_io import read_json
from mcp_server.shared.process_liveness import pid_alive


def live_entry(entry: Path) -> dict | None:
    """Data of registry file ``entry`` if it names a live window (pid alive,
    start signature unchanged: a recycled pid is not the window), else None.

    source: ADR-0597"""
    try:
        pid = int(entry.stem)
    except ValueError:
        return None
    if entry.suffix != ".json" or not pid_alive(pid):
        return None
    data = read_json(entry)
    if not isinstance(data, dict) or data.get("v") != session_registry._SCHEMA_VERSION:
        return None
    if data.get("claude_pid") != pid:
        return None
    recorded = data.get("claude_start_time")
    # Read through the module so a test that fakes the probe fakes it here too.
    current = session_registry._process_start_signature(pid)
    return data if recorded is not None and recorded == current else None


def live_project_roots() -> frozenset[str] | None:
    """The resolved project roots of every live window, or None when unknown.

    postcondition: a missing registry directory yields an empty set (no window
    registered); an unreadable one, or a live entry without a ``project_root``,
    yields None. Dead, recycled and malformed entries are skipped.

    source: issue #711"""
    try:
        entries = list(session_registry.registry_dir().iterdir())
    except FileNotFoundError:
        return frozenset()
    except OSError:
        return None
    roots: set[str] = set()
    for entry in entries:
        data = live_entry(entry)
        if data is None:
            continue
        root = data.get("project_root")
        if not isinstance(root, str) or not root:
            return None
        roots.add(root)
    return frozenset(roots)
