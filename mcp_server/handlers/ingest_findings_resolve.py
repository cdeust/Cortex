"""output_dir resolution for ingest_findings (INC5.1 design D2, iface Q3.1).

Priority order (explicit beats inferred):
  1. ``output_dir`` argument — absolute path, used as-is.
  2. ``graph_key`` argument — looked up as a ``_code_graph:<graph_key>``
     protected memory (the same tag ``ingest_codebase`` writes via
     ``ingest_helpers.memoise_graph_path``); output_dir = graph_path's
     parent directory (AP's own convention: graph lives at
     ``<output_dir>/graph``, confirmed in ingest_codebase_graph.py:96-98).
  3. Roster scan — ``ap_bridge.resolve_graph_paths()`` (both directory
     schemes AP/ingest_codebase are known to write under), output_dir =
     each candidate's parent, first one with a
     ``runs/<run_id>/`` subdirectory wins.

Infra: touches MemoryStore (protected-memory lookup) + the filesystem.
No PostgreSQL wiki writes here — pure resolution.
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.infrastructure import ap_bridge
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.observability import silent_failure


def _from_graph_key(store: MemoryStore, graph_key: str) -> Path | None:
    tag = f"_code_graph:{graph_key}"
    try:
        mems = store.get_memories_by_tag(tag, limit=5)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("ingest_findings.graph_key_lookup", exc)
        return None
    for mem in mems:
        content = mem.get("content") or ""
        if content.startswith("graph_path="):
            graph_path = content[len("graph_path=") :].strip()
            if graph_path:
                return Path(graph_path).expanduser().parent
    return None


def _from_roster(run_id: str) -> Path | None:
    for graph_path in ap_bridge.resolve_graph_paths():
        candidate = Path(graph_path).expanduser().parent
        if (candidate / "runs" / run_id).is_dir():
            return candidate
    return None


def resolve_output_dir(
    store: MemoryStore, *, run_id: str, output_dir: str | None, graph_key: str | None
) -> Path | None:
    """Return the AP output_dir to read ``runs/<run_id>/`` from, or None.

    Postcondition: the returned path, if not None, either was supplied
    explicitly or was verified to contain ``runs/<run_id>/`` on disk
    (roster path). The explicit and graph_key paths are NOT existence-
    checked here — the caller's index.json read surfaces a clear
    "not found" error instead of a silent resolution failure.
    """
    if output_dir:
        return Path(output_dir).expanduser()
    if graph_key:
        resolved = _from_graph_key(store, graph_key)
        if resolved is not None:
            return resolved
    return _from_roster(run_id)
