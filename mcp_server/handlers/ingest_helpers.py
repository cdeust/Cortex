"""Shared helpers for ingest_codebase and ingest_prd handlers.

Two concerns live here:

1. Graph-path memoisation — after a codebase analysis, the returned
   graph_path is stored as a protected Cortex memory tagged
   ``_code_graph:<project-id>`` so subsequent ingest runs can reuse
   the same graph without re-indexing.

2. Safe MCP calls — wraps mcp_client_pool.get_client + call with a
   uniform error shape so ingest handlers don't each re-derive the
   try/except boilerplate.
"""

from __future__ import annotations

from datetime import date, datetime

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from mcp_server.infrastructure.mcp_client_pool import get_client
from mcp_server.infrastructure.upstream_governor import govern
from mcp_server.observability import silent_failure

CODE_GRAPH_TAG_PREFIX = "_code_graph:"


def project_key(project_path: str) -> str:
    """Stable project key = last path segment + short hash of full path."""
    p = Path(project_path).expanduser().resolve()
    digest = hashlib.sha256(str(p).encode("utf-8")).hexdigest()[:8]
    return f"{p.name}-{digest}"


def code_graph_tag(project_path: str) -> str:
    """Canonical tag used to memoise a code graph path for a project."""
    return f"{CODE_GRAPH_TAG_PREFIX}{project_key(project_path)}"


def graph_path_is_materialised(graph_path: str | None) -> bool:
    """True when ``graph_path`` points at a graph that still exists on disk.

    AP writes ``<output_dir>/graph`` as a LadybugDB directory; pre-3.14
    builds wrote a single file at the same slot. Either form counts as
    valid only when **non-empty** — an existing-but-empty directory is a
    half-built or wiped graph, which must read as a cache miss so the
    caller re-analyses rather than silently projecting zero symbols.

    source: ingest staleness bug Jun-2026 — a memo outlived its graph
    (the graph directory was deleted) and ``find_cached_graph`` handed the
    dead path straight back to ``ensure_graph``, which then projected an
    empty graph. A memo must never outlive the artefact it points at
    (Dijkstra audit: the pointer is not the thing).
    """
    if not graph_path:
        return False
    try:
        p = Path(graph_path).expanduser()
        if not p.exists():
            return False
        if p.is_dir():
            return any(p.iterdir())
        return p.stat().st_size > 0
    except OSError:
        return False


def _memo_tags(mem: dict) -> list:
    """Tags of a memory row as a list (rows may store JSON-encoded tags)."""
    raw = mem.get("tags", [])
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    return raw if isinstance(raw, list) else []


def _memo_recency_key(mem: dict) -> str:
    """Sortable recency key for a memo row (most-recent sorts highest).

    Prefers ``created_at`` (when the path was memoised); falls back to
    ``heat_base_set_at`` then ``last_accessed``. Datetimes are
    ISO-normalised; a missing value sorts oldest. ISO-8601 strings sort
    lexicographically in chronological order, so plain string comparison
    is correct here.
    """
    for field in ("created_at", "heat_base_set_at", "last_accessed"):
        val = mem.get(field)
        if val is None or val == "":
            continue
        if isinstance(val, (datetime, date)):
            return val.isoformat()
        return str(val)
    return ""


def find_cached_graph(store, project_path: str) -> str | None:
    """Return the cached graph_path for a project, or None.

    Returns the path from the MOST-RECENT memo tagged with the project's
    code-graph tag whose graph **still exists on disk**. A memo whose
    graph was deleted (path missing or empty) is skipped, never returned
    — this is the self-heal: a stale memo can no longer make the caller
    project an empty graph. When no live graph is found, returns None so
    the caller re-analyses and re-memoises.

    source: ingest staleness bug Jun-2026 (Dijkstra audit). Previously
    this returned the first tag match unconditionally, with no existence
    check and no recency ordering.
    """
    tag = code_graph_tag(project_path)
    try:
        if hasattr(store, "get_memories_by_tag"):
            # Tag-filtered, recency-ordered SQL lookup. The previous
            # full-table scan materialized every memory (content +
            # embeddings) to find a handful of graph memos
            # (bounded-I/O audit 2026-06-09).
            mems = store.get_memories_by_tag(tag, limit=20)
        else:  # test fakes / stores without the tag query
            mems = store.get_all_memories_for_decay()
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("ingest_helpers.cached_graph_lookup", exc)
        return None

    candidates: list[tuple[str, str]] = []  # (recency_key, graph_path)
    for mem in mems:
        if tag not in _memo_tags(mem):
            continue
        content = mem.get("content") or ""
        if not content.startswith("graph_path="):
            continue
        path = content[len("graph_path=") :].strip()
        if path:
            candidates.append((_memo_recency_key(mem), path))

    # Most-recent first; return the first whose graph is materialised AND
    # still fresh (built after the newest source change). A stale graph is
    # skipped so the caller re-analyses — "never serve a stale graph".
    candidates.sort(key=lambda c: c[0], reverse=True)
    for _, path in candidates:
        if not graph_path_is_materialised(path):
            continue
        if not graph_is_fresh(project_path, path):
            continue
        return path
    return None


