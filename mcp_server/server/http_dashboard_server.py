"""Memory dashboard HTTP server.

Singleton server that serves the memory dashboard UI with live API data.
Auto-shuts down after 10 minutes of inactivity.
"""

from __future__ import annotations

import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from mcp_server.server.http_common import (
    read_html_file,
    send_json_response,
    send_error_response,
    send_html_response,
    send_cors_options,
    serve_static_file,
)
from mcp_server.server.http_dashboard_data import build_dashboard_data

_memory_server: dict | None = None
_memory_idle_timer: threading.Timer | None = None
_memory_lock = threading.Lock()


def _reset_memory_idle_timer() -> None:
    """Reset the memory dashboard idle timer."""
    global _memory_idle_timer, _memory_server
    if _memory_idle_timer:
        _memory_idle_timer.cancel()

    def _shutdown():
        global _memory_server
        with _memory_lock:
            if _memory_server:
                _memory_server["server"].shutdown()
                _memory_server = None
                print(
                    "[cortex] Memory dashboard stopped (idle timeout)",
                    file=sys.stderr,
                )

    _memory_idle_timer = threading.Timer(600.0, _shutdown)
    _memory_idle_timer.daemon = True
    _memory_idle_timer.start()


def start_memory_dashboard_server(store_getter) -> str:
    """Start the memory dashboard HTTP server. Returns URL."""
    global _memory_server

    with _memory_lock:
        if _memory_server:
            _reset_memory_idle_timer()
            return _memory_server["url"]

    ui_root = Path(__file__).parent.parent.parent / "ui"
    html_path = ui_root / "memory-dashboard.html"
    js_dir = ui_root / "dashboard" / "js"
    css_dir = ui_root / "dashboard"
    html_content = read_html_file(html_path, "dashboard UI file")
    cached_html = html_content.encode("utf-8")

    handler_cls = _build_dashboard_handler(
        store_getter, html_path, cached_html, js_dir, css_dir
    )
    return _bind_and_start(handler_cls, 3457)


def _build_dashboard_handler(
    store_getter, html_path, cached_html, js_dir, css_dir
) -> type:
    """Build the DashboardHandler class with bound context."""

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            send_cors_options(self)

        def do_GET(self):
            _reset_memory_idle_timer()
            if self.path == "/api/dashboard":
                self._serve_api()
            elif self.path.startswith("/js/") and self.path.endswith(".js"):
                serve_static_file(self, js_dir, self.path[4:], "application/javascript")
            elif self.path.startswith("/css/") and self.path.endswith(".css"):
                serve_static_file(self, css_dir, self.path[5:], "text/css")
            else:
                send_html_response(self, html_path, cached_html)

        def _serve_api(self):
            try:
                store = store_getter()
                data = build_dashboard_data(store)
                send_json_response(self, data)
            except Exception as e:
                send_error_response(self, e)

        def log_message(self, format, *args):
            pass

    return DashboardHandler


def _bind_and_start(handler_cls, preferred_port: int) -> str:
    """Bind to preferred port (fallback to OS-assigned) and start serving."""
    global _memory_server

    for port in [preferred_port, 0]:
        try:
            server = HTTPServer(("127.0.0.1", port), handler_cls)
            actual_port = server.server_address[1]
            url = f"http://127.0.0.1:{actual_port}"

            with _memory_lock:
                _memory_server = {
                    "server": server,
                    "url": url,
                    "port": actual_port,
                }

            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            _reset_memory_idle_timer()
            print(
                f"[cortex] Memory dashboard started at {url}",
                file=sys.stderr,
            )
            return url
        except OSError:
            if port != 0:
                continue
            raise


def shutdown_memory_dashboard_server() -> None:
    """Shutdown the memory dashboard server if running."""
    global _memory_server, _memory_idle_timer
    if _memory_idle_timer:
        _memory_idle_timer.cancel()
        _memory_idle_timer = None
    with _memory_lock:
        if _memory_server:
            _memory_server["server"].shutdown()
            _memory_server = None
