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
from socketserver import ThreadingMixIn

IDLE_TIMEOUT = 600.0  # 10 minutes
_CONVERSATIONS_CACHE_TTL = 60.0  # seconds

_last_request_time = time.monotonic()
_lock = threading.Lock()

# Cached state shared between graph and discussion endpoints
_cached_domain_hub_ids: dict[str, str] = {}
_cached_conversations: list[dict] | None = None
_conversations_cache_ts: float = 0.0

# Graph cache — avoids rebuilding 8000+ nodes on every request
_graph_cache: dict | None = None
_graph_cache_ts: float = 0.0
_graph_build_lock = threading.Lock()
_GRAPH_CACHE_TTL = 120.0  # seconds

# Set by _build_unified_handler for pre-warm access
_graph_builder_fn = None


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server — prevents graph builds from blocking static files."""

    daemon_threads = True


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


def _get_cached_conversations() -> list[dict]:
    """Return cached conversations, refreshing if TTL expired."""
    global _cached_conversations, _conversations_cache_ts
    now = time.time()
    if (
        _cached_conversations is None
        or (now - _conversations_cache_ts) > _CONVERSATIONS_CACHE_TTL
    ):
        from mcp_server.infrastructure.scanner import discover_conversations

        _cached_conversations = discover_conversations()
        _conversations_cache_ts = now
    return _cached_conversations


def _extract_domain_hub_ids(nodes: list[dict]) -> dict[str, str]:
    """Extract domain_key -> node_id mapping from graph nodes."""
    hub_ids: dict[str, str] = {}
    for node in nodes:
        if node.get("type") == "domain":
            domain_key = node.get("domain", "")
            if domain_key:
                hub_ids[domain_key] = node["id"]
    return hub_ids


def _parse_discussion_params(path: str) -> dict:
    """Parse query params for the discussions endpoint."""
    result: dict = {"project": None, "batch": 0, "batch_size": 500}
    if "?" not in path:
        return result
    params = path.split("?", 1)[1]
    for p in params.split("&"):
        if p.startswith("project="):
            result["project"] = p[8:]
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

    def _do_background_build(domain_filter: str | None) -> None:
        """Build the full graph in background and cache it."""
        global _graph_cache, _graph_cache_ts, _cached_domain_hub_ids

        acquired = _graph_build_lock.acquire(blocking=False)
        if not acquired:
            return  # Another build already in progress

        try:
            profiles = load_profiles()
            memories = store.get_hot_memories(min_heat=0.0, limit=0)
            entities = store.get_all_entities(min_heat=0.0)
            relationships = store.get_all_relationships()

            data = build_unified_graph(
                profiles=profiles,
                memories=[format_memory(m, 500) for m in memories],
                entities=[format_entity(e) for e in entities],
                relationships=[format_relationship(r) for r in relationships],
                filter_domain=domain_filter,
            )
            _cached_domain_hub_ids = _extract_domain_hub_ids(data.get("nodes", []))
            _graph_cache = {"data": data, "domain_filter": domain_filter}
            _graph_cache_ts = time.monotonic()
            print(
                f"[cortex] Graph cache ready: {len(data.get('nodes', []))} nodes",
                file=sys.stderr,
            )
        except Exception as exc:
            print(f"[cortex] Graph build error: {exc}", file=sys.stderr)
        finally:
            _graph_build_lock.release()

    def _get_graph_response(path: str) -> dict:
        """Return cached full graph, or signal warming while building."""
        global _graph_cache, _graph_cache_ts

        params = _parse_query(path)
        domain_filter = params["domain_filter"]
        now = time.monotonic()

        cache_valid = (
            _graph_cache
            and _graph_cache.get("domain_filter") == domain_filter
            and (now - _graph_cache_ts) < _GRAPH_CACHE_TTL
        )

        if cache_valid:
            return _graph_cache["data"]

        # No cache — return warming signal, kick off background build
        threading.Thread(
            target=_do_background_build,
            args=(domain_filter,),
            daemon=True,
        ).start()
        return {
            "nodes": [],
            "edges": [],
            "clusters": [],
            "meta": {"warming": True, "node_count": 0},
        }

    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            _touch()
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.end_headers()

        def do_GET(self):
            _touch()
            path_no_qs = self.path.split("?")[0]
            if self.path == "/api/graph" or self.path.startswith("/api/graph?"):
                self._serve_graph()
            elif self.path == "/api/discussions" or self.path.startswith(
                "/api/discussions?"
            ):
                self._serve_discussions()
            elif path_no_qs.startswith("/api/discussion/"):
                self._serve_discussion_detail(path_no_qs)
            elif path_no_qs == "/api/wiki/list":
                self._serve_wiki_list()
            elif path_no_qs == "/api/wiki/page":
                self._serve_wiki_page()
            elif self.path == "/api/sankey" or self.path.startswith("/api/sankey?"):
                self._serve_sankey()
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

        def _serve_wiki_list(self):
            try:
                from mcp_server.handlers.wiki_api import list_wiki_pages
                from mcp_server.infrastructure.config import METHODOLOGY_DIR

                data = list_wiki_pages(METHODOLOGY_DIR / "wiki")
                body = json.dumps({"pages": data}, default=str).encode()
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

        def _serve_wiki_page(self):
            try:
                import urllib.parse
                from mcp_server.handlers.wiki_api import read_wiki_page
                from mcp_server.infrastructure.config import METHODOLOGY_DIR

                rel_path = ""
                if "?" in self.path:
                    for p in self.path.split("?", 1)[1].split("&"):
                        if p.startswith("path="):
                            rel_path = urllib.parse.unquote(p[5:])
                data = read_wiki_page(METHODOLOGY_DIR / "wiki", rel_path)
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

        def _serve_graph(self):
            try:
                data = _get_graph_response(self.path)
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

        def _serve_sankey(self):
            try:
                rows = store._conn.execute(
                    "SELECT from_stage, to_stage, COUNT(*) as count "
                    "FROM stage_transitions "
                    "GROUP BY from_stage, to_stage "
                    "ORDER BY from_stage, to_stage"
                ).fetchall()
                transitions = [dict(r) for r in rows]

                # Transition timing stats
                timing_rows = store._conn.execute(
                    "SELECT from_stage, to_stage, "
                    "AVG(hours_in_prev_stage) as avg_hours, "
                    "MIN(hours_in_prev_stage) as min_hours, "
                    "MAX(hours_in_prev_stage) as max_hours "
                    "FROM stage_transitions GROUP BY from_stage, to_stage"
                ).fetchall()
                timing = {}
                for r in timing_rows:
                    key = r["from_stage"] + "->" + r["to_stage"]
                    timing[key] = {
                        "avg_hours": round(r["avg_hours"], 1),
                        "min_hours": round(r["min_hours"], 1),
                        "max_hours": round(r["max_hours"], 1),
                    }

                # Per-stage metrics
                stages = [
                    "labile",
                    "early_ltp",
                    "late_ltp",
                    "consolidated",
                    "reconsolidating",
                ]
                stage_metrics = {}
                for s in stages:
                    r = store._conn.execute(
                        "SELECT COUNT(*) as count, "
                        "AVG(heat) as avg_heat, AVG(importance) as avg_importance, "
                        "AVG(replay_count) as avg_replay, AVG(access_count) as avg_access, "
                        "AVG(encoding_strength) as avg_encoding, "
                        "AVG(interference_score) as avg_interference, "
                        "AVG(schema_match_score) as avg_schema, "
                        "AVG(hippocampal_dependency) as avg_hippo, "
                        "AVG(plasticity) as avg_plasticity, "
                        "AVG(stability) as avg_stability, "
                        "AVG(hours_in_stage) as avg_hours "
                        "FROM memories WHERE consolidation_stage = %s "
                        "AND NOT is_benchmark AND NOT is_stale",
                        (s,),
                    ).fetchone()
                    stage_metrics[s] = {
                        k: round(v, 3) if isinstance(v, float) else (v or 0)
                        for k, v in dict(r).items()
                    }

                # Total memories
                total = store._conn.execute(
                    "SELECT COUNT(*) as c FROM memories "
                    "WHERE NOT is_benchmark AND NOT is_stale"
                ).fetchone()

                body = json.dumps(
                    {
                        "transitions": transitions,
                        "timing": timing,
                        "stage_metrics": stage_metrics,
                        "total_memories": total["c"],
                    },
                    default=str,
                ).encode()
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

        def _serve_discussions(self):
            try:
                data = _build_discussions_response(self.path)
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

        def _serve_discussion_detail(self, path_no_qs: str):
            try:
                session_id = path_no_qs.rsplit("/", 1)[-1]
                data = _build_discussion_detail(session_id)
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

    global _graph_builder_fn
    _graph_builder_fn = _do_background_build

    return Handler


def _build_discussions_response(path: str) -> dict:
    """Build the paginated discussions response."""
    from mcp_server.core.graph_builder_discussions import build_discussion_nodes

    params = _parse_discussion_params(path)
    conversations = _get_cached_conversations()

    if params["project"]:
        conversations = [
            c for c in conversations if c.get("project") == params["project"]
        ]

    conversations = sorted(
        conversations,
        key=lambda c: c.get("startedAt") or "",
        reverse=True,
    )

    total = len(conversations)
    batch_size = max(1, params["batch_size"])
    batch = params["batch"]
    total_batches = max(1, (total + batch_size - 1) // batch_size)
    start = batch * batch_size
    end = start + batch_size
    page = conversations[start:end]

    nodes, edges = build_discussion_nodes(page, _cached_domain_hub_ids)

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "total": total,
            "batch": batch,
            "batch_size": batch_size,
            "total_batches": total_batches,
        },
    }


def _build_discussion_detail(session_id: str) -> dict:
    """Build the detail response for a single discussion."""
    from mcp_server.infrastructure.conversation_reader import (
        format_conversation_messages,
        read_full_conversation,
    )

    conversations = _get_cached_conversations()
    conv = next(
        (c for c in conversations if c.get("sessionId") == session_id),
        None,
    )
    if conv is None:
        return {"error": "Discussion not found", "sessionId": session_id}

    from mcp_server.infrastructure.config import CLAUDE_DIR

    # Whitelist approach: find the JSONL file by scanning actual files on disk
    # Never construct a path from user-provided session_id or project
    target_filename = session_id + ".jsonl"
    projects_dir = CLAUDE_DIR / "projects"
    found_path = None

    if projects_dir.is_dir():
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            candidate = project_dir / target_filename
            if candidate.is_file():
                found_path = candidate
                break

    if found_path is None:
        return {"error": "Session file not found", "sessionId": session_id}

    # found_path comes from directory enumeration, not user input
    raw = read_full_conversation(str(found_path))
    messages = format_conversation_messages(raw)

    return {
        "sessionId": session_id,
        "project": conv.get("project"),
        "messages": messages,
        "startedAt": conv.get("startedAt"),
        "endedAt": conv.get("endedAt"),
        "duration": conv.get("duration"),
        "turnCount": conv.get("turnCount"),
    }


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
    import re

    # Security: strip all path components, keep only the final filename
    safe_name = Path(filename).name
    # Reject empty names, hidden files, null bytes, and non-alphanumeric filenames
    if (
        not safe_name
        or safe_name.startswith(".")
        or "\x00" in safe_name
        or not re.match(r"^[\w][\w.\-]*$", safe_name)
    ):
        handler.send_response(403)
        handler.end_headers()
        return
    # Whitelist approach: enumerate actual files in base_dir and match
    resolved_base = base_dir.resolve()
    actual_files = {f.name: f for f in resolved_base.iterdir() if f.is_file()}
    if safe_name not in actual_files:
        handler.send_response(404)
        handler.end_headers()
        return
    # Use the Path object from the directory listing — never from user input
    body = actual_files[safe_name].read_bytes()
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
            return _ThreadedHTTPServer(("127.0.0.1", port), handler_cls)
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

    # Pre-warm graph cache for unified viz
    if args.type == "unified" and _graph_builder_fn:
        warm = threading.Thread(
            target=lambda: _graph_builder_fn(None),
            daemon=True,
        )
        warm.start()

    print(f"[cortex] Standalone {args.type} server at {url}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
