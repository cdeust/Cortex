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
from socketserver import ThreadingMixIn

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

# Graph cache — avoids rebuilding 8000+ nodes on every request
_graph_cache: dict | None = None
_graph_cache_ts: float = 0.0
_graph_build_lock = threading.Lock()
_GRAPH_CACHE_TTL = 120.0  # seconds


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server — prevents graph builds from blocking static files."""

    daemon_threads = True


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
    return _bind_and_start(handler_cls, 3458, profiles_getter, store_getter)


def _build_unified_handler(
    profiles_getter, store_getter, html_path, cached_html, js_dir, css_dir
) -> type:
    """Build the UnifiedHandler class with bound context."""

    class UnifiedHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            send_cors_options(self)

        def do_POST(self):
            path_no_qs = self.path.split("?")[0]
            if path_no_qs == "/api/wiki/save":
                self._serve_wiki_save()
            else:
                self.send_response(404)
                self.end_headers()

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
            elif path_no_qs == "/api/wiki/list":
                self._serve_wiki_list()
            elif path_no_qs == "/api/wiki/page":
                self._serve_wiki_page()
            elif path_no_qs == "/api/wiki/page_meta":
                self._serve_wiki_page_meta()
            elif path_no_qs == "/api/wiki/concepts":
                self._serve_wiki_concepts()
            elif path_no_qs == "/api/wiki/drafts":
                self._serve_wiki_drafts()
            elif path_no_qs == "/api/wiki/memos":
                self._serve_wiki_memos()
            elif path_no_qs == "/api/wiki/views":
                self._serve_wiki_views()
            elif path_no_qs == "/api/wiki/view":
                self._serve_wiki_view()
            elif path_no_qs == "/api/wiki/bibliography":
                self._serve_wiki_bibliography()
            elif path_no_qs == "/api/wiki/bibliography/read":
                self._serve_wiki_bibliography_read()
            elif path_no_qs == "/api/wiki/export":
                self._serve_wiki_export()
            elif self.path.startswith("/js/") and self.path.endswith(".js"):
                serve_static_file(self, js_dir, self.path[4:], "application/javascript")
            elif self.path.startswith("/css/") and self.path.endswith(".css"):
                serve_static_file(self, css_dir, self.path[5:], "text/css")
            else:
                send_html_response(self, html_path, cached_html)

        def _serve_graph_api(self):
            try:
                data = _get_graph_response(profiles_getter, store_getter, self.path)
                send_json_response(self, data)
            except Exception as e:
                send_error_response(self, e)

        def _serve_discussions_api(self):
            try:
                data = _build_discussions_response(self.path)
                send_json_response(self, data)
            except Exception as e:
                send_error_response(self, e)

        def _serve_wiki_list(self):
            try:
                from mcp_server.handlers.wiki_api import list_wiki_pages
                from mcp_server.infrastructure.config import METHODOLOGY_DIR

                wiki_root = METHODOLOGY_DIR / "wiki"
                data = list_wiki_pages(wiki_root)
                send_json_response(self, {"pages": data})
            except Exception as e:
                send_error_response(self, e)

        def _serve_wiki_page(self):
            try:
                import urllib.parse

                from mcp_server.handlers.wiki_api import read_wiki_page
                from mcp_server.infrastructure.config import METHODOLOGY_DIR

                wiki_root = METHODOLOGY_DIR / "wiki"
                params = self.path.split("?", 1)
                rel_path = ""
                if len(params) > 1:
                    for p in params[1].split("&"):
                        if p.startswith("path="):
                            rel_path = urllib.parse.unquote(p[5:])
                data = read_wiki_page(wiki_root, rel_path)
                send_json_response(self, data)
            except Exception as e:
                send_error_response(self, e)

        def _qs(self) -> dict[str, str]:
            import urllib.parse as _p

            parts = self.path.split("?", 1)
            if len(parts) < 2:
                return {}
            return {
                k: _p.unquote(v)
                for k, v in (
                    kv.split("=", 1) if "=" in kv else (kv, "")
                    for kv in parts[1].split("&")
                    if kv
                )
            }

        def _serve_wiki_page_meta(self):
            try:
                from mcp_server.handlers.wiki_api import page_meta

                rel_path = self._qs().get("path", "")
                send_json_response(self, page_meta(rel_path))
            except Exception as e:
                send_error_response(self, e)

        def _serve_wiki_concepts(self):
            try:
                from mcp_server.handlers.wiki_api import list_concepts

                qs = self._qs()
                status = qs.get("status") or None
                limit = int(qs.get("limit", "100"))
                send_json_response(self, list_concepts(status, limit))
            except Exception as e:
                send_error_response(self, e)

        def _serve_wiki_drafts(self):
            try:
                from mcp_server.handlers.wiki_api import list_drafts

                qs = self._qs()
                status = qs.get("status") or None
                kind = qs.get("kind") or None
                limit = int(qs.get("limit", "100"))
                send_json_response(self, list_drafts(status, kind, limit))
            except Exception as e:
                send_error_response(self, e)

        def _serve_wiki_memos(self):
            try:
                from mcp_server.handlers.wiki_api import list_memos

                qs = self._qs()
                subject_type = qs.get("subject_type") or "page"
                subject_id = int(qs.get("subject_id", "0"))
                if subject_id == 0:
                    send_json_response(self, {"error": "subject_id required"})
                    return
                limit = int(qs.get("limit", "50"))
                send_json_response(self, list_memos(subject_type, subject_id, limit))
            except Exception as e:
                send_error_response(self, e)

        def _serve_wiki_views(self):
            try:
                from mcp_server.handlers.wiki_api import list_views

                send_json_response(self, list_views())
            except Exception as e:
                send_error_response(self, e)

        def _serve_wiki_view(self):
            try:
                from mcp_server.handlers.wiki_api import execute_view

                qs = self._qs()
                name = qs.get("name") or None
                query = qs.get("query") or None
                send_json_response(self, execute_view(name, query))
            except Exception as e:
                send_error_response(self, e)

        def _serve_wiki_bibliography(self):
            try:
                from mcp_server.handlers.wiki_api import list_bibliography
                from mcp_server.infrastructure.config import METHODOLOGY_DIR

                send_json_response(self, list_bibliography(METHODOLOGY_DIR / "wiki"))
            except Exception as e:
                send_error_response(self, e)

        def _serve_wiki_bibliography_read(self):
            try:
                from mcp_server.handlers.wiki_api import read_bibliography
                from mcp_server.infrastructure.config import METHODOLOGY_DIR

                rel_path = self._qs().get("path", "")
                send_json_response(
                    self, read_bibliography(METHODOLOGY_DIR / "wiki", rel_path)
                )
            except Exception as e:
                send_error_response(self, e)

        def _serve_wiki_export(self):
            """GET /api/wiki/export?path=X&format=pdf|tex|docx|html

            Streams the Pandoc-rendered bytes with the correct MIME
            type + Content-Disposition so the browser triggers a file
            download. Never exposes the base64 blob over HTTP — that
            path is reserved for the MCP tool.
            """
            try:
                import asyncio
                import base64

                from mcp_server.handlers.wiki_export import handler as _export

                qs = self._qs()
                rel_path = qs.get("path", "")
                fmt = qs.get("format", "pdf")
                result = asyncio.run(_export({"rel_path": rel_path, "format": fmt}))
                if not result.get("ok"):
                    send_json_response(self, result)
                    return
                data = base64.b64decode(result["content_base64"])
                # CodeQL py/http-response-splitting: the previous
                # re.sub() sanitizer wasn't recognised by the taint
                # tracker because rel_path still flowed into the
                # Content-Disposition header. Eliminate the taint
                # entirely by picking from a dict of compile-time
                # literals — the output value is ALWAYS one of four
                # constant strings, no user input path remains.
                _EXPORT_FILENAMES = {
                    "pdf": "cortex-export.pdf",
                    "tex": "cortex-export.tex",
                    "docx": "cortex-export.docx",
                    "html": "cortex-export.html",
                }
                safe_filename = _EXPORT_FILENAMES.get(
                    result.get("format", ""), "cortex-export.bin"
                )
                self.send_response(200)
                self.send_header("Content-Type", result["mime"])
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{safe_filename}"',
                )
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                send_error_response(self, e)

        def _serve_wiki_save(self):
            """POST /api/wiki/save — body: JSON {rel_path, body}."""
            try:
                import json as _json

                from mcp_server.handlers.wiki_api import save_wiki_page
                from mcp_server.infrastructure.config import METHODOLOGY_DIR

                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > 4_000_000:
                    send_json_response(self, {"error": "invalid content-length"})
                    return
                payload = _json.loads(self.rfile.read(length))
                rel_path = payload.get("rel_path", "")
                body = payload.get("body", "")
                result = save_wiki_page(METHODOLOGY_DIR / "wiki", rel_path, body)
                send_json_response(self, result)
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


def _do_background_build(
    profiles_getter,
    store_getter,
    domain_filter: str | None,
) -> None:
    """Build the full graph in background and cache it."""
    global _graph_cache, _graph_cache_ts, _cached_domain_hub_ids
    from mcp_server.core.unified_graph_builder import build_unified_graph

    acquired = _graph_build_lock.acquire(blocking=False)
    if not acquired:
        return  # Another build already in progress

    try:
        profiles = profiles_getter()
        store = store_getter()
        memories = store.get_hot_memories(min_heat=0.0, limit=0)
        entities = store.get_all_entities(min_heat=0.0)
        relationships = store.get_all_relationships()

        result = build_unified_graph(
            profiles=profiles,
            memories=[format_memory(m, 500) for m in memories],
            entities=[format_entity(e) for e in entities],
            relationships=[format_relationship(r) for r in relationships],
            filter_domain=domain_filter,
        )

        # System vitals
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

        # Session counts per domain from methodology profiles
        session_counts = {}
        for did, ddata in (profiles.get("domains") or {}).items():
            session_counts[did] = ddata.get("sessionCount", 0)
        result["meta"]["session_counts"] = session_counts

        _cached_domain_hub_ids = _extract_domain_hub_ids(result.get("nodes", []))
        _graph_cache = {"data": result, "domain_filter": domain_filter}
        _graph_cache_ts = time.monotonic()
        print(
            f"[cortex] Graph cache ready: {len(result.get('nodes', []))} nodes",
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"[cortex] Graph build error: {exc}", file=sys.stderr)
    finally:
        _graph_build_lock.release()


def _get_graph_response(profiles_getter, store_getter, path: str) -> dict:
    """Return cached full graph, or signal warming while building."""
    global _graph_cache, _graph_cache_ts

    params = _parse_query_params(path)
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
        args=(profiles_getter, store_getter, domain_filter),
        daemon=True,
    ).start()
    return {
        "nodes": [],
        "edges": [],
        "clusters": [],
        "meta": {"warming": True, "node_count": 0},
    }


def _extract_domain_hub_ids(nodes: list[dict]) -> dict[str, str]:
    """Extract domain_key -> node_id mapping from graph nodes."""
    hub_ids: dict[str, str] = {}
    for node in nodes:
        if node.get("type") == "domain":
            domain_key = node.get("domain", "")
            if domain_key:
                hub_ids[domain_key] = node["id"]
    return hub_ids


def _bind_and_start(
    handler_cls,
    preferred_port: int,
    profiles_getter=None,
    store_getter=None,
) -> str:
    """Bind to preferred port (fallback to OS-assigned) and start serving."""
    global _unified_server

    for port in [preferred_port, 0]:
        try:
            server = _ThreadedHTTPServer(("127.0.0.1", port), handler_cls)
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

            # Pre-warm graph cache in background
            if profiles_getter and store_getter:
                warm = threading.Thread(
                    target=_do_background_build,
                    args=(profiles_getter, store_getter, None),
                    daemon=True,
                )
                warm.start()

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
