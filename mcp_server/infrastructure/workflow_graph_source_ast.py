"""AST-backed loader for the workflow graph (ADR-0046).

Peer of ``workflow_graph_source_pg`` / ``workflow_graph_source_jsonl``.
Calls the ``automatised-pipeline`` MCP server via ``ap_bridge`` and
returns builder-shaped dicts for symbol nodes and the AST edges
(``defined_in``, ``calls``, ``imports``, ``member_of``).

Constrained to the Cortex-known file set: AP may have indexed files
that Cortex doesn't know about (e.g. vendored dependencies); we filter
so the graph stays focused on what the user's sessions actually touch.

Pure infrastructure — no core imports. When AP is disabled
(``CORTEX_MEMORY_AP_ENABLED=0``) or unreachable, every loader returns
``[]`` so the workflow graph degrades to the native in-process AST
source in ``workflow_graph_source_native_ast``.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Iterable, Iterator

from mcp_server.errors import McpConnectionError
from mcp_server.infrastructure.ap_bridge import (
    APBridge,
    is_enabled,
    resolve_graph_path,
    resolve_graph_paths,
)


def _ap_sync_timeout_s() -> float:
    """Cross-loop wait ceiling for AP reader-thread calls.

    source: memory_config.AP_SYNC_RESULT_TIMEOUT_S (see that field's
    derivation comment — floored at the in-loop 3600 s AP-call ceiling
    plus a drain margin). Read lazily so env overrides apply per-process.
    """
    from mcp_server.infrastructure.memory_config import get_memory_settings

    return float(get_memory_settings().AP_SYNC_RESULT_TIMEOUT_S)


def _run(coro):
    """Legacy sync wrapper — each call creates a fresh loop. Retained
    for callers that only need one roundtrip per process.

    The AST source itself avoids this for multi-call flows: the subprocess
    streams (``asyncio.subprocess``) are bound to whichever loop created
    them, and a second ``asyncio.run`` invalidates them. The class uses
    ``_SyncLoop`` to pin one loop across all its calls.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Lamport H4: an untimed cross-loop .result() hangs this caller
            # forever if the loop thread wedges. Bound every cross-loop wait.
            try:
                return asyncio.run_coroutine_threadsafe(coro, loop).result(
                    timeout=_ap_sync_timeout_s()
                )
            except FutureTimeoutError as exc:
                raise McpConnectionError(
                    "AP cross-loop call exceeded "
                    f"{_ap_sync_timeout_s():.0f}s — subprocess presumed wedged"
                ) from exc
    except RuntimeError:
        pass
    return asyncio.run(coro)


