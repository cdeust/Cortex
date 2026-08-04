"""AST-backed loader for the workflow graph (ADR-0046).

Peer of ``workflow_graph_source_pg`` / ``workflow_graph_source_jsonl``.
Calls the ``ai-architect-mcp-codebase`` MCP server via ``ap_bridge`` and
returns builder-shaped dicts for symbol nodes and the AST edges
(``defined_in``, ``calls``, ``imports``, ``member_of``).

Constrained to the Cortex-known file set: AP may have indexed files
that Cortex doesn't know about (e.g. vendored dependencies); we filter
so the graph stays focused on what the user's sessions actually touch.

Pure infrastructure — no core imports. When AP is disabled
(``CORTEX_MEMORY_AP_ENABLED=0``) or unreachable, every loader returns
``[]`` so the workflow graph degrades to the native in-process AST
source in ``workflow_graph_source_native_ast``.

Composition point over three separated concerns (issue #275 — this file
previously held all three and exceeded the 300-line cap): ``ap_sync_loop``
(cross-loop sync/drain primitive, ``_SyncLoop`` re-exported here),
``workflow_graph_ast_symbols`` (AST symbol loading), and
``workflow_graph_ast_edges`` (AST edge loading). The three private
``_*_batches_async``/``_verify_symbols_async`` methods below stay thin
instance-method delegates into those modules (not free functions) because
tests monkeypatch them per-instance.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Iterator

from mcp_server.infrastructure.ap_bridge import (
    APBridge,
    is_enabled,
    resolve_graph_path,
    resolve_graph_paths,
)
from mcp_server.infrastructure.ap_sync_loop import (
    _SHUTDOWN_DRAIN_TIMEOUT_S,
    _SyncLoop,
)
from mcp_server.infrastructure.workflow_graph_ast_edges import edge_batches_async
from mcp_server.infrastructure.workflow_graph_ast_response import as_list
from mcp_server.infrastructure.workflow_graph_ast_symbols import (
    _SYMBOL_LABELS,
    symbol_batches_async,
    verify_symbols_async,
)

logger = logging.getLogger(__name__)


class WorkflowGraphASTSource:
    """AST-layer loader. Construct once per graph build; the inner
    bridge caches its MCP connection across calls."""

    def __init__(self, bridge: APBridge | None = None) -> None:
        self._bridge = bridge or APBridge()
        self._loop_owner = _SyncLoop()

    def enabled(self) -> bool:
        return is_enabled()

    def close(self) -> None:
        """Close the underlying bridge + pinned loop. Idempotent."""
        try:
            self._loop_owner.run(self._bridge.close())
        except Exception as exc:  # noqa: BLE001 — teardown continues to the loop close
            logger.debug("AP bridge close failed during teardown: %s", exc)
        self._loop_owner.close()

    def iter_symbols(
        self,
        file_paths: Iterable[str],
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield AST symbol rows one per-query batch (one AP ``query_graph``
        per label per graph). Each yielded list is the result of a single
        AP roundtrip; the caller sees batch *N* before batch *N+1*'s query
        is issued, so the source-internal peak is one query's rows — never
        the union across all ~21 label queries × graphs.

        Row shape per item: ``{file_path, qualified_name, symbol_type,
        signature, language, line}``. ``domain`` is inferred downstream.
        A corrupt/missing graph is skipped without aborting the stream.
        """
        if not is_enabled():
            return
        graph_paths = resolve_graph_paths()
        if not graph_paths:
            return
        paths = [p for p in file_paths if p]
        yield from self._loop_owner.run_iter(
            self._iter_symbols_async(graph_paths, paths)
        )

    def load_symbols(
        self,
        file_paths: Iterable[str],
    ) -> list[dict[str, Any]]:
        """Full-set convenience over ``iter_symbols``.

        Materializes every batch into one list for consumers that genuinely
        need the whole set (the workflow_graph builder iterates ``ast_symbols``
        once and the handler takes ``len(...)``). The streaming win is still
        real: ``iter_symbols`` bounds the *source*-internal peak to one query
        while this list is filled. Consumers that can iterate should call
        ``iter_symbols`` directly to avoid the final materialization.
        """
        out: list[dict[str, Any]] = []
        for batch in self.iter_symbols(file_paths):
            out.extend(batch)
        return out

    def iter_ast_edges(
        self,
        file_paths: Iterable[str],
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield CALLS / IMPORTS / MEMBER_OF / USES edge rows one per-query
        batch (one AP ``query_graph`` per rel-table per graph, ~89 queries).
        Same incremental contract as ``iter_symbols``: peak retained inside
        the source is one rel-table's rows, not the union of all 89.
        Empty ``file_paths`` means "no path filter"."""
        if not is_enabled():
            return
        graph_paths = resolve_graph_paths()
        if not graph_paths:
            return
        paths = [p for p in file_paths if p]
        yield from self._loop_owner.run_iter(self._iter_edges_async(graph_paths, paths))

    def load_ast_edges(
        self,
        file_paths: Iterable[str],
    ) -> list[dict[str, Any]]:
        """Full-set convenience over ``iter_ast_edges`` (see ``load_symbols``
        for why the final list is kept: the builder + handler ``len(...)``
        genuinely need the whole edge set)."""
        out: list[dict[str, Any]] = []
        for batch in self.iter_ast_edges(file_paths):
            out.extend(batch)
        return out

    async def _iter_symbols_async(
        self,
        graph_paths: list[str],
        paths: list[str],
    ):
        """Async generator: one batch per (graph, label) AP query.

        A failed query for one (graph, label) is skipped — one bad graph or
        label never kills the whole stream, matching the prior swallow-and-
        continue contract.
        """
        for gp in graph_paths:
            try:
                async for batch in self._symbol_batches_async(gp, paths):
                    if batch:
                        yield batch
            except Exception as exc:  # noqa: BLE001 — one corrupt/missing graph never kills the whole stream; logged per skip
                logger.debug(
                    "symbol batches failed for graph %s (skipped): %s", gp, exc
                )
                continue

    async def _iter_edges_async(
        self,
        graph_paths: list[str],
        paths: list[str],
    ):
        """Async generator: one batch per (graph, rel-table) AP query."""
        for gp in graph_paths:
            try:
                async for batch in self._edge_batches_async(gp, paths):
                    if batch:
                        yield batch
            except Exception as exc:  # noqa: BLE001 — one corrupt/missing graph never kills the whole stream; logged per skip
                logger.debug("edge batches failed for graph %s (skipped): %s", gp, exc)
                continue

    async def _load_symbols_async(
        self,
        graph_path: str,
        paths: list[str],
    ) -> list[dict[str, Any]]:
        """Full-set per-graph drain of ``_symbol_batches_async``.

        Kept list-returning because ``http_standalone_graph`` caches the
        per-project symbol list and reports ``len(syms)`` — a genuine
        full-set consumer (reported as needing-full-set in the C3 RCA).
        """
        out: list[dict[str, Any]] = []
        async for batch in self._symbol_batches_async(graph_path, paths):
            out.extend(batch)
        return out

    def _symbol_batches_async(self, graph_path: str, paths: list[str]):
        """Delegates to ``workflow_graph_ast_symbols.symbol_batches_async``.

        Kept as an instance method: ``test_ble001_sweep_infrastructure.py``
        monkeypatches it per-instance to exercise ``_iter_symbols_async``'s
        per-graph error handling in isolation.
        """
        return symbol_batches_async(self._bridge, graph_path, paths)

    def search_codebase(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Forward ``search_codebase`` to AP and normalize to a flat
        list of ``{id, qualified_name, file_path, score, snippet}``.

        Phase 3 (ADR-0046). When AP is disabled OR no graph_path is
        configured, returns ``[]`` so the unified-search fusion
        gracefully falls back to Cortex-only results.
        """
        if not is_enabled() or not query or not query.strip():
            return []
        gp = resolve_graph_path()
        if not gp:
            return []
        resp = self._loop_owner.run(
            self._bridge.search_codebase(gp, query, limit=int(limit))
        )
        out: list[dict[str, Any]] = []
        for r in as_list(resp):
            qname = r.get("qualified_name") or r.get("name") or ""
            fpath = r.get("file_path") or r.get("abs_path") or ""
            if not qname:
                continue
            out.append(
                {
                    # Deterministic id so RRF fusion can dedupe with
                    # the same scheme used for SYMBOL graph nodes.
                    "id": f"symbol:{fpath}::{qname}",
                    "qualified_name": str(qname),
                    "file_path": str(fpath),
                    "score": float(r.get("score") or 0.0),
                    "snippet": r.get("snippet") or r.get("signature") or "",
                    "source": "ap",
                }
            )
        return out

    def verify_symbols(self, qualnames: list[str]) -> dict[str, bool]:
        """Return ``{qualname: exists_in_ap}`` for each candidate.

        Used by the wiki_verify handler (ADR-0046 Phase 2). Returns
        ``{qname: False}`` for every input when AP is disabled OR no
        graph_path is configured — the handler interprets that as
        'verification skipped', not as confirmed staleness.
        """
        if not is_enabled():
            return {q: False for q in qualnames}
        gp = resolve_graph_path()
        if not gp:
            return {q: False for q in qualnames}
        uniq = [q for q in dict.fromkeys(qualnames) if q]
        if not uniq:
            return {}
        return self._loop_owner.run(self._verify_symbols_async(gp, uniq))

    async def _verify_symbols_async(
        self,
        graph_path: str,
        qualnames: list[str],
    ) -> dict[str, bool]:
        """Delegates to ``workflow_graph_ast_symbols.verify_symbols_async``."""
        return await verify_symbols_async(self._bridge, graph_path, qualnames)

    async def _load_edges_async(
        self,
        graph_path: str,
        paths: list[str],
    ) -> list[dict[str, Any]]:
        """Full-set per-graph drain of ``_edge_batches_async``.

        Kept list-returning for ``http_standalone_graph`` (caches the
        per-project edge list, reports ``len(edgs)``) — a genuine full-set
        consumer (reported as needing-full-set in the C3 RCA).
        """
        out: list[dict[str, Any]] = []
        async for batch in self._edge_batches_async(graph_path, paths):
            out.extend(batch)
        return out

    def _edge_batches_async(self, graph_path: str, paths: list[str]):
        """Delegates to ``workflow_graph_ast_edges.edge_batches_async``
        (same rationale as ``_symbol_batches_async`` above)."""
        return edge_batches_async(self._bridge, graph_path, paths)


__all__ = [
    "WorkflowGraphASTSource",
    "_SyncLoop",
    "_SHUTDOWN_DRAIN_TIMEOUT_S",
    "_SYMBOL_LABELS",
]
