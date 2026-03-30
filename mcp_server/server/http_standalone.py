"""Standalone HTTP server — runs as a detached process, survives MCP shutdown.

Starts the unified viz or methodology server, writes the bound URL to stdout,
then serves until idle timeout (10 min with no requests).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

IDLE_TIMEOUT = 600.0  # 10 minutes

_last_request_time = time.monotonic()
_lock = threading.Lock()


def _touch() -> None:
    """Record that a request was served."""
    global _last_request_time
    with _lock:
        _last_request_time = time.monotonic()


def _idle_watchdog(server: HTTPServer) -> None:
    """Background thread that shuts down the server after idle timeout."""
    while True:
        time.sleep(30)
        with _lock:
            elapsed = time.monotonic() - _last_request_time
        if elapsed >= IDLE_TIMEOUT:
            print(
                f"[cortex] Standalone server stopped (idle {IDLE_TIMEOUT}s)",
                file=sys.stderr,
            )
            server.shutdown()
            return


def _get_ui_root() -> Path:
    """Resolve UI root for standalone process."""
    # When run from plugin cache or dev checkout, ui/ is at project root
    # Project root = parent of mcp_server/
    pkg_dir = Path(__file__).parent.parent
    # Check inside package first (pip install)
    if (pkg_dir / "ui").is_dir():
        return pkg_dir / "ui"
    # Dev layout: project_root/ui/
    project_root = pkg_dir.parent
    if (project_root / "ui").is_dir():
        return project_root / "ui"
    raise RuntimeError("UI files not found")


def _get_store():
    """Create a fresh MemoryStore for this process."""
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import MemoryStore

    settings = get_memory_settings()
    return MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)


def _build_unified_handler(ui_root: Path, store) -> type:
    """Build unified viz HTTP handler."""
    from mcp_server.core.unified_graph_builder import build_unified_graph
    from mcp_server.infrastructure.profile_store import load_profiles
    from mcp_server.server.http_dashboard_data import (
        format_entity,
        format_memory,
        format_relationship,
    )

    html_path = ui_root / "unified-viz.html"
    html_bytes = html_path.read_bytes()
    js_dir = ui_root / "unified" / "js"
    css_dir = ui_root / "unified"

    def _parse_query(path: str) -> dict:
        result = {"domain_filter": None, "batch": 0, "batch_size": 0}
        if "?" not in path:
            return result
        for p in path.split("?", 1)[1].split("&"):
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

    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            _touch()
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.end_headers()

        def do_GET(self):
            _touch()
            if self.path == "/api/graph" or self.path.startswith("/api/graph?"):
                self._serve_graph()
            elif self.path.startswith("/api/file-diff?"):
                _serve_file_diff(self)
            elif self.path.startswith("/js/") and self.path.endswith(".js"):
                _serve_static(self, js_dir, self.path[4:], "application/javascript")
            elif self.path.startswith("/css/") and self.path.endswith(".css"):
                _serve_static(self, css_dir, self.path[5:], "text/css")
            else:
                self._serve_html()

        def _serve_html(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                self.wfile.write(html_path.read_bytes())
            except Exception:
                self.wfile.write(html_bytes)

        def _serve_graph(self):
            try:
                profiles = load_profiles()
                memories = store.get_hot_memories(min_heat=0.0, limit=200)
                entities = store.get_all_entities(min_heat=0.0)
                relationships = store.get_all_relationships()
                params = _parse_query(self.path)

                data = build_unified_graph(
                    profiles=profiles,
                    memories=[format_memory(m, 500) for m in memories],
                    entities=[format_entity(e) for e in entities],
                    relationships=[format_relationship(r) for r in relationships],
                    filter_domain=params["domain_filter"],
                    batch=params["batch"],
                    batch_size=params["batch_size"],
                )
                body = json.dumps(data, default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        def log_message(self, format, *args):
            pass

    return Handler


def _build_methodology_handler(ui_root: Path) -> type:
    """Build methodology viz HTTP handler."""
    from mcp_server.core.graph_builder import build_methodology_graph
    from mcp_server.infrastructure.profile_store import load_profiles

    html_path = ui_root / "methodology-viz.html"
    html_bytes = html_path.read_bytes()
    meth_dir = ui_root / "methodology"

    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            _touch()
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.end_headers()

        def do_GET(self):
            _touch()
            if self.path == "/graph":
                self._serve_graph()
            elif self.path.startswith("/methodology/js/") and self.path.endswith(".js"):
                _serve_static(
                    self, meth_dir / "js", self.path[16:], "application/javascript"
                )
            elif self.path.startswith("/methodology/css/") and self.path.endswith(
                ".css"
            ):
                _serve_static(self, meth_dir / "css", self.path[17:], "text/css")
            else:
                self._serve_html()

        def _serve_html(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                self.wfile.write(html_path.read_bytes())
            except Exception:
                self.wfile.write(html_bytes)

        def _serve_graph(self):
            try:
                profiles = load_profiles()
                data = build_methodology_graph(profiles)
                body = json.dumps(data, default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        def log_message(self, format, *args):
            pass

    return Handler


def _serve_static(handler, base_dir: Path, filename: str, content_type: str) -> None:
    """Serve a static file, sanitizing filename."""
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


def _serve_file_diff(handler) -> None:
    """Serve git diff for a file entity — delegates to http_file_diff."""
    from mcp_server.server.http_file_diff import serve_file_diff

    serve_file_diff(handler)


def _bind_server(handler_cls: type, preferred_port: int) -> HTTPServer:
    """Bind to preferred port, fall back to OS-assigned."""
    for port in [preferred_port, 0]:
        try:
            return HTTPServer(("127.0.0.1", port), handler_cls)
        except OSError:
            if port != 0:
                continue
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Cortex standalone HTTP server")
    parser.add_argument("--type", required=True, choices=["unified", "methodology"])
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    ui_root = _get_ui_root()

    if args.type == "unified":
        store = _get_store()
        handler_cls = _build_unified_handler(ui_root, store)
    else:
        handler_cls = _build_methodology_handler(ui_root)

    server = _bind_server(handler_cls, args.port)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}"

    # Signal the URL to the parent process, then close stdout
    # so the parent doesn't block waiting for us
    print(json.dumps({"url": url, "pid": __import__("os").getpid()}))
    sys.stdout.flush()
    sys.stdout.close()

    # Start idle watchdog
    watchdog = threading.Thread(target=_idle_watchdog, args=(server,), daemon=True)
    watchdog.start()

    print(f"[cortex] Standalone {args.type} server at {url}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
