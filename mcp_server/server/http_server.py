"""UI visualization HTTP server with idle timeout.

Singleton HTTP server that serves the 3D methodology constellation map.
Auto-shuts down after 10 minutes of inactivity.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from mcp_server.server.http_common import get_ui_root

# ── UI Server (methodology constellation map) ─────────────────────────

_active_server: dict | None = None
_idle_timer: threading.Timer | None = None
_lock = threading.Lock()


def _reset_idle_timer() -> None:
    global _idle_timer, _active_server
    if _idle_timer:
        _idle_timer.cancel()

    def _shutdown():
        global _active_server
        with _lock:
            if _active_server:
                _active_server["server"].shutdown()
                _active_server = None
                print(
                    "[methodology-agent] UI server stopped (idle timeout)",
                    file=sys.stderr,
                )

    _idle_timer = threading.Timer(600.0, _shutdown)
    _idle_timer.daemon = True
    _idle_timer.start()


def start_ui_server(graph_data: dict[str, Any], *, html_file: str | None = None) -> str:
    """Start or reuse the UI HTTP server. Returns URL."""
    global _active_server

    with _lock:
        if _active_server:
            _active_server["graph_data"] = graph_data
            _active_server["graph_json"] = json.dumps(graph_data)
            _reset_idle_timer()
            return _active_server["url"]

    html_path = _resolve_html_path(html_file)
    html_content = _read_html(html_path)

    server_state = {
        "graph_data": graph_data,
        "graph_json": json.dumps(graph_data),
        "html": html_content,
    }

    handler_cls = _build_handler_class(server_state)
    return _bind_and_start_ui(handler_cls, server_state)


def _resolve_html_path(html_file: str | None) -> Path:
    """Resolve the HTML file path for the UI server."""
    if html_file:
        return Path(html_file)
    return get_ui_root() / "methodology-viz.html"


def _read_html(html_path: Path) -> str:
    """Read an HTML file, raising RuntimeError on failure."""
    try:
        return html_path.read_text(encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"Could not read UI file: {e}")


def _build_handler_class(server_state: dict) -> type:
    """Build the BaseHTTPRequestHandler subclass for the UI server."""

    ui_root = get_ui_root()
    meth_dir = ui_root / "methodology"

    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.end_headers()

        def do_GET(self):
            _reset_idle_timer()
            self.send_header_cors()
            if self.path == "/graph":
                _serve_graph_json(self, server_state)
            elif self.path.startswith("/methodology/js/") and self.path.endswith(".js"):
                _serve_static(
                    self, meth_dir / "js", self.path[16:], "application/javascript"
                )
            elif self.path.startswith("/methodology/css/") and self.path.endswith(
                ".css"
            ):
                _serve_static(self, meth_dir / "css", self.path[17:], "text/css")
            else:
                _serve_html_page(self, server_state)

        def send_header_cors(self):
            pass

        def log_message(self, format, *args):
            pass

    return Handler


def _serve_graph_json(handler, server_state: dict) -> None:
    """Serve graph data as JSON."""
    body = server_state["graph_json"].encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)


def _serve_static(handler, base_dir: Path, filename: str, content_type: str) -> None:
    """Serve a static file from the given directory."""
    try:
        # Sanitize: strip path components, use only the basename
        safe_name = Path(filename).name
        file_path = (base_dir / safe_name).resolve()
        # Validate: resolved path must stay within base_dir
        if not str(file_path).startswith(str(base_dir.resolve())):
            handler.send_response(403)
            handler.end_headers()
            return
        body = file_path.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()
        handler.wfile.write(body)
    except FileNotFoundError:
        handler.send_response(404)
        handler.end_headers()


def _serve_html_page(handler, server_state: dict) -> None:
    """Serve the HTML visualization page."""
    body = server_state["html"].encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)


def _bind_and_start_ui(handler_cls, server_state: dict) -> str:
    """Bind the UI server to preferred port and start serving."""
    global _active_server

    for port in [3456, 0]:
        try:
            server = HTTPServer(("127.0.0.1", port), handler_cls)
            actual_port = server.server_address[1]
            url = f"http://127.0.0.1:{actual_port}"

            with _lock:
                _active_server = {
                    "server": server,
                    "url": url,
                    "port": actual_port,
                    **server_state,
                }

            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            _reset_idle_timer()
            print(
                f"[methodology-agent] UI server started at {url}",
                file=sys.stderr,
            )
            return url
        except OSError:
            if port != 0:
                continue
            raise


def shutdown_server() -> None:
    """Shutdown the active server if running."""
    global _active_server, _idle_timer
    if _idle_timer:
        _idle_timer.cancel()
        _idle_timer = None
    with _lock:
        if _active_server:
            _active_server["server"].shutdown()
            _active_server = None