class _SyncLoop:
    """Owns a single event loop + runs coroutines on it synchronously.

    The MCP client spawns the AP subprocess and binds its stdin/stdout
    to the *current* event loop. If we close that loop between calls,
    subsequent writes to those streams raise ``RuntimeError: Event loop
    is closed``. This helper pins one loop for the lifetime of a caller
    so every AP call shares the same loop/transport.

    When called from *inside* a running event loop (e.g. a FastMCP
    async handler), we run the coroutine on the private loop inside a
    dedicated thread so we never compete with the outer loop. That is
    the only reliable way to expose a sync façade to async callers
    without leaking thread-local state.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            loop = self._loop  # non-Optional local captured by the loop thread
            import threading

            def _run_forever():
                asyncio.set_event_loop(loop)
                loop.run_forever()

            self._thread = threading.Thread(
                target=_run_forever,
                name="ap-sync-loop",
                daemon=True,
            )
            self._thread.start()
        return self._loop

    def run(self, coro):
        """Run ``coro`` on the pinned loop and block until it completes.

        Single-reader-thread ownership (verified): ``_ensure_loop`` spawns
        exactly one ``ap-sync-loop`` thread that owns the loop for this
        ``_SyncLoop``'s lifetime; every AP call funnels through here onto
        that one loop. No other thread drives the loop, so the JSON-RPC
        pipe has a single reader (Lamport H4 satisfied by construction).

        The wait is bounded: if the loop thread wedges (e.g. the AP
        subprocess stalls below the in-loop await), ``.result(timeout=…)``
        raises rather than hanging this worker forever. On timeout we never
        return partial data — we raise ``McpConnectionError``.
        """
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=_ap_sync_timeout_s())
        except FutureTimeoutError as exc:
            future.cancel()
            raise McpConnectionError(
                "AP reader-thread call exceeded "
                f"{_ap_sync_timeout_s():.0f}s — subprocess presumed wedged"
            ) from exc

    def run_iter(self, agen) -> Iterator[Any]:
        """Drive an async generator one step per bounded cross-loop call,
        yielding each item synchronously to the caller.

        This is the streaming primitive: ``agen`` (an async generator that
        yields one batch per AP query) is advanced one ``__anext__`` at a
        time, each on the pinned loop with a bounded ``.result(timeout=…)``.
        The caller therefore receives batch *N* (and may process/discard it)
        BEFORE batch *N+1*'s query is ever issued — peak retained inside the
        source is one batch, not the union across all queries.

        On a wedged loop thread, each step raises ``McpConnectionError``
        rather than hanging. Partial batches already yielded are real data;
        the generator stops at the failed step (it does not silently return
        a truncated full list).
        """
        loop = self._ensure_loop()
        _SENTINEL = object()

        async def _step():
            try:
                return await agen.__anext__()
            except StopAsyncIteration:
                return _SENTINEL

        while True:
            future = asyncio.run_coroutine_threadsafe(_step(), loop)
            try:
                item = future.result(timeout=_ap_sync_timeout_s())
            except FutureTimeoutError as exc:
                future.cancel()
                raise McpConnectionError(
                    "AP reader-thread step exceeded "
                    f"{_ap_sync_timeout_s():.0f}s — subprocess presumed wedged"
                ) from exc
            if item is _SENTINEL:
                return
            yield item

    def close(self) -> None:
        if self._loop and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
            try:
                if self._thread is not None:
                    self._thread.join(timeout=2.0)
            except Exception:
                pass
            try:
                self._loop.close()
            except Exception:
                pass
        self._loop = None
        self._thread = None


def _as_list(payload: Any) -> list[dict]:
    """Normalise AP's ``query_graph`` response into a list of dicts.

    AP's Stage-3a query_graph returns the shape:
        {
          "columns": ["a", "b"],
          "rows":    [["1", "2"], ["3", "4"]],
          "status":  "ok",
          ...
        }

    We zip ``columns`` with each row to produce ``[{"a": "1", "b": "2"}, ...]``.
    Error responses (``status: "error"``) surface as an empty list — the
    caller is already resilient to that case. Plain lists and dicts with a
    ``rows`` key containing dicts are also accepted for forward-compat.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    if payload.get("status") == "error":
        return []
    cols = payload.get("columns")
    rows = payload.get("rows")
    if isinstance(cols, list) and isinstance(rows, list):
        out: list[dict] = []
        for row in rows:
            if isinstance(row, list) and len(row) == len(cols):
                out.append({str(c): row[i] for i, c in enumerate(cols)})
            elif isinstance(row, dict):
                out.append(row)
        return out
    # Older ``{"content": [...]}`` / ``{"data": [...]}`` shapes.
    inner = payload.get("content") or payload.get("data")
    if isinstance(inner, list):
        if inner and isinstance(inner[0], dict) and inner[0].get("type") == "text":
            try:
                parsed = json.loads(inner[0].get("text") or "")
                if isinstance(parsed, list):
                    return [r for r in parsed if isinstance(r, dict)]
            except ValueError:
                return []
        return [r for r in inner if isinstance(r, dict)]
    return []


