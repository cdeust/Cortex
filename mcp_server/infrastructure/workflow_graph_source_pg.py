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
_COMMAND_LINE_RE = re.compile(r"\*\*Command:\*\*\s*`([^`]+)`")
_PATH_TOKEN_RE = re.compile(r"(?:^|\s)((?:\.{1,2}/|~/|/)[^\s`'\"]{3,})")

_MEMORY_PASSTHROUGH_KEYS = tuple((
    "heat_base arousal emotional_valence dominant_emotion importance "
    "surprise_score confidence access_count useful_count replay_count "
    "reconsolidation_count plasticity stability excitability "
    "hippocampal_dependency schema_match_score schema_id separation_index "
    "interference_score encoding_strength hours_in_stage stage_entered_at "
    "no_decay is_protected is_stale is_benchmark is_global store_type "
    "last_accessed created_at compression_level compressed tags"
).split())


def load_tool_events(pg_store, tool_from_tags, domain_from_directory,
                     cmd_hash, first_line) -> list[dict[str, Any]]:
    """Parse post_tool_capture memories → (tool, file_path, domain, count)."""
    _ = cmd_hash; _ = first_line   # unused here, present for loader parity
    rows = pg_store.search_by_tag_vector(
        query_embedding=None, tag="auto-captured",
        domain=None, min_heat=0.0, limit=10000,
    )
    buckets: dict[tuple[str, str | None, str], int] = {}
    for mem in rows:
        tool = tool_from_tags(mem.get("tags") or [])
        if not tool:
            continue
        domain = mem.get("domain") or domain_from_directory(
            mem.get("directory_context")
        ) or ""
        content = mem.get("content") or ""
        file_path: str | None = None
        if tool in ("Edit", "Write", "Read"):
            m = _FILE_LINE_RE.search(content)
            if m:
                file_path = m.group(1).strip() or None
        key = (tool, file_path, domain)
        buckets[key] = buckets.get(key, 0) + 1
    return [
        {"tool": t, "file_path": fp, "domain": d, "count": n}
        for (t, fp, d), n in buckets.items()
    ]


def load_command_events(pg_store, domain_from_directory,
                        cmd_hash, first_line) -> list[dict[str, Any]]:
    """Parse Bash command memories; cmd_hash = sha1[:12] of first line."""
    rows = pg_store.search_by_tag_vector(
        query_embedding=None, tag="tool:bash",
        domain=None, min_heat=0.0, limit=5000,
    )
    buckets: dict[tuple[str, str, str], int] = {}
    for mem in rows:
        m = _COMMAND_LINE_RE.search(mem.get("content") or "")
        if not m:
            continue
        cmd = first_line(m.group(1))
        if not cmd:
            continue
        h = cmd_hash(cmd)
        dom = mem.get("domain") or domain_from_directory(
            mem.get("directory_context")
        ) or ""
        key = (cmd, h, dom)
        buckets[key] = buckets.get(key, 0) + 1
    return [
        {"cmd": c, "cmd_hash": h, "domain": d, "count": n}
        for (c, h, d), n in buckets.items()
    ]


def load_command_files(pg_store, known_paths: Iterable[str],
                       cmd_hash, first_line) -> list[dict[str, Any]]:
    """Extract absolute paths from bash commands; retain only those that
    match a known file node — prevents edge spam to non-graph paths."""
    known = set(known_paths)
    if not known:
        return []
    rows = pg_store.search_by_tag_vector(
        query_embedding=None, tag="tool:bash",
        domain=None, min_heat=0.0, limit=5000,
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
        {"cmd_hash": h, "file_path": f, "count": n}
        for (h, f), n in buckets.items()
    ]


def load_memories(pg_store, min_heat: float = 0.0,
                  limit: int = 10000) -> list[dict[str, Any]]:
    """Return every memory row for the graph with its scientific fields."""
    rows = pg_store.get_hot_memories(
        min_heat=min_heat, limit=limit, include_benchmarks=True,
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
