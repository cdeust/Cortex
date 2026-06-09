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
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.core.streaming.adaptive_writer import (
    AdaptiveBatchWriter,
    adaptive_drain,
)
from mcp_server.core.streaming.calibrated import (
    edge_queue_cap,
    make_edge_controller,
    make_entity_controller,
)
from mcp_server.infrastructure.staging_resolve_sink import (
    build_edge_sink,
    build_entity_sink,
)

logger = logging.getLogger(__name__)

# Upstream MCP server name in mcp-connections.json.
_UPSTREAM_SERVER = "codebase"

# Symbol ingest page size. Symbols are fetched and written in pages of
# this size so the peak RAM stays at O(page_size) rather than O(N_symbols).
# Kuzu queries use SKIP/LIMIT pagination per page so the MCP JSON-RPC
# blob per request is bounded regardless of total corpus size.
# Call edges and containment edges are pulled once after all symbol pages
# complete (they reference qualified_names that must already exist).
# source: Carnot analysis — root cause of OOM is accumulating all symbols
#   in one Python list before any write; adaptive pagination removes that.
_SYMBOL_PAGE_SIZE: int = 5_000
_DEFAULT_TOP_SYMBOLS: int | None = None  # None = ingest full graph, paged
_DEFAULT_TOP_PROCESSES: int | None = None

# Edge fetch+write page size. Edges are paged out of Kuzu via SKIP/LIMIT and
# written one page at a time to a single staging sink on the loop thread —
# constant memory on both sides. source: benchmark — the proven 1000-row chunk
# (74MB peak RSS / ~49.5k rows/s streaming 500k rows, measured 2026-06-03).
_EDGE_PAGE_SIZE: int = 1_000

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
                _store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


def _default_output_dir(project_path: str) -> str:
    """Default graph location under ~/.cache/cortex/code-graphs/."""
    from mcp_server.handlers.ingest_helpers import project_key

    return str(
        Path.home() / ".cache" / "cortex" / "code-graphs" / project_key(project_path)
    )


def _prune_precedent_graphs(output_dir: str) -> list[str]:
    """Remove stale graphs for the SAME project once a fresh one is built.

    Graph dirs are keyed ``<project-name>-<hash>`` (project_key) — but a
    path move, a version-named legacy dir, or a re-index under a new hash
    leaves the old ``<name>-*`` dir behind. Those precedents pollute
    ``resolve_graph_paths`` (the impact query then scans 4 graphs, some
    stale/empty, and can pick a stale hit). Per "update a version → remove
    the precedent", drop every sibling sharing this project's name prefix
    except the one we just wrote. Returns removed dir names.
    """
    import shutil

    cur = Path(output_dir)
    parent = cur.parent
    if not parent.is_dir():
        return []
    # Project name = key minus the trailing ``-<hash>`` segment.
    prefix = cur.name.rsplit("-", 1)[0] + "-"
    removed: list[str] = []
    for sib in parent.iterdir():
        if sib == cur or not sib.is_dir() or not sib.name.startswith(prefix):
            continue
        try:
            shutil.rmtree(sib)
            removed.append(sib.name)
        except OSError as exc:
            logger.warning("could not prune precedent graph %s: %s", sib, exc)
    if removed:
        logger.info("pruned %d precedent graph(s): %s", len(removed), removed)
    return removed


def _parse_int_or_none(raw: Any) -> int | None:
    return int(raw) if raw is not None else None


def _entity_rows_from_files(
    files: list[dict[str, Any]], domain: str
) -> list[writers.EntityRow]:
    """Project the file list into entity rows (None-safe)."""
    rows: list[writers.EntityRow] = []
    for f in files:
        row = writers.file_entity_row(f, domain)
        if row is not None:
            rows.append(row)
    return rows


