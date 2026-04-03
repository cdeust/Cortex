"""Unified visualization HTTP server.

Singleton server combining methodology graph and memory data
into a single interactive visualization. Auto-shuts down after
10 minutes of inactivity.
"""

from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from mcp_server.server.http_common import (
    get_ui_root,
    read_html_file,
    send_cors_options,
    send_error_response,
    send_html_response,
    send_json_response,
    serve_static_file,
)
from mcp_server.server.http_dashboard_data import (
    format_entity,
    format_memory,
    format_relationship,
)

_unified_server: dict | None = None
_unified_idle_timer: threading.Timer | None = None
_unified_lock = threading.Lock()


def _reset_unified_idle_timer() -> None:
    """Reset the unified viz idle timer."""
    global _unified_idle_timer, _unified_server
    if _unified_idle_timer:
        _unified_idle_timer.cancel()

    def _shutdown():
        global _unified_server
        with _unified_lock:
            if _unified_server:
                _unified_server["server"].shutdown()
                _unified_server = None
                print(
                    "[cortex] Unified viz stopped (idle timeout)",
                    file=sys.stderr,
                )

    _unified_idle_timer = threading.Timer(600.0, _shutdown)
    _unified_idle_timer.daemon = True
    _unified_idle_timer.start()


def _parse_query_params(path: str) -> dict:
    """Parse query string into domain_filter, batch, batch_size."""
    result = {"domain_filter": None, "batch": 0, "batch_size": 0}
    if "?" not in path:
        return result

    params = path.split("?", 1)[1]
    for p in params.split("&"):
        if p.startswith("domain="):
            result["domain_filter"] = p[7:]
        elif p.startswith("batch="):
            try:
                result["batch"] = int(p[6:])
            except ValueError:
                pass
        elif p.startswith("batch_size="):
            try:
                result["batch_size"] = int(p[11:])
            except ValueError:
                pass
    return result


def start_unified_viz_server(profiles_getter, store_getter) -> str:
    """Start the unified visualization HTTP server. Returns URL."""
    global _unified_server

    with _unified_lock:
        if _unified_server:
            _reset_unified_idle_timer()
            return _unified_server["url"]

    ui_root = get_ui_root()
    html_path = ui_root / "unified-viz.html"
    js_dir = ui_root / "unified" / "js"
    css_dir = ui_root / "unified"
    html_content = read_html_file(html_path, "unified viz file")
    cached_html = html_content.encode("utf-8")

    handler_cls = _build_unified_handler(
        profiles_getter, store_getter, html_path, cached_html, js_dir, css_dir
    )
    return _bind_and_start(handler_cls, 3458)


def _build_unified_handler(
    profiles_getter, store_getter, html_path, cached_html, js_dir, css_dir
) -> type:
    """Build the UnifiedHandler class with bound context."""

    class UnifiedHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            send_cors_options(self)

        def do_GET(self):
            _reset_unified_idle_timer()
            base = self.path.split("?")[0]
            if base == "/api/graph":
                self._serve_graph_api()
            elif base == "/api/timeline":
                self._serve_timeline_api()
            elif base == "/api/local-graph":
                self._serve_local_graph_api()
            elif base == "/api/backlinks":
                self._serve_backlinks_api()
            elif base == "/api/entity":
                self._serve_entity_api()
            elif self.path.startswith("/js/") and self.path.endswith(".js"):
                serve_static_file(self, js_dir, self.path[4:], "application/javascript")
            elif self.path.startswith("/css/") and self.path.endswith(".css"):
                serve_static_file(self, css_dir, self.path[5:], "text/css")
            else:
                send_html_response(self, html_path, cached_html)

        def do_POST(self):
            _reset_unified_idle_timer()
            base = self.path.split("?")[0]
            if base == "/api/memory":
                self._serve_update_memory_api()
            else:
                send_error_response(self, ValueError("Unknown POST endpoint"))

        def _serve_graph_api(self):
            try:
                data = _build_graph_response(profiles_getter, store_getter, self.path)
                send_json_response(self, data)
            except Exception as e:
                send_error_response(self, e)

        def _serve_timeline_api(self):
            try:
                data = _build_timeline_response(store_getter, self.path)
                send_json_response(self, data)
            except Exception as e:
                send_error_response(self, e)

        def _serve_local_graph_api(self):
            try:
                data = _build_local_graph_response(store_getter, self.path)
                send_json_response(self, data)
            except Exception as e:
                send_error_response(self, e)

        def _serve_backlinks_api(self):
            try:
                data = _build_backlinks_response(store_getter, self.path)
                send_json_response(self, data)
            except Exception as e:
                send_error_response(self, e)

        def _serve_entity_api(self):
            try:
                from mcp_server.server.http_viz_api import (
                    handle_entity_detail, parse_single_param,
                )
                eid = parse_single_param(self.path, "entity_id")
                if not eid:
                    send_error_response(self, ValueError("entity_id required"))
                    return
                data = handle_entity_detail(store_getter, int(eid))
                send_json_response(self, data)
            except Exception as e:
                send_error_response(self, e)

        def _serve_update_memory_api(self):
            try:
                from mcp_server.server.http_viz_api import (
                    handle_update_memory, read_json_body,
                )
                body = read_json_body(self)
                if not body:
                    send_error_response(self, ValueError("JSON body required"))
                    return
                data = handle_update_memory(store_getter, body)
                send_json_response(self, data)
            except Exception as e:
                send_error_response(self, e)

        def log_message(self, format, *args):
            pass

    return UnifiedHandler


