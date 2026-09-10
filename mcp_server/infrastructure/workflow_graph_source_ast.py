"""source: ADR-0634"""

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
from mcp_server.infrastructure.workflow_graph_ast_response import normalize_search_hits
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

    @property
    def last_search_degraded_reason(self) -> str | None:
        """Return the recorded reason for the last degraded search, or None after
        success or before any attempt.

        source: ADR-0634"""
        return self._bridge.unavailable_reason

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
        """Row shape per item: ``{file_path, qualified_name, symbol_type,
                signature, language, line}``. ``domain`` is inferred downstream.
                A corrupt/missing graph is skipped without aborting the stream.

        source: ADR-0634"""
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

        source: ADR-0634"""
        out: list[dict[str, Any]] = []
        for batch in self.iter_symbols(file_paths):
            out.extend(batch)
        return out

    def iter_ast_edges(
        self,
        file_paths: Iterable[str],
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield CALLS, IMPORTS, MEMBER_OF, and USES rows one query batch at a
        time. Empty file_paths disables path filtering.

        source: ADR-0634"""
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
        """Collect iter_ast_edges into a complete edge list.

        source: ADR-0634"""
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

        source: ADR-0634"""
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

        source: ADR-0634"""
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

        source: ADR-0634"""
        if not is_enabled() or not query or not query.strip():
            return []
        gp = resolve_graph_path()
        if not gp:
            return []
        resp = self._loop_owner.run(
            self._bridge.search_codebase(gp, query, limit=int(limit))
        )
        return normalize_search_hits(resp)

    def verify_symbols(self, qualnames: list[str]) -> dict[str, bool]:
        """Return ``{qualname: exists_in_ap}`` for each candidate.

        source: ADR-0634"""
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
        """Yield edge-query batches through
        workflow_graph_ast_edges.edge_batches_async.

        source: ADR-0634"""
        return edge_batches_async(self._bridge, graph_path, paths)


__all__ = [
    "WorkflowGraphASTSource",
    "_SyncLoop",
    "_SHUTDOWN_DRAIN_TIMEOUT_S",
    "_SYMBOL_LABELS",
]
