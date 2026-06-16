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

import dataclasses
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
from mcp_server.shared.progress import NullProgress, ProgressReporter

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

# Human-readable names for the 6 sequential ingest stages.
# Order must match the execution order inside handler().
_STAGES: tuple[str, ...] = (
    "analyze graph",
    "fetch files",
    "ingest entities",
    "ingest edges",
    "pull processes",
    "enrich process symbols",
)

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


@dataclasses.dataclass
class _SymbolPageCtx:
    """Grouped context for the symbol pagination loop (avoids >4-param violation)."""

    graph_path: str
    domain: str
    page_size: int
    top_symbols: int | None
    symbol_total: int | None
    writer: Any
    run_id: str
    store: Any
    progress: Any


async def _stream_symbol_pages(
    ctx: _SymbolPageCtx,
    diagnostics: list[str],
    start_offset: int,
    start_count: int,
) -> int:
    """Paginate Kuzu symbols into ctx.writer; return total rows consumed.

    Precondition:  start_offset/start_count from checkpoint (or 0, 0 fresh).
    Postcondition: all symbol pages written, checkpoint updated each page.
    Invariant:     total_symbols non-decreasing; terminates on empty page or
                   top_symbols cap.
    """
    offset = start_offset
    total_symbols = start_count
    while True:
        page, page_diag = await cypher.fetch_symbols_page(
            ctx.graph_path, offset=offset, page_size=ctx.page_size
        )
        diagnostics.extend(page_diag)
        if not page:
            break
        rows = [
            r
            for s in page
            if (r := writers.symbol_entity_row(s, ctx.domain)) is not None
        ]
        if rows:
            ctx.writer.add_many(rows)
        total_symbols += len(page)
        # stride != page_size — see symbol_page_stride (2026-06-11 RCA).
        offset += cypher.symbol_page_stride(ctx.page_size)
        _checkpoint_write(ctx.store, ctx.run_id, offset, total_symbols)
        ctx.progress.advance(total_symbols, total=ctx.symbol_total)
        if ctx.top_symbols is not None and total_symbols >= ctx.top_symbols:
            break
    return total_symbols


async def _build_symbol_ctx(
    store: Any,
    graph_path: str,
    domain: str,
    page_size: int,
    top_symbols: int | None,
    progress: Any,
) -> tuple[_SymbolPageCtx, AdaptiveBatchWriter, Any, int, int]:
    """Build the pagination context + sink; return (ctx, writer, sink, off, n).

    top_symbols is the tightest honest bound when set; otherwise Kuzu is
    queried for the real count via three cheap COUNT(*) queries. None means
    indeterminate — the bar stays frozen but McpProgress.advance() still
    emits a running-count text line on every dispatch.
    """
    run_id = f"ingest-symbols:{domain}"
    sink = build_entity_sink(lambda: store.batch_pool.connection())
    writer = AdaptiveBatchWriter(sink, make_entity_controller())
    offset, count = _checkpoint_read(store, run_id)
    symbol_total: int | None = (
        top_symbols
        if top_symbols is not None
        else await cypher.fetch_symbols_total(graph_path)
    )
    ctx = _SymbolPageCtx(
        graph_path=graph_path,
        domain=domain,
        page_size=page_size,
        top_symbols=top_symbols,
        symbol_total=symbol_total,
        writer=writer,
        run_id=run_id,
        store=store,
        progress=progress,
    )
    return ctx, writer, sink, offset, count


