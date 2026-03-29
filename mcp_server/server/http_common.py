"""Shared HTTP server infrastructure: singleton manager and response helpers.

Provides ServerManager to eliminate duplicated singleton/timer/shutdown
patterns across UI, dashboard, and unified visualization servers.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any


class ServerManager:
    """Manages a singleton HTTP server with idle timeout.

    Each server type (UI, dashboard, unified viz) creates one instance.
    Handles: reuse check, idle timer, startup on preferred/fallback port,
    and graceful shutdown.
    """

    def __init__(self, label: str, idle_seconds: float = 600.0) -> None:
        self.label = label
        self.idle_seconds = idle_seconds
        self._server_state: dict | None = None
        self._idle_timer: threading.Timer | None = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._server_state is not None

    @property
    def url(self) -> str | None:
        if self._server_state:
            return self._server_state["url"]
        return None

    def get_or_start(
        self,
        handler_cls: type[BaseHTTPRequestHandler],
        preferred_port: int,
        *,
        on_reuse: Any = None,
    ) -> str:
        """Return existing URL or start a new server. Returns URL."""
        with self._lock:
            if self._server_state:
                self.reset_idle_timer()
                return self._server_state["url"]

        return self._start_server(handler_cls, preferred_port)

    def reset_idle_timer(self) -> None:
        """Cancel previous timer and start a new idle-timeout timer."""
        if self._idle_timer:
            self._idle_timer.cancel()

        def _shutdown() -> None:
            with self._lock:
                if self._server_state:
                    self._server_state["server"].shutdown()
                    self._server_state = None
                    print(
                        f"[cortex] {self.label} stopped (idle timeout)",
                        file=sys.stderr,
                    )

        self._idle_timer = threading.Timer(self.idle_seconds, _shutdown)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def shutdown(self) -> None:
        """Stop the server and cancel the idle timer."""
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None
        with self._lock:
            if self._server_state:
                self._server_state["server"].shutdown()
                self._server_state = None

    def _start_server(
        self,
        handler_cls: type[BaseHTTPRequestHandler],
        preferred_port: int,
    ) -> str:
        """Try preferred port, then fall back to OS-assigned port."""
        for port in [preferred_port, 0]:
            try:
                server = HTTPServer(("127.0.0.1", port), handler_cls)
                actual_port = server.server_address[1]
                url = f"http://127.0.0.1:{actual_port}"

                with self._lock:
                    self._server_state = {
                        "server": server,
                        "url": url,
                        "port": actual_port,
                    }

                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                self.reset_idle_timer()
                print(
                    f"[cortex] {self.label} started at {url}",
                    file=sys.stderr,
                )
                return url
            except OSError:
                if port != 0:
                    continue
                raise


def get_ui_root() -> Path:
    """Return the path to the bundled ui/ directory.

    Resolution order:
    1. CLAUDE_PLUGIN_ROOT/ui/ — plugin layout (code in uv cache, assets in plugin root)
    2. cwd/ui/ — fallback for plugin layout when cwd is set to plugin root
    3. mcp_server/ui/ — installed layout (ui/ inside the package)
    4. project_root/ui/ — development layout
    """
    # Plugin layout: CLAUDE_PLUGIN_ROOT env var set by plugin.json
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        plugin_ui = Path(plugin_root) / "ui"
        if plugin_ui.is_dir():
            return plugin_ui
    # Plugin layout fallback: cwd (MCP config sets cwd to plugin root)
    cwd_ui = Path.cwd() / "ui"
    if cwd_ui.is_dir():
        return cwd_ui
    # Installed layout: mcp_server/ui/
    pkg_ui = Path(__file__).parent.parent / "ui"
    if pkg_ui.is_dir():
        return pkg_ui
    # Development layout: project_root/ui/
    dev_ui = Path(__file__).parent.parent.parent / "ui"
    if dev_ui.is_dir():
        return dev_ui
    raise RuntimeError(
        "UI files not found. Checked: "
        f"CLAUDE_PLUGIN_ROOT={plugin_root}, "
        f"cwd={Path.cwd()}, "
        f"package={Path(__file__).parent.parent}"
    )


def read_html_file(path: Path, error_label: str) -> str:
    """Read an HTML file, raising RuntimeError with a clear message on failure."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"Could not read {error_label}: {e}")


def send_json_response(
    handler: BaseHTTPRequestHandler, data: Any, *, status: int = 200
) -> None:
    """Send a JSON response with CORS and no-cache headers."""
    body = json.dumps(data, default=str).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)


def send_error_response(handler: BaseHTTPRequestHandler, error: Exception) -> None:
    """Send a 500 JSON error response."""
    handler.send_response(500)
    handler.send_header("Content-Type", "application/json")
    handler.end_headers()
    handler.wfile.write(json.dumps({"error": str(error)}).encode())


def send_html_response(
    handler: BaseHTTPRequestHandler, html_path: Path, fallback: bytes
) -> None:
    """Send an HTML response, hot-reloading from disk for development."""
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    try:
        body = html_path.read_bytes()
    except Exception:
        body = fallback
    handler.wfile.write(body)


def serve_static_file(
    handler: BaseHTTPRequestHandler,
    base_dir: Path,
    filename: str,
    content_type: str,
) -> None:
    """Serve a static file from base_dir, sanitizing the filename."""
    safe_name = Path(filename).name
    file_path = base_dir / safe_name
    if not file_path.exists():
        handler.send_response(404)
        handler.end_headers()
        return
    body = file_path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type + "; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)


def send_cors_options(handler: BaseHTTPRequestHandler) -> None:
    """Send a 204 CORS preflight response."""
    handler.send_response(204)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    handler.end_headers()