# AP's node labels carrying symbol semantics. Derived from
# stage-3 tree-sitter extractors; see
# ``automatised-pipeline/src/clustering.rs`` for the canonical list.
_SYMBOL_LABELS = (
    # Core — Rust + Python (original set)
    "Function",
    "Method",
    "Struct",
    "Enum",
    "Trait",
    "Constant",
    "TypeAlias",
    # JVM family — Java, Kotlin
    "Class",
    "Interface",
    "Field",
    "Property",
    # Swift / ObjC family
    "Protocol",
    "Extension",
    # C / C++
    "Union",
    "Typedef",
    "Macro",
    # Go / general
    "Module",
    "Package",
    "Namespace",
    "Variable",
    # Import statements (one node per ``import`` site). AP wires every
    # file to its imports via the ``Defines_File_Import`` rel table; the
    # nodes themselves carry ``id`` (``<file>::<modpath>``), ``path``,
    # ``alias``, ``is_glob``. Loaded via a custom property mapping in
    # ``_load_symbols_async`` because imports lack ``qualified_name``.
    "Import",
)

# Labels whose nodes don't expose ``qualified_name`` / ``name``. The
# load query falls back to ``id`` / ``path`` (or whatever the node
# DOES carry) so they still flow into the graph.
_NON_QUALIFIED_LABELS = {"Import"}


