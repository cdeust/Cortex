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


__all__ = [
    "serve_trace_domains",
    "serve_trace_sessions",
    "serve_trace_chain",
    "serve_trace_file",
]
