"""AST-backed loader for the workflow graph (ADR-0046).

Peer of ``workflow_graph_source_pg`` / ``workflow_graph_source_jsonl``.
Calls the ``automatised-pipeline`` MCP server via ``ap_bridge`` and
returns builder-shaped dicts for symbol nodes and the AST edges
(``defined_in``, ``calls``, ``imports``, ``member_of``).

Constrained to the Cortex-known file set: AP may have indexed files
that Cortex doesn't know about (e.g. vendored dependencies); we filter
so the graph stays focused on what the user's sessions actually touch.

Pure infrastructure — no core imports. When ``CORTEX_ENABLE_AP`` is
off (default) or AP is unreachable, every loader returns ``[]`` so
the workflow graph degrades to the baseline.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Iterable

from mcp_server.infrastructure.ap_bridge import (
    APBridge,
    is_enabled,
    resolve_graph_path,
    resolve_graph_paths,
)

# A paranoid cap so a bad Cypher can't drag in the world. Matches
# AP's default page size for ``query_graph``.
_MAX_SYMBOLS_PER_FILE = 500


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
            return asyncio.run_coroutine_threadsafe(coro, loop).result()
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
            import threading

            def _run_forever():
                asyncio.set_event_loop(self._loop)
                self._loop.run_forever()

            self._thread = threading.Thread(
                target=_run_forever,
                name="ap-sync-loop",
                daemon=True,
            )
            self._thread.start()
        return self._loop

    def run(self, coro):
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

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
)


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

    def load_symbols(
        self,
        file_paths: Iterable[str],
    ) -> list[dict[str, Any]]:
        """Return one row per AST symbol defined in a file Cortex knows
        about. Row shape: ``{file_path, qualified_name, symbol_type,
        signature, language, line, domain}``. ``domain`` is always ``""``
        — the builder infers it from the file node.
        """
        if not is_enabled():
            return []
        graph_paths = resolve_graph_paths()
        if not graph_paths:
            return []
        paths = [p for p in file_paths if p]

        async def _gather():
            out: list[dict[str, Any]] = []
            for gp in graph_paths:
                try:
                    rows = await self._load_symbols_async(gp, paths)
                    out.extend(rows)
                except Exception:
                    # One bad graph (corrupt / missing) never kills the
                    # whole visualization.
                    continue
            return out

        return self._loop_owner.run(_gather())

    def load_ast_edges(
        self,
        file_paths: Iterable[str],
    ) -> list[dict[str, Any]]:
        """Return CALLS / IMPORTS / MEMBER_OF edges across every
        project graph. Empty ``file_paths`` means "no path filter"."""
        if not is_enabled():
            return []
        graph_paths = resolve_graph_paths()
        if not graph_paths:
            return []
        paths = [p for p in file_paths if p]

        async def _gather():
            out: list[dict[str, Any]] = []
            for gp in graph_paths:
                try:
                    rows = await self._load_edges_async(gp, paths)
                    out.extend(rows)
                except Exception:
                    continue
            return out

        return self._loop_owner.run(_gather())

    async def _load_symbols_async(
        self,
        graph_path: str,
        paths: list[str],
    ) -> list[dict[str, Any]]:
        """Pull all symbols whose owning file ∈ ``paths``.

        AP stores each symbol under its own label (Function, Method,
        Struct, Enum, Trait, Constant, TypeAlias). The qualified_name
        follows ``<relative_file>::<name>``. We query each label
        separately (LadybugDB rejects multi-label ``MATCH``).

        ``paths`` entries may be absolute (builder convention); AP's
        ``File.id`` and the symbol ``qualified_name`` prefix are
        repo-relative. We match by ``endswith`` so both forms work.
        """
        out: list[dict[str, Any]] = []
        # Build a set of basenames and tail fragments for fast matching.
        path_tails: set[str] = set()
        for p in paths:
            if not p:
                continue
            path_tails.add(p)
            # e.g. /abs/root/pkg/mod.py → pkg/mod.py, mod.py
            parts = p.split("/")
            for i in range(1, len(parts)):
                path_tails.add("/".join(parts[i:]))
        for label in _SYMBOL_LABELS:
            query = (
                f"MATCH (s:{label}) "
                "RETURN s.qualified_name AS qualified_name, "
                "       s.name           AS name "
                f"LIMIT {_MAX_SYMBOLS_PER_FILE * max(len(paths), 1)}"
            )
            rows = await self._bridge.call(
                "query_graph",
                {"graph_path": graph_path, "query": query},
            )
            for r in _as_list(rows):
                qn = r.get("qualified_name")
                if not qn:
                    continue
                qn_s = str(qn)
                file_part, sep, _ = qn_s.partition("::")
                if not sep:
                    continue
                # Match the symbol's file against the known set.
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
                out.append(
                    {
                        "file_path": abs_match,
                        "qualified_name": qn_s,
                        "symbol_type": _symbol_type_from_label(label),
                        "signature": None,
                        "language": None,
                        "line": None,
                    }
                )
        return out

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
            self._bridge.call(
                "search_codebase",
                {"graph_path": gp, "query": query, "limit": int(limit)},
            )
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
        """Pull CALLS / IMPORTS / MEMBER_OF edges from the AP graph.

        AP uses per-label-pair typed rel tables (LadybugDB convention):
          * Calls_<Src>_<Dst>   for Function↔Method call edges
          * Imports_File_<Lbl>  for File → imported symbol
          * HasMethod_<Parent>_Method for struct/enum/trait → method

        We enumerate the known rel tables and collapse them to the
        three semantic kinds the builder understands.
        """
        out: list[dict[str, Any]] = []
        # Same path-matching strategy as ``_load_symbols_async``.
        path_tails: set[str] = set()
        for p in paths:
            if not p:
                continue
            path_tails.add(p)
            parts = p.split("/")
            for i in range(1, len(parts)):
                path_tails.add("/".join(parts[i:]))
        calls_rels = [
            ("Function", "Function"),
            ("Function", "Method"),
            ("Method", "Function"),
            ("Method", "Method"),
        ]
        imports_rels = [
            ("File", "Function"),
            ("File", "Struct"),
            ("File", "Enum"),
            ("File", "Trait"),
            ("File", "Method"),
            ("File", "Constant"),
        ]
        member_rels = [
            ("Struct", "Method"),
            ("Enum", "Method"),
            ("Trait", "Method"),
        ]

        def _match(file_part: str) -> bool:
            if not path_tails:
                return True
            return any(
                p == file_part or p.endswith(file_part) or file_part.endswith(p)
                for p in path_tails
            )

        async def _run_edge(kind: str, table: str, src_lbl: str, dst_lbl: str):
            if src_lbl == "File":
                select_src = "src.id AS src_name"
            else:
                select_src = "src.qualified_name AS src_name"
            query = (
                f"MATCH (src:{src_lbl})-[:{table}]->(dst:{dst_lbl}) "
                f"RETURN {select_src}, "
                "       dst.qualified_name AS dst_name"
            )
            rows = await self._bridge.call(
                "query_graph",
                {"graph_path": graph_path, "query": query},
            )
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
                out.append(
                    {
                        "kind": kind,
                        "src_file": src_file,
                        "src_name": src_qn,
                        "dst_file": dst_file,
                        "dst_name": dst,
                    }
                )

        for s, d in calls_rels:
            await _run_edge("calls", f"Calls_{s}_{d}", s, d)
        for s, d in imports_rels:
            await _run_edge("imports", f"Imports_{s}_{d}", s, d)
        for s, d in member_rels:
            await _run_edge("member_of", f"HasMethod_{s}_{d}", s, d)
        return out


__all__ = ["WorkflowGraphASTSource"]