async def _ingest_entities(
    store: Any,
    graph_path: str,
    domain: str,
    files: list[dict[str, Any]],
    diagnostics: list[str],
    page_size: int,
    top_symbols: int | None,
) -> int:
    """Stream files + paged symbols into KG entities via the staging sink.

    Entities resolve their ids server-side (NOT EXISTS dedup on LOWER(name));
    NO qualified_name -> id map is held in Python -- that map was the
    O(total_symbols) buffer that broke constant memory. The sink is
    SINGLE-WRITER on this (the event loop's) thread: its borrowed connection
    is created and used on one thread only, and Kuzu fetch / PG write are
    sequential per page, so peak RAM is O(page_size). Kuzu is read-only during
    ingest (graph built by ensure_graph first), so SKIP/LIMIT paging is
    drift-safe. Returns the number of symbol rows seen.
    """
    run_id = f"ingest-symbols:{domain}"
    sink = build_entity_sink(lambda: store.batch_pool.connection())
    # Single-writer (NOT EXISTS dedup needs no race) but ADAPTIVELY sized: the
    # writer buffers Kuzu pages and flushes AIMD-sized batches (measured bounds
    # in calibrated.py), growing while PG keeps up and shrinking when it slows.
    writer = AdaptiveBatchWriter(sink, make_entity_controller())
    offset, total_symbols = _checkpoint_read(store, run_id)  # 0,0 on a fresh run
    try:
        # File entities are idempotent (NOT EXISTS), so re-running them on a
        # resume is harmless; write them once at the start regardless.
        file_rows = _entity_rows_from_files(files, domain)
        if file_rows:
            writer.add_many(file_rows)
        while True:
            page, page_diag = await cypher.fetch_symbols_page(
                graph_path, offset=offset, page_size=page_size
            )
            diagnostics.extend(page_diag)
            if not page:
                break
            rows = [
                r
                for s in page
                if (r := writers.symbol_entity_row(s, domain)) is not None
            ]
            if rows:
                writer.add_many(rows)
            total_symbols += len(page)
            offset += page_size
            # Advisory checkpoint after the page committed. A crash before this
            # write re-does at most one page on resume (idempotent → safe).
            _checkpoint_write(store, run_id, offset, total_symbols)
            if top_symbols is not None and total_symbols >= top_symbols:
                break
        writer.flush_remaining()  # flush the buffered tail
    finally:
        sink.close()
    _checkpoint_clear(store, run_id)  # clean completion — drop the checkpoint
    return total_symbols


def _checkpoint_read(store: Any, run_id: str) -> tuple[int, int]:
    """Resume ``(offset, rows_seen)`` from the ingest checkpoint, or (0, 0).

    Guarded so stores without the checkpoint API (SQLite / test fakes) simply
    start fresh.
    """
    if not hasattr(store, "get_ingest_progress"):
        return 0, 0
    last_key, rows = store.get_ingest_progress(run_id)
    try:
        return (int(last_key) if last_key else 0), int(rows or 0)
    except (TypeError, ValueError):
        return 0, int(rows or 0)


def _checkpoint_write(store: Any, run_id: str, offset: int, total: int) -> None:
    if hasattr(store, "set_ingest_progress"):
        store.set_ingest_progress(run_id, str(offset), total)


def _checkpoint_clear(store: Any, run_id: str) -> None:
    if hasattr(store, "clear_ingest_progress"):
        store.clear_ingest_progress(run_id)


def _edge_rows(batch: list[tuple[str, str]], builder: Any) -> list[writers.EdgeRow]:
    """Project a raw-edge page through ``builder``, dropping None rows."""
    out: list[writers.EdgeRow] = []
    for e in batch:
        row = builder(e)
        if row is not None:
            out.append(row)
    return out