def _build_graph_response(profiles_getter, store_getter, path: str) -> dict:
    """Fetch data from stores and build the unified graph response."""
    from mcp_server.core.unified_graph_builder import build_unified_graph

    profiles = profiles_getter()
    store = store_getter()
    memories = store.get_hot_memories(min_heat=0.0, limit=2000)
    entities = store.get_all_entities(min_heat=0.0)
    relationships = store.get_all_relationships()

    # Materialized memory-entity links (from memory_entities join table)
    memory_entity_links = []
    try:
        rows = store._conn.execute(
            "SELECT memory_id, entity_id, confidence FROM memory_entities"
        ).fetchall()
        memory_entity_links = [dict(r) for r in rows]
    except Exception:
        pass

    params = _parse_query_params(path)

    result = build_unified_graph(
        profiles=profiles,
        memories=[format_memory(m, 500) for m in memories],
        entities=[format_entity(e) for e in entities],
        relationships=[format_relationship(r) for r in relationships],
        filter_domain=params["domain_filter"],
        batch=params["batch"],
        batch_size=params["batch_size"],
        memory_entity_links=memory_entity_links,
    )

    # System vitals — aggregated from already-fetched memories, no new queries
    stages: dict[str, int] = {}
    heats: list[float] = []
    episodic = 0
    semantic = 0
    for m in memories:
        s = m.get("consolidation_stage", "labile")
        stages[s] = stages.get(s, 0) + 1
        heats.append(m.get("heat", 0))
        if m.get("store_type") == "episodic":
            episodic += 1
        elif m.get("store_type") == "semantic":
            semantic += 1

    result["meta"]["system_vitals"] = {
        "consolidation_pipeline": stages,
        "mean_heat": round(sum(heats) / max(len(heats), 1), 4),
        "total_memories": len(memories),
        "episodic": episodic,
        "semantic": semantic,
    }
    return result


def _parse_timeline_params(path: str) -> dict:
    """Parse timeline query params: domain, days, limit."""
    result = {"domain": "", "days": 30, "limit": 50}
    if "?" not in path:
        return result
    params = path.split("?", 1)[1]
    for p in params.split("&"):
        if p.startswith("domain="):
            result["domain"] = p[7:]
        elif p.startswith("days="):
            try:
                result["days"] = int(p[5:])
            except ValueError:
                pass
        elif p.startswith("limit="):
            try:
                result["limit"] = int(p[6:])
            except ValueError:
                pass
    return result


def _build_timeline_response(store_getter, path: str) -> dict:
    """Fetch sessions from store and group via core logic."""
    from mcp_server.core.session_grouper import group_into_sessions

    store = store_getter()
    params = _parse_timeline_params(path)

    raw_sessions = store.get_sessions(
        domain=params["domain"],
        limit=params["limit"],
    )

    if not raw_sessions:
        return {"sessions": [], "total": 0}

    # Fetch memories for each session to build full summaries
    all_memories: list[dict] = []
    for sess in raw_sessions:
        sid = sess.get("session_id", "")
        if sid:
            mems = store.get_memories_by_session(sid, limit=50)
            all_memories.extend(mems)

    sessions = group_into_sessions(all_memories)
    sessions = sessions[: params["limit"]]

    return {"sessions": sessions, "total": len(sessions)}


def _build_local_graph_response(store_getter, path: str) -> dict:
    """Build local graph response for a memory."""
    from mcp_server.core.local_graph import build_local_graph
    from mcp_server.server.http_viz_api import parse_single_param

    mid = parse_single_param(path, "memory_id")
    if not mid:
        return {"error": "memory_id required"}
    depth = int(parse_single_param(path, "depth") or "1")
    store = store_getter()
    raw = store.get_local_graph(int(mid), depth=min(depth, 3))
    if raw["center"] is None:
        return {"error": "memory_not_found", "memory_id": int(mid)}
    return build_local_graph(
        raw["center"], raw["entities"], raw["neighbors"], raw["relationships"]
    )


def _build_backlinks_response(store_getter, path: str) -> dict:
    """Build backlinks response for an entity."""
    from mcp_server.core.backlink_resolver import resolve_backlinks
    from mcp_server.server.http_viz_api import parse_single_param

    eid = parse_single_param(path, "entity_id")
    if not eid:
        return {"error": "entity_id required"}
    limit = int(parse_single_param(path, "limit") or "50")
    store = store_getter()
    raw = store.get_backlinks(int(eid), limit=min(limit, 200))
    return resolve_backlinks(raw)


def _bind_and_start(handler_cls, preferred_port: int) -> str:
    """Bind to preferred port (fallback to OS-assigned) and start serving."""
    global _unified_server

    for port in [preferred_port, 0]:
        try:
            server = HTTPServer(("127.0.0.1", port), handler_cls)
            actual_port = server.server_address[1]
            url = f"http://127.0.0.1:{actual_port}"

            with _unified_lock:
                _unified_server = {
                    "server": server,
                    "url": url,
                    "port": actual_port,
                }

            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            _reset_unified_idle_timer()
            print(f"[cortex] Unified viz started at {url}", file=sys.stderr)
            return url
        except OSError:
            if port != 0:
                continue
            raise


def shutdown_unified_viz_server() -> None:
    """Shutdown the unified viz server if running."""
    global _unified_server, _unified_idle_timer
    if _unified_idle_timer:
        _unified_idle_timer.cancel()
        _unified_idle_timer = None
    with _unified_lock:
        if _unified_server:
            _unified_server["server"].shutdown()
            _unified_server = None
