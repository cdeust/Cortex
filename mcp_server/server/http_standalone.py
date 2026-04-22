"""Standalone HTTP server — runs as a detached process, survives MCP shutdown.

Starts the unified viz or methodology server, writes the bound URL to
stdout, then serves until the idle timeout fires (10 min with no
requests). Composition-root only: the route table lives here, but every
endpoint body has been extracted to a sibling module so this file stays
inside the 300-line ceiling.

Sibling modules:

* ``http_standalone_state`` — shared caches + touch() watchdog state.
* ``http_standalone_graph`` — workflow-graph cache + discussions.
* ``http_standalone_wiki``  — /api/wiki/* endpoints.
* ``http_standalone_endpoints`` — /api/sankey, /api/graph, static, diff,
  methodology handler factory.
* ``http_standalone_response`` — JSON response boilerplate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

from mcp_server.server.http_common import (
    _apply_cors_headers,
    enforce_same_origin_write,
    validate_host_header,
)
from mcp_server.server.http_standalone_endpoints import (
    build_methodology_handler,
    serve_discussion_detail,
    serve_discussions,
    serve_file_diff,
    serve_graph,
    serve_sankey,
    serve_static,
)
from mcp_server.server.http_standalone_graph import build_and_cache_graph
from mcp_server.server.http_standalone_state import (
    IDLE_TIMEOUT,
    seconds_since_last_request,
    touch,
)
from mcp_server.server.http_standalone_wiki import (
    serve_wiki_db,
    serve_wiki_export,
    serve_wiki_list,
    serve_wiki_page,
    serve_wiki_save,
)


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server — prevents graph builds from blocking static files."""

    daemon_threads = True


def _idle_watchdog(server: HTTPServer) -> None:
    """Shut the server down after ``IDLE_TIMEOUT`` seconds with no requests."""
    while True:
        time.sleep(30)
        if seconds_since_last_request() >= IDLE_TIMEOUT:
            print(
                f"[cortex] Standalone server stopped (idle {IDLE_TIMEOUT}s)",
                file=sys.stderr,
            )
            server.shutdown()
            return


def _get_ui_root() -> Path:
    """Resolve the UI root whether run from the pip install, plugin cache,
    or dev checkout.

    The canonical marker is ``unified-viz.html`` — we require it to exist,
    otherwise the resolver falls through. An empty ``mcp_server/ui/``
    directory (left behind by an earlier sync) previously won this lookup
    and crashed every request when the HTML was missing.
    """
    pkg_dir = Path(__file__).parent.parent
    candidates = [
        pkg_dir / "ui",  # pip-installed layout
        pkg_dir.parent / "ui",  # plugin cache + dev checkout
        Path.cwd() / "ui",  # last-resort when cwd is plugin root
    ]
    for ui in candidates:
        if (ui / "unified-viz.html").is_file():
            return ui
    raise RuntimeError(f"UI files not found — looked in {[str(c) for c in candidates]}")


def _get_store():
    """Create a fresh MemoryStore for this standalone process."""
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import MemoryStore

    settings = get_memory_settings()
    return MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)


_WIKI_DB_OPS = {
    "/api/wiki/page_meta": "page_meta",
    "/api/wiki/concepts": "concepts",
    "/api/wiki/drafts": "drafts",
    "/api/wiki/memos": "memos",
    "/api/wiki/views": "views",
    "/api/wiki/view": "view",
    "/api/wiki/bibliography": "bibliography",
    "/api/wiki/bibliography/read": "bibliography_read",
}


def _route_unified_get(
    handler, store, js_dir: Path, css_dir: Path, html_path: Path
) -> None:
    """Resolve a GET request for the unified server."""
    path = handler.path
    path_no_qs = path.split("?")[0]
    if path == "/api/graph" or path.startswith("/api/graph?"):
        serve_graph(handler, store)
    elif path == "/api/discussions" or path.startswith("/api/discussions?"):
        serve_discussions(handler)
    elif path_no_qs.startswith("/api/discussion/"):
        serve_discussion_detail(handler, path_no_qs)
    elif path_no_qs == "/api/wiki/list":
        serve_wiki_list(handler)
    elif path_no_qs == "/api/wiki/page":
        serve_wiki_page(handler)
    elif path_no_qs in _WIKI_DB_OPS:
        serve_wiki_db(handler, _WIKI_DB_OPS[path_no_qs])
    elif path_no_qs == "/api/wiki/export":
        serve_wiki_export(handler)
    elif path == "/api/sankey" or path.startswith("/api/sankey?"):
        serve_sankey(handler, store)
    elif path.startswith("/api/file-diff?"):
        serve_file_diff(handler)
    elif path.startswith("/js/") and path_no_qs.endswith(".js"):
        serve_static(handler, js_dir, path_no_qs[4:], "application/javascript")
    elif path.startswith("/css/") and path_no_qs.endswith(".css"):
        serve_static(handler, css_dir, path_no_qs[5:], "text/css")
    else:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()
        handler.wfile.write(html_path.read_bytes())


def _build_unified_handler(ui_root: Path, store) -> type:
    """HTTPHandler factory for the unified viz server."""
    html_path = ui_root / "unified-viz.html"
    js_dir = ui_root / "unified" / "js"
    css_dir = ui_root / "unified"

    class Handler(BaseHTTPRequestHandler):
        def _guard_host(self) -> bool:
            if validate_host_header(self):
                return True
            self.send_response(421)
            self.end_headers()
            return False

        def do_OPTIONS(self):
            if not self._guard_host():
                return
            touch()
            self.send_response(204)
            _apply_cors_headers(self)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_POST(self):
            if not self._guard_host():
                return
            if not enforce_same_origin_write(self):
                self.send_response(403)
                self.end_headers()
                return
            touch()
            if self.path.split("?")[0] == "/api/wiki/save":
                serve_wiki_save(self)
            else:
                self.send_response(404)
                self.end_headers()

        def do_GET(self):
            if not self._guard_host():
                return
            touch()
            _route_unified_get(self, store, js_dir, css_dir, html_path)

        def log_message(self, format, *args):
            pass

    return Handler


def _bind_server(handler_cls: type, preferred_port: int) -> HTTPServer:
    """Bind to preferred port, fall back to OS-assigned."""
    for port in [preferred_port, 0]:
        try:
            return _ThreadedHTTPServer(("127.0.0.1", port), handler_cls)
        except OSError:
            if port != 0:
                continue
            raise


def _announce(url: str) -> None:
    """Signal the bound URL to the parent process, then close stdout."""
    print(json.dumps({"url": url, "pid": os.getpid()}))
    sys.stdout.flush()
    sys.stdout.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Cortex standalone HTTP server")
    parser.add_argument("--type", required=True, choices=["unified", "methodology"])
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    ui_root = _get_ui_root()
    store = None
    if args.type == "unified":
        store = _get_store()
        handler_cls = _build_unified_handler(ui_root, store)
    else:
        handler_cls = build_methodology_handler(ui_root)

    server = _bind_server(handler_cls, args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    _announce(url)

    threading.Thread(
        target=_idle_watchdog,
        args=(server,),
        daemon=True,
    ).start()

    if args.type == "unified" and store is not None:
        threading.Thread(
            target=build_and_cache_graph,
            args=(store, None),
            daemon=True,
        ).start()

    print(f"[cortex] Standalone {args.type} server at {url}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
