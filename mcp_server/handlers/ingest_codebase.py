"""Handler: ingest_codebase — pull codebase analysis from the upstream
ai-automatised-pipeline MCP server into Cortex's store.

Flow
----
1. Resolve the project's graph path (cache hit or upstream analyze).
2. Pull the FULL chain hierarchy from the Kuzu graph via Cypher:
   every Function/Method/Struct, every File, every call edge between
   symbols, every File→symbol containment edge.
3. Project upstream artefacts into Cortex's stores: memories + KG
   entities + KG edges + wiki reference pages per process.
4. Return an ingestion summary.

Cortex is the CONSUMER — upstream owns analysis, Cortex owns
documentation and knowledge-graph state.

This file is the composition root. Implementation is split:
  - ingest_codebase_schema.py    — MCP tool schema
  - ingest_codebase_graph.py     — graph-path resolution + analyze
  - ingest_codebase_cypher.py    — Kuzu fetchers
  - ingest_codebase_writers.py   — MemoryStore writers
  - ingest_codebase_pages.py     — process wiki rendering
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from mcp_server.errors import McpConnectionError
from mcp_server.handlers import ingest_codebase_cypher as cypher
from mcp_server.handlers import ingest_codebase_graph as graphmod
from mcp_server.handlers import ingest_codebase_pages as pages
from mcp_server.handlers import ingest_codebase_writers as writers
from mcp_server.handlers.ingest_codebase_schema import schema  # re-exported
from mcp_server.handlers.ingest_helpers import call_upstream, normalise_mcp_payload
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

# Upstream MCP server name in mcp-connections.json.
_UPSTREAM_SERVER = "codebase"

# Symbol/process caps. ``None`` means "no LIMIT clause" — pull every
# Function/Method/Struct, every call edge, every process. The Rust
# pipeline already did the AST work; Cortex's job is to project the
# whole graph, not a tip-of-the-iceberg sample. Callers may still pass
# ``top_symbols`` / ``top_processes`` to cap explicitly.
_DEFAULT_TOP_SYMBOLS: int | None = None
_DEFAULT_TOP_PROCESSES: int | None = None

__all__ = ["schema", "handler"]

_store: MemoryStore | None = None
_store_lock = threading.Lock()


def _get_store() -> MemoryStore:
    """Lazy MemoryStore singleton.

    Lock-guarded for the worker-thread case (asyncio coroutines on one
    loop don't preempt mid-init, but if any caller invokes the handler
    from a thread pool — e.g., a sync hook running on an executor — the
    fast double-checked init below prevents racing on construction.
    """
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                settings = get_memory_settings()
                _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


def _default_output_dir(project_path: str) -> str:
    """Default graph location under ~/.cache/cortex/code-graphs/."""
    from mcp_server.handlers.ingest_helpers import project_key

    return str(
        Path.home() / ".cache" / "cortex" / "code-graphs" / project_key(project_path)
    )


def _parse_int_or_none(raw: Any) -> int | None:
    return int(raw) if raw is not None else None


def _attribute_files_to_symbols(
    symbols: list[dict[str, Any]],
    file_edges: list[tuple[str, str]],
    known_files: set[str],
) -> list[str]:
    """Assign ``sym["file"]`` from the authoritative File→symbol
    containment edges. Returns diagnostic strings for symbols that
    fell through to the qn-split fallback (so non-Python indexers
    that don't emit containment edges are visible to the user).

    The qn-split fallback is only trusted when its derived path
    appears in ``known_files`` — otherwise we leave file=None rather
    than fabricating a Rust crate/module name as a file path.
    """
    qn_to_file: dict[str, str] = {qn: f for (f, qn) in file_edges}
    fallback_used = 0
    fallback_unverified = 0
    for sym in symbols:
        qn = sym.get("qualified_name")
        if not qn:
            continue
        authoritative = qn_to_file.get(qn)
        if authoritative is not None:
            sym["file"] = authoritative
            continue
        # No containment edge — try the qn-split fallback, but only
        # accept it when the result corresponds to an actual File node.
        candidate = cypher.file_path_from_qn(qn)
        if candidate and candidate in known_files:
            sym["file"] = candidate
            fallback_used += 1
        else:
            sym["file"] = None
            if candidate:
                fallback_unverified += 1
    diagnostics: list[str] = []
    if fallback_used:
        diagnostics.append(
            f"file-attribution: {fallback_used} symbols had no "
            f"(:File)-[]->(:symbol) edge; used qn-split fallback "
            f"(verified against known files)"
        )
    if fallback_unverified:
        diagnostics.append(
            f"file-attribution: {fallback_unverified} symbols had no "
            f"containment edge AND the qn-split fallback didn't match a "
            f"known file (likely non-Python indexer); file=None"
        )
    return diagnostics


async def _pull_symbols_and_files(
    graph_path: str,
    top_symbols: int | None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[tuple[str, str]],
    list[tuple[str, str]],
    list[str],
]:
    """Project the full chain hierarchy: symbols, files, call edges,
    file-containment edges. Returns the four artefacts plus a flat
    diagnostics list (one entry per failed sub-query)."""
    diagnostics: list[str] = []
    symbols, sym_diag = await cypher.fetch_top_symbols(graph_path, top_symbols)
    diagnostics.extend(sym_diag)
    files, file_diag = await cypher.fetch_files(graph_path, limit=top_symbols)
    diagnostics.extend(file_diag)
    call_edges: list[tuple[str, str]] = []
    file_edges: list[tuple[str, str]] = []
    if symbols:
        known_symbols = {
            s["qualified_name"] for s in symbols if s.get("qualified_name")
        }
        call_edges, call_diag = await cypher.fetch_call_edges(
            graph_path, known_symbols
        )
        diagnostics.extend(call_diag)
        known_files = {f["path"] for f in files if f.get("path")}
        if known_files:
            file_edges, contain_diag = await cypher.fetch_file_containment(
                graph_path, known_files, known_symbols
            )
            diagnostics.extend(contain_diag)
        else:
            known_files = set()
        diagnostics.extend(_attribute_files_to_symbols(symbols, file_edges, known_files))
    return symbols, files, call_edges, file_edges, diagnostics


async def _pull_processes(
    graph_path: str,
    top_processes: int | None,
) -> list[dict[str, Any]]:
    """Pull processes via upstream get_processes; respect optional cap."""
    try:
        proc_payload = await call_upstream(
            _UPSTREAM_SERVER,
            "get_processes",
            {"graph_path": graph_path},
        )
        proc_result = normalise_mcp_payload(proc_payload)
        all_procs = proc_result.get("processes") or []
        return all_procs if top_processes is None else all_procs[:top_processes]
    except Exception as exc:
        logger.debug("get_processes failed: %s", exc)
        return []


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ingest a codebase analysis into Cortex's store."""
    args = args or {}
    project_path = (args.get("project_path") or "").strip()
    if not project_path:
        return {"ingested": False, "reason": "project_path is required"}

    output_dir = args.get("output_dir") or _default_output_dir(project_path)
    language = args.get("language", "auto") or "auto"
    force_reindex = bool(args.get("force_reindex", False))
    top_symbols = _parse_int_or_none(args.get("top_symbols", _DEFAULT_TOP_SYMBOLS))
    top_processes = _parse_int_or_none(
        args.get("top_processes", _DEFAULT_TOP_PROCESSES)
    )

    store = _get_store()
    domain = f"code:{Path(project_path).name}"

    try:
        graph_path, analyze_stats = await graphmod.ensure_graph(
            store, project_path, output_dir, language, force_reindex
        )
    except McpConnectionError as exc:
        return {
            "ingested": False,
            "reason": "upstream_mcp_unreachable",
            "error": str(exc),
        }
    except Exception as exc:
        logger.warning("ingest_codebase analyze step failed: %s", exc, exc_info=True)
        return {
            "ingested": False,
            "reason": "analyze_failed",
            "error": f"{type(exc).__name__}: {exc}",
        }

    if top_symbols is None or top_symbols > 0:
        symbols, files, call_edges, file_edges, diagnostics = (
            await _pull_symbols_and_files(graph_path, top_symbols)
        )
    else:
        symbols, files, call_edges, file_edges, diagnostics = [], [], [], [], []

    processes = (
        await _pull_processes(graph_path, top_processes)
        if (top_processes is None or top_processes > 0)
        else []
    )

    sym_mem = writers.write_symbol_memories(store, symbols, project_path, domain)
    file_mem = writers.write_file_memories(store, files, project_path, domain)
    sym_ent, ent_diag = writers.write_symbol_entities(store, symbols, domain)
    diagnostics.extend(ent_diag)
    file_ent = writers.write_file_entities(store, files, domain)
    call_count = writers.write_symbol_relationships(store, call_edges, sym_ent)
    contain_count = writers.write_file_relationships(
        store, file_edges, file_ent, sym_ent
    )
    wiki_paths = pages.write_process_pages(processes)

    response: dict[str, Any] = {
        "ingested": True,
        "graph_path": graph_path,
        "analyze": analyze_stats,
        "memories_written": len(sym_mem) + len(file_mem),
        "entities_written": len(sym_ent) + len(file_ent),
        "edges_written": call_count + contain_count,
        "wiki_pages_written": wiki_paths,
        "symbol_count_seen": len(symbols),
        "file_count_seen": len(files),
        "process_count_seen": len(processes),
    }
    if diagnostics:
        response["diagnostics"] = diagnostics
    return response
