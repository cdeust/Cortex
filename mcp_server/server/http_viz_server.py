"""Unified visualization HTTP server.

Singleton server combining methodology graph and memory data
into a single interactive visualization. Auto-shuts down after
10 minutes of inactivity.
"""

from __future__ import annotations

import re
import sys
import threading
import time
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

# Cached state shared between graph and discussion endpoints
_cached_domain_hub_ids: dict[str, str] = {}
_cached_conversations: list[dict] | None = None
_conversations_cache_ts: float = 0.0
_CONVERSATIONS_CACHE_TTL = 60.0  # seconds


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
            path_no_qs = self.path.split("?")[0]
            if self.path == "/api/graph" or self.path.startswith("/api/graph?"):
                self._serve_graph_api()
            elif self.path == "/api/discussions" or self.path.startswith(
                "/api/discussions?"
            ):
                self._serve_discussions_api()
            elif re.match(r"^/api/discussion/[^/]+$", path_no_qs):
                self._serve_discussion_detail(path_no_qs)
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

        def _serve_discussions_api(self):
            try:
                data = _build_discussions_response(self.path)
                send_json_response(self, data)
            except Exception as e:
                send_error_response(self, e)

        def _serve_discussion_detail(self, path_no_qs: str):
            try:
                session_id = path_no_qs.rsplit("/", 1)[-1]
                data = _build_discussion_detail(session_id)
                send_json_response(self, data)
            except Exception as e:
                send_error_response(self, e)

        def log_message(self, format, *args):
            pass

    return UnifiedHandler


def _build_graph_response(profiles_getter, store_getter, path: str) -> dict:
    """Fetch data from stores and build the unified graph response."""
    global _cached_domain_hub_ids
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

    # Export domain_hub_ids for the discussions endpoint
    _cached_domain_hub_ids = _extract_domain_hub_ids(result.get("nodes", []))

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


def _extract_domain_hub_ids(nodes: list[dict]) -> dict[str, str]:
    """Extract domain_key -> node_id mapping from graph nodes."""
    hub_ids: dict[str, str] = {}
    for node in nodes:
        if node.get("type") == "domain":
            domain_key = node.get("domain", "")
            if domain_key:
                hub_ids[domain_key] = node["id"]
    return hub_ids


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


def _parse_discussion_params(path: str) -> dict:
    """Parse query params for the discussions endpoint."""
    result = {"project": None, "batch": 0, "batch_size": 500}
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


def _build_discussions_response(path: str) -> dict:
    """Build the paginated discussions response."""
    from mcp_server.core.graph_builder_discussions import build_discussion_nodes

    params = _parse_discussion_params(path)
    conversations = _get_cached_conversations()

    # Filter by project if specified
    if params["project"]:
        conversations = [
            c for c in conversations if c.get("project") == params["project"]
        ]

    # Sort by startedAt descending
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

    # The scanner stores filePath as part of the record if available;
    # otherwise reconstruct from project + sessionId
    file_path = conv.get("filePath")
    if not file_path:
        from mcp_server.infrastructure.config import CLAUDE_DIR

        project = conv.get("project", "")
        file_path = str(CLAUDE_DIR / "projects" / project / f"{session_id}.jsonl")

    raw = read_full_conversation(file_path)
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
