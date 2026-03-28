"""Unified visualization HTTP server.

Singleton server combining methodology graph and memory data
into a single interactive visualization. Auto-shuts down after
10 minutes of inactivity.
"""

from __future__ import annotations

import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from mcp_server.server.http_common import (
    get_ui_root,
    read_html_file,
    send_json_response,
    send_error_response,
    send_html_response,
    send_cors_options,
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
            if self.path == "/api/graph" or self.path.startswith("/api/graph?"):
                self._serve_graph_api()
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

    return build_unified_graph(
        profiles=profiles,
        memories=[format_memory(m, 500) for m in memories],
        entities=[format_entity(e) for e in entities],
        relationships=[format_relationship(r) for r in relationships],
        filter_domain=params["domain_filter"],
        batch=params["batch"],
        batch_size=params["batch_size"],
    )


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