def _symbol_type_from_label(label: str) -> str:
    """Map AP's label → workflow-graph symbol_type.

    Keeps the value set small so the palette (``SYMBOL_COLORS``) stays
    compact. Every AP label from every supported language collapses
    into one of: function · method · class · module · constant.
    """
    low = label.lower()
    if low == "function":
        return "function"
    if low == "method":
        return "method"
    # All type-like constructs → class. Covers Rust (struct/enum/trait),
    # Java/Kotlin (class/interface), Swift/ObjC (protocol/extension),
    # C/C++ (union).
    if low in (
        "struct",
        "enum",
        "trait",
        "class",
        "interface",
        "protocol",
        "extension",
        "union",
    ):
        return "class"
    # Module-ish containers → module (amber).
    if low in ("module", "package", "namespace"):
        return "module"
    # Value-ish / alias-ish → constant (slate).
    if low in (
        "constant",
        "typealias",
        "typedef",
        "macro",
        "field",
        "property",
        "variable",
    ):
        return "constant"
    return low


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
        except Exception:
            pass
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
            except Exception:
                # One corrupt / missing graph never kills the whole stream.
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
            except Exception:
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

    async def _symbol_batches_async(
        self,
        graph_path: str,
        paths: list[str],
    ):
        """Yield one batch of symbol rows per AP label query (async gen).

        AP stores each symbol under its own label (Function, Method,
        Struct, Enum, Trait, Constant, TypeAlias). The qualified_name
        follows ``<relative_file>::<name>``. We query each label
        separately (LadybugDB rejects multi-label ``MATCH``). Each label's
        rows are yielded as soon as its query returns, so the consumer can
        process/discard a label's rows before the next label is queried.

        ``paths`` entries may be absolute (builder convention); AP's
        ``File.id`` and the symbol ``qualified_name`` prefix are
        repo-relative. We match by ``endswith`` so both forms work.
        """
        # Build a set of basenames and tail fragments for fast matching.
        # These are also used to construct server-side WHERE predicates so
        # Kuzu filters by file prefix rather than returning ALL symbols and
        # discarding in Python. Previously the code used a blanket
        # ``LIMIT 500`` without a WHERE clause — on a 50k-symbol codebase
        # alphabetically-early files consume the entire limit and the
        # desired file's symbols are never returned.
        # source: measured 2026-06-04 — query for consolidate.py returned 0
        #   because the first 500 Functions all start with benchmarks/* or
        #   _pipeline/*; mcp_server/handlers/* never appeared.
        path_tails: set[str] = set()
        for p in paths:
            if not p:
                continue
            path_tails.add(p)
            # e.g. /abs/root/pkg/mod.py → pkg/mod.py, mod.py
            parts = p.split("/")
            for i in range(1, len(parts)):
                path_tails.add("/".join(parts[i:]))

        # Build a Cypher WHERE predicate that filters at the Kuzu level.
        # Each tail produces one STARTS WITH predicate on qualified_name
        # (or id for Import nodes). We emit the shortest unique tails only
        # — if "pkg/mod.py" is present, "mod.py" is redundant because any
        # match for "mod.py" also matches "pkg/mod.py". Cap at 10 tails
        # to keep the WHERE clause tractable.
        def _where_for_tails(prop: str, tails: set[str]) -> str:
            if not tails:
                return ""
            # Sort longest-first so shorter redundant tails are skipped.
            sorted_tails = sorted(tails, key=len, reverse=True)
            kept: list[str] = []
            for t in sorted_tails:
                if any(t == k or k.endswith(t) for k in kept):
                    continue  # already covered by a longer tail
                kept.append(t)
                if len(kept) >= 10:
                    break
            escaped = [t.replace("'", "\\'") for t in kept]
            preds = " OR ".join(f"{prop} STARTS WITH '{t}::'" for t in escaped)
            return f" WHERE {preds}"

        for label in _SYMBOL_LABELS:
            # Import nodes don't carry qualified_name / name — they use
            # ``id`` (``<file>::<modpath>``) and ``path`` (the imported
            # module). Use those as the qualified_name / name surrogate.
            if label in _NON_QUALIFIED_LABELS:
                prop = "s.id"
                select = (
                    f"MATCH (s:{label})"
                    "{where}"
                    " RETURN s.id   AS qualified_name,"
                    "        s.path AS name"
                )
            else:
                prop = "s.qualified_name"
                select = (
                    f"MATCH (s:{label})"
                    "{where}"
                    " RETURN s.qualified_name AS qualified_name,"
                    "        s.name           AS name"
                )
            if paths:
                where = _where_for_tails(prop, path_tails)
                query = select.format(where=where)
            else:
                # Load-all mode: no filter, no limit — pull the full graph.
                query = select.format(where="")
            rows = await self._bridge.call(
                "query_graph",
                {"graph_path": graph_path, "query": query},
            )
            # Per-label batch: built, yielded, then dropped before the next
            # label's query runs — peak retained inside the source is one
            # label's rows, not the union across all _SYMBOL_LABELS queries.
            batch: list[dict[str, Any]] = []
            for r in _as_list(rows):
                qn = r.get("qualified_name")
                if not qn:
                    continue
                qn_s = str(qn)
                file_part, sep, _ = qn_s.partition("::")
                if not sep:
                    continue
                # Python-side match as a secondary safeguard (the WHERE
                # clause is the primary filter; this handles edge cases
                # where a shorter tail matched a different file).
                if path_tails and not any(
                    p == file_part or p.endswith(file_part) or file_part.endswith(p)
                    for p in path_tails
                ):
                    continue
                # Resolve file_path back to the absolute form if possible.
                abs_match = next(
                    (p for p in paths if p.endswith(file_part)),
                    file_part,
                )
                batch.append(
                    {
                        "file_path": abs_match,
                        "qualified_name": qn_s,
                        "symbol_type": _symbol_type_from_label(label),
                        "signature": None,
                        "language": None,
                        "line": None,
                    }
                )
            if batch:
                yield batch

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
        for r in _as_list(resp):
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
        """Batch verification across every AP symbol label.

        AP has no unified ``Symbol`` label — we iterate the known set
        (Function, Method, Struct, ...). Wiki references are usually
        bare names (``WorkflowGraphBuilder``), so we widen the match:
        a qualname counts as found if any AP symbol name equals it,
        its name equals the tail, or the qualified_name endswith the
        tail (``::tail`` or ``.tail``).
        """
        out: dict[str, bool] = {q: False for q in qualnames}
        all_names: list[str] = []
        all_short: list[str] = []
        for label in _SYMBOL_LABELS:
            query = (
                f"MATCH (s:{label}) "
                "RETURN DISTINCT s.qualified_name AS qualified_name, "
                "                s.name           AS name"
            )
            rows = await self._bridge.call(
                "query_graph",
                {"graph_path": graph_path, "query": query},
            )
            for r in _as_list(rows):
                qn = str(r.get("qualified_name") or "")
                nm = str(r.get("name") or "")
                if qn:
                    all_names.append(qn)
                if nm:
                    all_short.append(nm)
        for q in qualnames:
            tail = q.rsplit(".", 1)[-1]
            if tail in all_short:
                out[q] = True
                continue
            for qn in all_names:
                if qn == q or qn.endswith(f"::{tail}") or qn.endswith(f".{tail}"):
                    out[q] = True
                    break
        return out

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

    async def _edge_batches_async(
        self,
        graph_path: str,
        paths: list[str],
    ):
        """Yield one batch of edge rows per AP rel-table query (async gen).

        AP uses per-label-pair typed rel tables (LadybugDB convention):
          * Calls_<Src>_<Dst>   for Function↔Method call edges
          * Imports_File_<Lbl>  for File → imported symbol
          * HasMethod_<Parent>_Method for struct/enum/trait → method

        We enumerate the known rel tables (~89 queries) and collapse them to
        the semantic kinds the builder understands. Each rel-table's rows are
        yielded as its own batch the moment its query returns, so peak rows
        retained inside the source is one rel-table's result — not the union
        across all 89 queries.
        """
        # Same path-matching strategy as ``_symbol_batches_async``.
        path_tails: set[str] = set()
        for p in paths:
            if not p:
                continue
            path_tails.add(p)
            parts = p.split("/")
            for i in range(1, len(parts)):
                path_tails.add("/".join(parts[i:]))
        # Enumerate the full Cartesian product of label kinds AP could
        # have produced rel tables for. AP rejects queries against rel
        # tables that don't exist by returning empty rows, so the over-
        # enumeration is safe — it just costs extra round-trips against
        # missing tables. The narrower prior lists were the reason the
        # cortex viz showed ~4k imports instead of the tens of thousands
        # the codebase actually contains: every File→Class / File→
        # Interface / File→TypeAlias / File→Macro etc. edge was being
        # silently dropped because its rel table was never queried.
        _CALL_LABELS = ("Function", "Method", "Macro")
        _IMPORT_TARGETS = _SYMBOL_LABELS  # File can import any symbol kind
        _CONTAINER_LBLS = (
            "Struct",
            "Enum",
            "Trait",
            "Class",
            "Interface",
            "Protocol",
            "Extension",
            "Union",
        )
        _MEMBER_LBLS = ("Method", "Field", "Property", "Constant", "TypeAlias")
        calls_rels = [(s, d) for s in _CALL_LABELS for d in _CALL_LABELS]
        imports_rels = [("File", t) for t in _IMPORT_TARGETS]
        member_rels = [(s, d) for s in _CONTAINER_LBLS for d in _MEMBER_LBLS]

        def _match(file_part: str) -> bool:
            if not path_tails:
                return True
            return any(
                p == file_part or p.endswith(file_part) or file_part.endswith(p)
                for p in path_tails
            )

        async def _run_edge(
            kind: str,
            table: str,
            src_lbl: str,
            dst_lbl: str,
            has_provenance: bool,
        ) -> list[dict[str, Any]]:
            """Query AP for edges of ``kind`` in ``table`` and RETURN this
            rel-table's rows as one batch (the caller yields it, then drops
            it before the next rel-table query — bounding peak to one batch).

            ``has_provenance`` gates whether to fetch ``r.confidence`` +
            ``r.resolution_method``: Kuzu raises a Binder exception on
            missing-property access, so we only request those columns
            for rel tables the AP resolver actually annotates (Calls_*
            / Imports_* / Implements_* / Extends_* / Uses_*). Structural
            tables (HasMethod_* / Defines_*) have no such columns —
            callers default confidence to 1.0 for those kinds instead.
            """
            if src_lbl == "File":
                select_src = "src.id AS src_name"
            elif src_lbl in _NON_QUALIFIED_LABELS:
                select_src = "src.id AS src_name"
            else:
                select_src = "src.qualified_name AS src_name"
            # Import nodes (and any other ``_NON_QUALIFIED_LABELS`` kind)
            # carry ``id`` instead of ``qualified_name``. Selecting the
            # missing property would raise a Kuzu Binder exception.
            dst_qn = (
                "dst.id AS dst_name"
                if dst_lbl in _NON_QUALIFIED_LABELS
                else "dst.qualified_name AS dst_name"
            )
            if has_provenance:
                return_tail = (
                    f"       {dst_qn}, "
                    "       r.confidence       AS confidence, "
                    "       r.resolution_method AS reason"
                )
            else:
                return_tail = f"       {dst_qn}"
            query = (
                f"MATCH (src:{src_lbl})-[r:{table}]->(dst:{dst_lbl}) "
                f"RETURN {select_src}, {return_tail}"
            )
            rows = await self._bridge.call(
                "query_graph",
                {"graph_path": graph_path, "query": query},
            )
            batch: list[dict[str, Any]] = []
            for r in _as_list(rows):
                src = str(r.get("src_name") or "")
                dst = str(r.get("dst_name") or "")
                if not dst:
                    continue
                # src may be a File.id (relative path) or a symbol qn.
                if src_lbl == "File":
                    src_file = src
                    src_qn = ""
                else:
                    src_file, _, _ = src.partition("::")
                    src_qn = src
                dst_file, _, _ = dst.partition("::")
                if kind == "imports":
                    if not _match(src_file):
                        continue
                else:
                    if not (_match(src_file) and _match(dst_file)):
                        continue
                # AP stores ``resolution_method`` wrapped in literal
                # single quotes (see ``automatised-pipeline``
                # resolver.rs:183 — ``format!("'{method}'")``), so the
                # value comes back INCLUDING quotes. Strip them here at
                # the infrastructure boundary. Remove this strip once
                # AP fixes the upstream quoting.
                conf_raw = r.get("confidence") if has_provenance else None
                try:
                    confidence = float(conf_raw) if conf_raw is not None else None
                except (TypeError, ValueError):
                    confidence = None
                reason_raw = r.get("reason") if has_provenance else None
                reason_str = (
                    str(reason_raw).strip("'\"") or None if reason_raw else None
                )
                batch.append(
                    {
                        "kind": kind,
                        "src_file": src_file,
                        "src_name": src_qn,
                        "dst_file": dst_file,
                        "dst_name": dst,
                        "confidence": confidence,
                        "reason": reason_str,
                    }
                )
            return batch

        for s, d in calls_rels:
            yield await _run_edge("calls", f"Calls_{s}_{d}", s, d, has_provenance=True)
        for s, d in imports_rels:
            yield await _run_edge(
                "imports", f"Imports_{s}_{d}", s, d, has_provenance=True
            )
        for s, d in member_rels:
            yield await _run_edge(
                "member_of", f"HasMethod_{s}_{d}", s, d, has_provenance=False
            )
        # File → Import node. AP wires every ``import`` statement to its
        # file via this rel table; counts in the tens of thousands per
        # project. Without this, the cortex viz captures only the small
        # subset that AP managed to RESOLVE to in-graph symbols (the
        # ``Imports_File_*`` tables, totalling ~5k vs ~36k actual).
        yield await _run_edge(
            "imports",
            "Defines_File_Import",
            "File",
            "Import",
            has_provenance=False,
        )
        # Type-usage edges (Method/Function uses Struct/Class/etc).
        # Captured by AP's resolver and exposed as ``Uses_<src>_<dst>``.
        _USES_SRC = ("Method", "Function")
        _USES_DST = (
            "Struct",
            "Enum",
            "Trait",
            "Class",
            "Interface",
            "Protocol",
            "Extension",
            "Union",
            "TypeAlias",
        )
        for s in _USES_SRC:
            for d in _USES_DST:
                yield await _run_edge(
                    "uses", f"Uses_{s}_{d}", s, d, has_provenance=True
                )


__all__ = ["WorkflowGraphASTSource"]
