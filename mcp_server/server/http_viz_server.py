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
    """Parse query string into a flat key-value dict."""
    result: dict = {"domain_filter": None, "batch": 0, "batch_size": 0}
    if "?" not in path:
        return result

    params = path.split("?", 1)[1]
    for p in params.split("&"):
        if "=" not in p:
            continue
        key, _, val = p.partition("=")
        if key == "domain":
            result["domain_filter"] = val
        elif key == "batch":
            try:
                result["batch"] = int(val)
            except ValueError:
                pass
        elif key == "batch_size":
            try:
                result["batch_size"] = int(val)
            except ValueError:
                pass
        elif key == "memory_id":
            try:
                result["memory_id"] = int(val)
            except ValueError:
                pass
        elif key == "depth":
            try:
                result["depth"] = int(val)
            except ValueError:
                pass
        elif key == "max_neighbors":
            try:
                result["max_neighbors"] = int(val)
            except ValueError:
                pass
        elif key == "entity_id":
            try:
                result["entity_id"] = int(val)
            except ValueError:
                pass
        elif key == "limit":
            try:
                result["limit"] = int(val)
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
            elif base == "/api/local-graph":
                self._serve_local_graph_api()
            elif base == "/api/backlinks":
                self._serve_backlinks_api()
            elif self.path.startswith("/js/") and self.path.endswith(".js"):
                serve_static_file(self, js_dir, self.path[4:], "application/javascript")
            elif self.path.startswith("/css/") and self.path.endswith(".css"):
                serve_static_file(self, css_dir, self.path[5:], "text/css")
            else:
                send_html_response(self, html_path, cached_html)

        def _serve_graph_api(self):
            try:
                data = _build_graph_response(profiles_getter, store_getter, self.path)
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

        def log_message(self, format, *args):
            pass

    return UnifiedHandler


def _build_graph_response(profiles_getter, store_getter, path: str) -> dict:
    """Fetch data from stores and build the unified graph response."""
    from mcp_server.core.unified_graph_builder import build_unified_graph

    profiles = profiles_getter()
    store = store_getter()
    memories = store.get_hot_memories(min_heat=0.0, limit=200)
    entities = store.get_all_entities(min_heat=0.0)
    relationships = store.get_all_relationships()
    params = _parse_query_params(path)

    result = build_unified_graph(
        profiles=profiles,
        memories=[format_memory(m, 500) for m in memories],
        entities=[format_entity(e) for e in entities],
        relationships=[format_relationship(r) for r in relationships],
        filter_domain=params["domain_filter"],
        batch=params["batch"],
        batch_size=params["batch_size"],
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


def _build_local_graph_response(store_getter, path: str) -> dict:
    """Build local graph response for a memory's neighborhood."""
    from mcp_server.core.local_graph import build_local_graph

    params = _parse_query_params(path)
    memory_id = params.get("memory_id")
    if memory_id is None:
        return {"error": "memory_id query parameter is required"}

    depth = min(params.get("depth", 1), 3)
    max_neighbors = min(params.get("max_neighbors", 30), 100)
    store = store_getter()
    raw = store.get_local_graph(memory_id, depth=depth, max_neighbors=max_neighbors)

    if raw["center"] is None:
        return {"error": f"Memory {memory_id} not found"}

    return build_local_graph(
        raw["center"], raw["entities"], raw["neighbors"], raw["relationships"]
    )


def _build_backlinks_response(store_getter, path: str) -> dict:
    """Build backlinks response for an entity."""
    from mcp_server.core.backlink_resolver import resolve_backlinks

    params = _parse_query_params(path)
    entity_id = params.get("entity_id")
    if entity_id is None:
        return {"error": "entity_id query parameter is required"}

    limit = min(params.get("limit", 50), 200)
    store = store_getter()
    raw = store.get_backlinks(entity_id, limit=limit)
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