async def _ingest_edges(
    store: Any,
    graph_path: str,
    domain: str,
    files: list[dict[str, Any]],
    diagnostics: list[str],
    page_size: int,
) -> tuple[int, int]:
    """Stream call + containment edges into LOAD-BALANCED adaptive writers.

    The async Kuzu pagers feed ``adaptive_drain``: ``concurrency=2`` worker
    threads (safe here — edges use ``ON CONFLICT DO NOTHING``, unlike the
    race-prone single-writer entity stage) each run an AIMD-sized
    ``AdaptiveBatchWriter`` with its own ``batch_pool`` connection. The bounded
    queue applies backpressure to the pagers, and under PG contention both
    controllers shrink together (AIMD fair-share) — emergent load balancing.
    Endpoints resolve by SQL JOIN against the entities committed in Phase 2
    (the staged barrier). Returns (edges_written, edges_seen); the difference is
    the dangling-endpoint count.
    """
    seen = [0]  # producer-side count (mutable box, updated on the loop thread)

    async def _edge_pages():
        async for batch, diag in cypher.iter_call_edges(graph_path, page_size):
            diagnostics.extend(diag)
            rows = _edge_rows(batch, writers.call_edge_row)
            seen[0] += len(rows)
            yield rows
        known_files = {f["path"] for f in files if f.get("path")}
        async for batch, diag in cypher.iter_containment_edges(
            graph_path, known_files, page_size
        ):
            diagnostics.extend(diag)
            rows = _edge_rows(batch, writers.containment_edge_row)
            seen[0] += len(rows)
            yield rows

    result = await adaptive_drain(
        _edge_pages(),
        lambda: build_edge_sink(lambda: store.batch_pool.connection()),
        make_edge_controller,
        concurrency=2,
        queue_cap=edge_queue_cap(),
    )
    for err in result.errors:
        logger.warning("edge drain: %s", err)
    return result.rows_written, seen[0]


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

    # The fresh graph supersedes any precedent for this project — remove
    # stale ``<name>-*`` siblings so resolve_graph_paths returns only the
    # current graph (no stale/empty hits in the impact query).
    _prune_precedent_graphs(output_dir)

    diagnostics: list[Any] = []
    do_symbols = top_symbols is None or top_symbols > 0

    # ── Phase 1: files (small; become file entities + containment sources) ─
    files: list[dict[str, Any]] = []
    if do_symbols:
        files, file_diag = await cypher.fetch_files(graph_path, limit=None)
        diagnostics.extend(file_diag)

    # ── Phase 2: entities — files + paged symbols streamed to the staging
    # sink. No qualified_name->id map is held; ids resolve server-side. ─────
    total_symbols_seen = 0
    if do_symbols:
        total_symbols_seen = await _ingest_entities(
            store=store,
            graph_path=graph_path,
            domain=domain,
            files=files,
            diagnostics=diagnostics,
            page_size=_SYMBOL_PAGE_SIZE,
            top_symbols=top_symbols,
        )

    # ── Phase 3: edges — call + containment, streamed page-by-page and
    # resolved by SQL JOIN against the entities committed in Phase 2 (the
    # staged barrier: Phase 2 has fully returned before any edge resolves).
    # Constant memory on both fetch and write sides — no edge list, no
    # name-set. ───────────────────────────────────────────────────────────
    edges_written = 0
    edges_seen = 0
    if total_symbols_seen:
        edges_written, edges_seen = await _ingest_edges(
            store=store,
            graph_path=graph_path,
            domain=domain,
            files=files,
            diagnostics=diagnostics,
            page_size=_EDGE_PAGE_SIZE,
        )

    # ── Phase 4: processes ───────────────────────────────────────────────
    processes = (
        await _pull_processes(graph_path, top_processes)
        if (top_processes is None or top_processes > 0)
        else []
    )
    wiki_paths = pages.write_process_pages(processes)

    response: dict[str, Any] = {
        "ingested": True,
        "graph_path": graph_path,
        "analyze": analyze_stats,
        "entities_written": total_symbols_seen + len(files),
        "edges_written": edges_written,
        "edges_seen": edges_seen,
        "wiki_pages_written": wiki_paths,
        "symbol_count_seen": total_symbols_seen,
        "file_count_seen": len(files),
        "process_count_seen": len(processes),
    }
    if diagnostics:
        response["diagnostics"] = diagnostics
    return response