# Directories never worth scanning for source-change detection: VCS,
# dependency caches, build outputs, virtualenvs, and the graph's own
# sidecar index. Pruned so the freshness walk early-exits cheaply on a
# real repo instead of stat-ing hundreds of thousands of vendored files.
_FRESHNESS_IGNORE_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "target",
        ".venv",
        "venv",
        "__pycache__",
        ".cache",
        "dist",
        "build",
        ".next",
        ".idea",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "search_index",
    }
)


def graph_is_fresh(project_path: str, graph_path: str) -> bool:
    """False when a source file changed AFTER the graph was built.

    Compares the graph artefact's own mtime (its build time) against the
    newest source file under ``project_path``. A bounded, ignore-pruned
    ``os.walk`` early-exits on the FIRST file newer than the graph, so a
    changed repo is detected without a full scan in the common case.

    Returns True (treat as fresh) when the project root is absent or the
    graph mtime is unreadable — staleness cannot be proven, and rejecting
    on uncertainty would force a needless re-analyse. The existence and
    health gates handle those cases; this gate's sole job is detecting a
    real source-vs-graph time skew.

    source: ingest stale-graph reuse Jun-2026 — ``find_cached_graph``
    reused a graph built before the codebase changed, so /cortex-visualize
    served a stale AST. ``graph_path_is_materialised`` (existence only)
    could not catch this; only a build-vs-source time comparison can.
    """
    try:
        built_at = Path(graph_path).expanduser().stat().st_mtime
    except OSError:
        return True
    root = Path(project_path).expanduser()
    if not root.is_dir():
        return True
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _FRESHNESS_IGNORE_DIRS and not d.startswith(".")
        ]
        for fn in filenames:
            try:
                if (Path(dirpath) / fn).stat().st_mtime > built_at:
                    return False
            except OSError:
                continue
    return True


def memoise_graph_path(
    store,
    project_path: str,
    graph_path: str,
    extra_tags: list[str] | None = None,
) -> int | None:
    """Persist the graph path as a protected memory for future lookups.

    Uses raw insert_memory (not the predictive-coding gate) so ingestion
    state is always recorded, even when low-surprise.

    ``extra_tags`` carries provenance (ADR-0052 sec 2, INC5.2) — e.g. the
    ``src:ap`` / AP-version tags from ``ingest_provenance.ap_provenance_tags``
    — appended to the base tag set.
    """
    tag = code_graph_tag(project_path)
    tags = [tag, "_ingest", "code-graph"]
    if extra_tags:
        tags.extend(extra_tags)
    record = {
        "content": f"graph_path={graph_path}",
        "tags": tags,
        "source": "ingest_codebase",
        "domain": "cortex-ingest",
        "directory_context": str(Path(project_path).expanduser().resolve()),
        "is_protected": True,
        "importance": 1.0,
        "heat": 1.0,
        # M-D2 (7.4): bulk codebase-graph ingestion bookkeeping.
        "write_class": "mechanical",
    }
    try:
        return store.insert_memory(record)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("ingest_helpers.graph_memo_insert", exc)
        return None


async def call_upstream(
    server_name: str,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Invoke a tool on an upstream MCP server; return parsed result.

    Raises McpConnectionError on connection/transport failure. Returns
    the tool result as a plain dict when the server answers successfully.
    """
    client = await get_client(server_name)
    # Bound concurrent in-flight calls to this single-process upstream child
    # across every Cortex handler. Without this, two batch tools (distinct
    # admission semaphores) can hammer the shared child until it OOMs and the
    # next stdin write raises ConnectionResetError: Connection lost.
    # source: upstream_governor.py / ingest_codebase RCA 2026-06-09.
    async with govern(server_name, client.max_concurrent_calls):
        response = await client.call(tool_name, args)
    if isinstance(response, dict):
        return response
    if isinstance(response, str):
        try:
            return json.loads(response)
        except (ValueError, TypeError):
            return {"text": response}
    return {"value": response}


def normalise_mcp_payload(payload: Any) -> Any:
    """MCP call() sometimes returns a dict with a 'content' array.

    The pipeline's tools emit ``{"content": [{"type": "text", "text": "{...}"}]}``;
    callers want the inner JSON. Other servers answer with a plain dict.
    This helper collapses both shapes to the underlying object.
    """
    if isinstance(payload, dict) and "content" in payload:
        content = payload["content"]
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and first.get("type") == "text":
                text = first.get("text", "")
                try:
                    return json.loads(text)
                except (ValueError, TypeError):
                    return {"text": text}
    return payload
