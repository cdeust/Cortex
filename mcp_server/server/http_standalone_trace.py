"""HTTP endpoints for the domain-split execution-trace graph.

Live, no-snapshot serving of the four navigation levels:

    GET /api/trace/domains            -> L0 domain hubs
    GET /api/trace/sessions?domain=   -> L1 sessions + has_session edges
    GET /api/trace/chain?session=     -> L2 ordered prompt/action/file chain
    GET /api/trace/file?path=         -> L3 file drill (AST + impact + git)

Each reads live from JSONL / AP graph / git per request — nothing cached
to disk.
"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from mcp_server.server.http_standalone_response import (
    send_json_error,
    send_json_ok,
)


def _param(handler, key: str) -> str:
    qs = parse_qs(urlparse(handler.path).query)
    vals = qs.get(key)
    return unquote(vals[0]) if vals else ""


def serve_trace_domains(handler) -> None:
    """GET /api/trace/domains — collapsed domain hubs (L0)."""
    try:
        from mcp_server.infrastructure.trace_source import list_domains

        nodes = list_domains()
        send_json_ok(
            handler,
            {"nodes": nodes, "edges": [], "meta": {"schema": "trace.v1", "level": 0}},
        )
    except Exception as e:
        send_json_error(handler, e)


def serve_trace_sessions(handler) -> None:
    """GET /api/trace/sessions?domain=<domain:id> — sessions in a domain (L1)."""
    try:
        from mcp_server.infrastructure.trace_source import list_sessions

        domain = _param(handler, "domain")
        if not domain:
            send_json_ok(handler, {"nodes": [], "edges": [], "error": "missing domain"})
            return
        payload = list_sessions(domain)
        payload["meta"] = {"schema": "trace.v1", "level": 1, "domain": domain}
        send_json_ok(handler, payload)
    except Exception as e:
        send_json_error(handler, e)


def serve_trace_chain(handler) -> None:
    """GET /api/trace/chain?session=<sid> — ordered causal chain (L2)."""
    try:
        from mcp_server.core.session_trace import build_chain
        from mcp_server.infrastructure.trace_source import iter_session_events

        sid = _param(handler, "session")
        if not sid:
            send_json_ok(handler, {"nodes": [], "edges": [], "error": "missing session"})
            return
        # ``since`` = chain steps the client already holds (live tail poll).
        # 0/absent → whole chain. Out-of-range → empty delta (dedup-safe).
        try:
            since = int(_param(handler, "since") or "0")
        except ValueError:
            since = 0
        events = iter_session_events(sid)
        payload = build_chain(events, sid, since=since)
        payload["meta"] = {
            "schema": "trace.v1",
            "level": 2,
            "session": sid,
            "event_count": len(events),
            "since": since,
        }
        send_json_ok(handler, payload)
    except Exception as e:
        send_json_error(handler, e)


def _git_history(path: str) -> dict:
    """Working-tree/last-commit diff + when-changed for one file."""
    try:
        from mcp_server.infrastructure.git_diff import find_git_root, get_file_diff

        root = find_git_root()
        if root is None:
            return {"available": False}
        diff = get_file_diff(path, root)
        return {
            "available": True,
            "diff_type": diff.get("diff_type"),
            "lines": diff.get("lines", []),
            "truncated": diff.get("truncated", False),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "error": str(exc)}


# ── AP AST source: ONE warm instance per viz process ───────────────────
# WorkflowGraphASTSource pins a single event loop on a dedicated thread
# (_SyncLoop) and keeps the AP MCP connection alive across calls. The old
# code spawned a fresh APBridge + asyncio.run() per request, which failed
# to connect from the detached viz subprocess ("connect_failed"). A
# module-level singleton connects once and is reused, and its label-by-
# label queries match AP's LadybugDB schema (a single multi-label MATCH
# is rejected by the engine). source: 2026-05-31 Phase 2 warm-pool.
_AST_SOURCE = None
_AST_SOURCE_LOCK = None


def _get_ast_source():
    global _AST_SOURCE, _AST_SOURCE_LOCK
    if _AST_SOURCE_LOCK is None:
        import threading

        _AST_SOURCE_LOCK = threading.Lock()
    with _AST_SOURCE_LOCK:
        if _AST_SOURCE is None:
            from mcp_server.infrastructure.workflow_graph_source_ast import (
                WorkflowGraphASTSource,
            )

            _AST_SOURCE = WorkflowGraphASTSource()
        return _AST_SOURCE


def _ast_and_impact(path: str) -> dict:
    """AST symbols defined in the file + downstream impact of the first
    symbol, via the warm AP source. Degrades gracefully to
    ``{available: False, reason}`` when AP is off / unreachable."""
    try:
        from mcp_server.infrastructure import ap_bridge

        if not ap_bridge.is_enabled():
            return {"available": False, "reason": "ap_disabled"}

        src = _get_ast_source()
        # load_symbols([path]) returns rows shaped
        # {file_path, qualified_name, symbol_type, signature, language,
        #  line, domain} — matched by path tail, so abs or repo-relative
        # both work.
        symbols = src.load_symbols([path]) or []
        if not symbols:
            return {"available": True, "symbols": [], "impact": []}

        # Blast-radius for the first symbol (cheap, illustrative). The
        # panel can request more on demand later.
        impact = []
        try:
            from mcp_server.infrastructure.ap_bridge import (
                APBridge,
                resolve_graph_paths,
            )

            qn = symbols[0].get("qualified_name")
            graph_paths = resolve_graph_paths()
            if qn and graph_paths:
                # Reuse the warm source's pinned loop + bridge.
                impact_raw = src._loop_owner.run(  # noqa: SLF001
                    src._bridge.get_impact(graph_paths[0], qn)  # noqa: SLF001
                )
                if isinstance(impact_raw, dict):
                    impact = (
                        impact_raw.get("processes")
                        or impact_raw.get("communities")
                        or impact_raw.get("impacted")
                        or []
                    )
                elif isinstance(impact_raw, list):
                    impact = impact_raw
        except Exception:
            impact = []

        return {"available": True, "symbols": symbols, "impact": impact}
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "error": str(exc)}


def serve_trace_file(handler) -> None:
    """GET /api/trace/file?path=<p> — L3 file drill: AST + impact + git."""
    try:
        path = _param(handler, "path")
        if not path:
            send_json_ok(handler, {"error": "missing path"})
            return
        send_json_ok(
            handler,
            {
                "path": path,
                "git": _git_history(path),
                "ast": _ast_and_impact(path),
                "meta": {"schema": "trace.v1", "level": 3},
            },
        )
    except Exception as e:
        send_json_error(handler, e)


def _basename(p: str) -> str:
    return (p or "").replace("\\", "/").rstrip("/").split("/")[-1]


def _impact_for_graph(graph_path: str, rel_path: str) -> dict | None:
    """Run the exact-path impact queries against ONE code-graph.

    Returns ``{downstream, upstream, members}`` or None if the file has no
    symbols in this graph (so the caller can try the next graph). Uses
    targeted Cypher with a ``STARTS WITH '<rel>::'`` filter on
    qualified_name — fast + exact (no cross-file collisions, no full-graph
    label-pair enumeration). Edge kinds: calls (Function/Method), imports
    (File→symbol), member (container→method).
    """
    from mcp_server.infrastructure.workflow_graph_source_ast import _as_list

    # Reuse the warm AST source's pinned loop + persistent AP connection.
    # A fresh APBridge + asyncio.run() per HTTP request collides with the
    # warm bridge on the same AP subprocess (relationship MATCH queries
    # silently returned 0 over HTTP while single-node MATCH worked). The
    # source serializes every call onto one loop, which is reliable.
    src = _get_ast_source()
    loop_run = src._loop_owner.run  # noqa: SLF001
    bridge = src._bridge            # noqa: SLF001

    async def _run() -> dict | None:
        if True:
            async def q(cypher):
                rows = await bridge.query_graph(graph_path, cypher)
                return _as_list(rows)

            # Does this graph even contain the file? (cheap gate)
            present = await q(
                "MATCH (f:File) WHERE f.id = '%s' RETURN f.id AS id LIMIT 1"
                % rel_path.replace("'", "")
            )
            if not present:
                return None

            esc = rel_path.replace("'", "")
            # downstream calls: a function defined in this file → callee
            calls = await q(
                "MATCH (s:Function)-[r:Calls_Function_Function]->(d:Function) "
                "WHERE s.qualified_name STARTS WITH '%s::' "
                "RETURN DISTINCT d.qualified_name AS name, r.confidence AS conf "
                "LIMIT 200" % esc
            )
            # downstream imports: this File imports symbol
            imports = await q(
                "MATCH (f:File)-[r:Imports_File_Function]->(d:Function) "
                "WHERE f.id = '%s' "
                "RETURN DISTINCT d.qualified_name AS name, r.confidence AS conf "
                "LIMIT 200" % esc
            )
            # upstream: who calls a function in this file
            callers = await q(
                "MATCH (s:Function)-[r:Calls_Function_Function]->(d:Function) "
                "WHERE d.qualified_name STARTS WITH '%s::' "
                "RETURN DISTINCT s.qualified_name AS name, r.confidence AS conf "
                "LIMIT 200" % esc
            )
            # members: methods/functions defined in this file
            members_rows = await q(
                "MATCH (s:Function) WHERE s.qualified_name STARTS WITH '%s::' "
                "RETURN DISTINCT s.qualified_name AS name LIMIT 200" % esc
            )

            def _file_of(qn):
                return str(qn or "").partition("::")[0]

            def _short_name(qn):
                return str(qn or "").split("::")[-1]

            def _conf(r):
                try:
                    return float(r.get("conf")) if r.get("conf") is not None else None
                except (TypeError, ValueError):
                    return None

            downstream = []
            for r in calls + imports:
                nm = r.get("name")
                if not nm:
                    continue
                downstream.append({
                    "file": _file_of(nm), "name": nm, "label": _short_name(nm),
                    "kind": "calls" if r in calls else "imports", "confidence": _conf(r),
                })
            upstream = [
                {"file": _file_of(r.get("name")), "name": r.get("name"),
                 "label": _short_name(r.get("name")), "kind": "calls",
                 "confidence": _conf(r)}
                for r in callers if r.get("name")
            ]
            members = [
                {"file": rel_path, "name": r.get("name"),
                 "label": _short_name(r.get("name")), "kind": "member",
                 "confidence": None}
                for r in members_rows if r.get("name")
            ]
            return {"downstream": downstream, "upstream": upstream, "members": members}

    return loop_run(_run())


def serve_trace_impact(handler) -> None:
    """GET /api/trace/impact?path=<file> — dependency/impact subgraph.

    Blast-radius for a file from the AP code-graph:
      * downstream — what this file calls / imports (it depends on these)
      * upstream   — what calls this file (these break if it changes)
      * members    — symbols this file defines
    Queries the FIRST code-graph that contains the file (exact File.id
    match), so it hits the Cortex graph for a Cortex path rather than
    scanning all 6 graphs. ``{available: False, reason}`` when off / not
    indexed.
    """
    try:
        from mcp_server.infrastructure import ap_bridge

        path = _param(handler, "path")
        if not path:
            send_json_ok(handler, {"available": False, "reason": "missing path"})
            return
        if not ap_bridge.is_enabled():
            send_json_ok(handler, {"available": False, "reason": "ap_disabled"})
            return

        rel = path.replace("\\", "/").lstrip("./")
        # Several graphs may contain the same relative path (a stale legacy
        # index AND the fresh Cortex code-graph). The first hit can be the
        # stale one with members-only and no edges, so pick the RICHEST
        # result (most call/import edges) across all graphs that have it.
        result = None
        best_edges = -1
        for gp in ap_bridge.resolve_graph_paths():
            try:
                r = _impact_for_graph(gp, rel)
            except Exception:
                r = None
            if r is None:
                continue
            n = len(r.get("downstream", [])) + len(r.get("upstream", [])) \
                + len(r.get("members", []))
            if n > best_edges:
                best_edges = n
                result = r

        if result is None:
            send_json_ok(handler, {
                "available": False, "reason": "not_indexed", "path": path,
                "center": {"file": path, "label": _basename(path)},
            })
            return

        result.update({
            "available": True, "path": path,
            "center": {"file": path, "label": _basename(path)},
            "meta": {"schema": "trace.v1", "level": 4},
        })
        send_json_ok(handler, result)
    except Exception as e:
        send_json_error(handler, e)


__all__ = [
    "serve_trace_domains",
    "serve_trace_sessions",
    "serve_trace_chain",
    "serve_trace_file",
    "serve_trace_impact",
]