async def _ingest_entities(
    store: Any,
    graph_path: str,
    domain: str,
    files: list[dict[str, Any]],
    diagnostics: list[str],
    page_size: int,
    top_symbols: int | None,
    *,
    progress: ProgressReporter | None = None,
) -> tuple[int, int]:
    """Stream files + paged symbols into KG entities via the staging sink.

    SINGLE-WRITER; peak RAM is O(page_size). Returns
    (symbol_rows_seen, entity_rows_inserted).
    """
    _progress = progress or NullProgress()
    ctx, writer, sink, offset, total = await _build_symbol_ctx(
        store,
        graph_path,
        domain,
        page_size,
        top_symbols,
        _progress,
    )
    try:
        file_rows = _entity_rows_from_files(files, domain)
        if file_rows:
            writer.add_many(file_rows)
        total = await _stream_symbol_pages(ctx, diagnostics, offset, total)
        writer.flush_remaining()
    finally:
        sink.close()
    _checkpoint_clear(store, ctx.run_id)
    return total, writer.rows_written


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
    *,
    progress: ProgressReporter | None = None,
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
            rows = _edge_rows(batch, lambda e: writers.call_edge_row(e, domain))
            seen[0] += len(rows)
            yield rows
        known_files = {f["path"] for f in files if f.get("path")}
        async for batch, diag in cypher.iter_containment_edges(
            graph_path, known_files, page_size
        ):
            diagnostics.extend(diag)
            rows = _edge_rows(batch, lambda e: writers.containment_edge_row(e, domain))
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
    *,
    progress: ProgressReporter | None = None,
) -> list[dict[str, Any]]:
    """Pull ALL processes via upstream get_processes; respect optional cap.

    Upstream pages its process list by serialized size (``truncated`` +
    ``next_offset``, automatised-pipeline ``do_get_processes``); a single
    call returns only the first page. Follow the cursor until exhausted —
    the previous single-shot read silently dropped every process past the
    first byte-budget page (2026-06-11 RCA).
    """
    procs: list[dict[str, Any]] = []
    offset = 0
    try:
        while True:
            proc_payload = await call_upstream(
                _UPSTREAM_SERVER,
                "get_processes",
                {"graph_path": graph_path, "offset": offset},
            )
            proc_result = normalise_mcp_payload(proc_payload)
            procs.extend(proc_result.get("processes") or [])
            if top_processes is not None and len(procs) >= top_processes:
                return procs[:top_processes]
            next_offset = proc_result.get("next_offset")
            if not proc_result.get("truncated") or next_offset is None:
                break
            if int(next_offset) <= offset:
                logger.warning("get_processes: non-advancing cursor at %d", offset)
                break
            offset = int(next_offset)
    except Exception as exc:
        logger.debug("get_processes failed: %s", exc)
    return procs


# Per-page cap on the "Symbols reached" list a process wiki page renders.
# render_process_page lists at most 50 symbols (its own display cap); the
# fetch honours the same bound so neither side does unbounded work.
_PROCESS_SYMBOLS_LIMIT: int = 50


async def _enrich_process_symbols(
    graph_path: str,
    processes: list[dict[str, Any]],
    diagnostics: list[str],
    *,
    progress: ProgressReporter | None = None,
) -> None:
    """Attach participating symbol qns to each process (in place).

    ``get_processes`` returns only counts (``node_count``); the actual
    membership lives in the graph as ParticipatesIn edges. Pages without
    symbols carry no documentation value (2026-05-17 user feedback), so
    this fetch is what makes the wiki pages worth writing.
    """
    for proc in processes:
        entry = proc.get("entry_point")
        if not entry or not _process_node_count(proc):
            continue
        qns, diag = await cypher.fetch_process_symbols(
            graph_path, str(entry), _PROCESS_SYMBOLS_LIMIT
        )
        diagnostics.extend(diag)
        if qns:
            proc["symbols"] = qns


def _process_node_count(proc: dict[str, Any]) -> int:
    try:
        return int(proc.get("node_count") or 0)
    except (TypeError, ValueError):
        return 0


