"""PostgreSQL-backed loaders for the workflow graph.

Extracts tool events, bash commands, command-to-file touches, and
memory rows from the PG store. Pure infrastructure — no core imports.
Split out of ``workflow_graph_source`` to keep that module under the
300-line project ceiling.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

_FILE_LINE_RE = re.compile(r"\*\*(?:File|Read):\*\*\s*`([^`]+)`")
# Grep / Glob memory bodies: ``**Grep:** `<pattern>` in `<path>`` and
# ``**Glob:** `<pattern>` (root=`<path>`)``. We extract the search root
# so at minimum the directory appears as a file node — the exact
# matched files come through separately via JSONL tool_uses.
_GREP_ROOT_RE = re.compile(r"\*\*Grep:\*\*\s*`[^`]*`\s+in\s+`([^`]+)`")
_GLOB_ROOT_RE = re.compile(r"\*\*Glob:\*\*\s*`[^`]*`\s*\(root=`([^`]+)`\)")
_COMMAND_LINE_RE = re.compile(r"\*\*Command:\*\*\s*`([^`]+)`")
_PATH_TOKEN_RE = re.compile(r"(?:^|\s)((?:\.{1,2}/|~/|/)[^\s`'\"]{3,})")

_MEMORY_PASSTHROUGH_KEYS = tuple(
    (
        "heat_base arousal emotional_valence dominant_emotion importance "
        "surprise_score confidence access_count useful_count replay_count "
        "reconsolidation_count plasticity stability excitability "
        "hippocampal_dependency schema_match_score schema_id separation_index "
        "interference_score encoding_strength hours_in_stage stage_entered_at "
        "no_decay is_protected is_stale is_benchmark is_global store_type "
        "last_accessed created_at compression_level compressed tags"
    ).split()
)


def load_tool_events(
    pg_store, tool_from_tags, domain_from_directory, cmd_hash, first_line
) -> list[dict[str, Any]]:
    """Parse post_tool_capture memories → one row per (tool, file_path,
    domain) with count + first/last timestamps so file nodes can expose
    a full access history."""
    _ = cmd_hash
    _ = first_line  # unused here, present for loader parity
    rows = pg_store.search_by_tag_vector(
        query_embedding=None,
        tag="auto-captured",
        domain=None,
        min_heat=0.0,
        limit=10**9,  # effectively unbounded
    )
    # bucket value: [count, first_ts, last_ts]  (ts = ISO string)
    buckets: dict[tuple[str, str | None, str], list] = {}
    for mem in rows:
        tool = tool_from_tags(mem.get("tags") or [])
        if not tool:
            continue
        domain = (
            mem.get("domain")
            or domain_from_directory(mem.get("directory_context"))
            or ""
        )
        content = mem.get("content") or ""
        file_path: str | None = None
        if tool in ("Edit", "Write", "Read"):
            m = _FILE_LINE_RE.search(content)
            if m:
                file_path = m.group(1).strip() or None
        ts = _iso(mem.get("created_at"))
        key = (tool, file_path, domain)
        slot = buckets.get(key)
        if slot is None:
            buckets[key] = [1, ts, ts]
        else:
            slot[0] += 1
            if ts and (slot[1] is None or ts < slot[1]):
                slot[1] = ts
            if ts and (slot[2] is None or ts > slot[2]):
                slot[2] = ts
    return [
        {
            "tool": t,
            "file_path": fp,
            "domain": d,
            "count": n,
            "first_ts": first,
            "last_ts": last,
        }
        for (t, fp, d), (n, first, last) in buckets.items()
    ]


def _iso(ts) -> str | None:
    """Render a timestamp-ish value as an ISO string, or None."""
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        try:
            return ts.isoformat()
        except (TypeError, ValueError):
            return None
    return str(ts)


def load_command_events(
    pg_store, domain_from_directory, cmd_hash, first_line
) -> list[dict[str, Any]]:
    """Parse Bash command memories; one row per (cmd, hash, domain) with
    count + first/last timestamps."""
    rows = pg_store.search_by_tag_vector(
        query_embedding=None,
        tag="tool:bash",
        domain=None,
        min_heat=0.0,
        limit=10**9,
    )
    buckets: dict[tuple[str, str, str], list] = {}
    for mem in rows:
        m = _COMMAND_LINE_RE.search(mem.get("content") or "")
        if not m:
            continue
        cmd = first_line(m.group(1))
        if not cmd:
            continue
        h = cmd_hash(cmd)
        dom = (
            mem.get("domain")
            or domain_from_directory(mem.get("directory_context"))
            or ""
        )
        ts = _iso(mem.get("created_at"))
        key = (cmd, h, dom)
        slot = buckets.get(key)
        if slot is None:
            buckets[key] = [1, ts, ts]
        else:
            slot[0] += 1
            if ts and (slot[1] is None or ts < slot[1]):
                slot[1] = ts
            if ts and (slot[2] is None or ts > slot[2]):
                slot[2] = ts
    return [
        {
            "cmd": c,
            "cmd_hash": h,
            "domain": d,
            "count": n,
            "first_ts": first,
            "last_ts": last,
        }
        for (c, h, d), (n, first, last) in buckets.items()
    ]


def load_command_files(
    pg_store, known_paths: Iterable[str], cmd_hash, first_line
) -> list[dict[str, Any]]:
    """Extract absolute paths from bash commands; retain only those that
    match a known file node — prevents edge spam to non-graph paths."""
    known = set(known_paths)
    if not known:
        return []
    rows = pg_store.search_by_tag_vector(
        query_embedding=None,
        tag="tool:bash",
        domain=None,
        min_heat=0.0,
        limit=10**9,
    )
    buckets: dict[tuple[str, str], int] = {}
    for mem in rows:
        m = _COMMAND_LINE_RE.search(mem.get("content") or "")
        if not m:
            continue
        cmd = first_line(m.group(1))
        if not cmd:
            continue
        h = cmd_hash(cmd)
        for pm in _PATH_TOKEN_RE.finditer(" " + cmd):
            tok = pm.group(1).rstrip(".,;:)")
            if tok in known:
                key = (h, tok)
                buckets[key] = buckets.get(key, 0) + 1
    return [
        {"cmd_hash": h, "file_path": f, "count": n} for (h, f), n in buckets.items()
    ]


def load_memories(
    pg_store, min_heat: float = 0.0, limit: int = 10000
) -> list[dict[str, Any]]:
    """Return every memory row for the graph with its scientific fields."""
    rows = pg_store.get_hot_memories(
        min_heat=min_heat,
        limit=limit,
        include_benchmarks=True,
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        row_dict: dict[str, Any] = {
            "id": r.get("id"),
            "domain": r.get("domain") or "",
            "consolidation_stage": r.get("consolidation_stage") or "episodic",
            "heat": float(r.get("heat") or r.get("heat_base") or 0.0),
            "content": r.get("content") or "",
        }
        for k in _MEMORY_PASSTHROUGH_KEYS:
            if k in r and r[k] is not None:
                row_dict[k] = r[k]
        out.append(row_dict)
    return out


def load_entities(pg_store, min_heat: float = 0.05) -> list[dict[str, Any]]:
    """Return knowledge-graph entity rows suitable for ENTITY-node ingest.

    Uses ``get_all_entities`` with ``include_archived=False`` so archived
    entities stay out of the graph. Each row carries ``id / name / type
    / domain / heat`` at minimum; extra columns pass through so the
    panel renderer can surface them.
    """
    if not hasattr(pg_store, "get_all_entities"):
        return []
    rows = pg_store.get_all_entities(min_heat=min_heat, include_archived=False)
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.get("id") is None or not r.get("name"):
            continue
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "type": r.get("type") or "concept",
                "domain": r.get("domain") or "",
                "heat": float(r.get("heat") or 0.0),
            }
        )
    return out


def load_memory_entity_edges(pg_store) -> list[dict[str, Any]]:
    """Bulk-fetch every row in ``memory_entities``.

    Shape: ``[{memory_id: int, entity_id: int}, ...]``. The builder
    synthesises one ``ABOUT_ENTITY`` edge per row after verifying that
    both endpoints are already in the graph (memories below
    ``min_heat`` and archived entities are silently skipped)."""
    if not hasattr(pg_store, "_execute"):
        return []
    try:
        rows = pg_store._execute(
            "SELECT memory_id, entity_id FROM memory_entities"
        ).fetchall()
    except Exception:
        return []
    return [
        {"memory_id": r["memory_id"], "entity_id": r["entity_id"]}
        for r in rows
        if r.get("memory_id") is not None and r.get("entity_id") is not None
    ]