async def handler(
    args: dict[str, Any] | None = None,
    *,
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    """Ingest a codebase analysis into Cortex's store.

    Precondition:  args["project_path"] is a non-empty string path to an
                   existing codebase directory.
    Postcondition: returns dict with "ingested": True and summary counts on
                   success, or "ingested": False with "reason" on failure.
                   progress receives stage() once per _STAGES entry in order,
                   advance() after each entity page, and close() in the finally.
    """
    _progress = progress or NullProgress()
    args = args or {}
    project_path = (args.get("project_path") or "").strip()
    if not project_path:
        return {"ingested": False, "reason": "project_path is required"}

    # A plugin-cache copy is NOT a project. Indexing them produced 8
    # duplicate symbol universes (versions 3.18.3–3.19.5 of Cortex
    # itself) whose graphs outlived their deleted source dirs and
    # polluted the galaxy + impact queries (user report 2026-06-13).
    _resolved = str(Path(project_path).expanduser().resolve())
    if "/plugins/cache/" in _resolved or "/.claude/plugins/" in _resolved:
        return {
            "ingested": False,
            "reason": (
                "refused: plugin-cache copy, not a project — "
                "index the source repository instead"
            ),
            "project_path": _resolved,
        }

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
        _progress.stage(_STAGES[0], 0, len(_STAGES))
        graph_path, analyze_stats = await graphmod.ensure_graph(
            store, project_path, output_dir, language, force_reindex
        )
    except McpConnectionError as exc:
        _progress.close()
        return {
            "ingested": False,
            "reason": "upstream_mcp_unreachable",
            "error": str(exc),
        }
    except Exception as exc:
        logger.warning("ingest_codebase analyze step failed: %s", exc, exc_info=True)
        _progress.close()
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

    try:
        # ── Phase 1: files (small; become file entities + containment sources) ─
        files: list[dict[str, Any]] = []
        if do_symbols:
            _progress.stage(_STAGES[1], 1, len(_STAGES))
            files, file_diag = await cypher.fetch_files(graph_path, limit=None)
            diagnostics.extend(file_diag)

        # ── Phase 2: entities — files + paged symbols streamed to the staging
        # sink. No qualified_name->id map is held; ids resolve server-side. ─────
        total_symbols_seen = 0
        entities_written = 0
        if do_symbols:
            _progress.stage(_STAGES[2], 2, len(_STAGES))
            total_symbols_seen, entities_written = await _ingest_entities(
                store=store,
                graph_path=graph_path,
                domain=domain,
                files=files,
                diagnostics=diagnostics,
                page_size=_SYMBOL_PAGE_SIZE,
                top_symbols=top_symbols,
                progress=_progress,
            )

        # ── Phase 3: edges — call + containment, streamed page-by-page and
        # resolved by SQL JOIN against the entities committed in Phase 2 (the
        # staged barrier: Phase 2 has fully returned before any edge resolves).
        # Constant memory on both fetch and write sides — no edge list, no
        # name-set. ───────────────────────────────────────────────────────────
        edges_written = 0
        edges_seen = 0
        if total_symbols_seen:
            _progress.stage(_STAGES[3], 3, len(_STAGES))
            edges_written, edges_seen = await _ingest_edges(
                store=store,
                graph_path=graph_path,
                domain=domain,
                files=files,
                diagnostics=diagnostics,
                page_size=_EDGE_PAGE_SIZE,
                progress=_progress,
            )

        # ── Phase 4: processes ───────────────────────────────────────────────
        _progress.stage(_STAGES[4], 4, len(_STAGES))
        processes = (
            await _pull_processes(graph_path, top_processes, progress=_progress)
            if (top_processes is None or top_processes > 0)
            else []
        )
        if processes:
            _progress.stage(_STAGES[5], 5, len(_STAGES))
            await _enrich_process_symbols(
                graph_path, processes, diagnostics, progress=_progress
            )
        wiki_paths = pages.write_process_pages(processes)
    finally:
        _progress.close()

    response: dict[str, Any] = {
        "ingested": True,
        "graph_path": graph_path,
        "analyze": analyze_stats,
        # entities_written = rows actually INSERTed by the staging sink
        # (post NOT EXISTS dedup); entities_seen = rows streamed at it.
        # The previous response reported seen counts AS written — a
        # misnomer that masked the domain-blind dedup bug (2026-06-11 RCA).
        "entities_written": entities_written,
        "entities_seen": total_symbols_seen + len(files),
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
