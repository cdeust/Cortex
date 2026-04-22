"""Graph cache and discussion-page builders for the standalone server.

Extracted from ``http_standalone.py`` to keep that file inside the
project-mandated 300-line ceiling. The module owns:

* graph-cache state (TTL, lock, domain-hub id map)
* ``build_and_cache_graph`` — the background-thread workflow-graph build
* ``get_graph_response`` — cache read with warming signal on miss
* ``build_discussions_response`` — paginated discussion listing
* ``build_discussion_detail`` — single-session detail
* ``parse_discussion_params`` / ``parse_graph_query`` — query-string parsers
* ``extract_domain_hub_ids`` — domain key → node id extraction

All I/O stays behind the existing infrastructure imports; the only
layer-relevant addition is that this module lives in ``server/`` and
composes ``handlers/workflow_graph`` + ``core/graph_builder_discussions``,
which matches the rules for server → handlers/core wiring.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback

from mcp_server.server.http_standalone_state import (
    CONVERSATIONS_CACHE_TTL,
    GRAPH_CACHE_TTL,
    get_cached_conversations_state,
    set_cached_conversations_state,
)

_cached_domain_hub_ids: dict[str, str] = {}

_graph_cache: dict | None = None
_graph_cache_ts: float = 0.0
_graph_build_lock = threading.Lock()


def parse_graph_query(path: str) -> dict:
    """Parse ``/api/graph`` query string into domain/batch/batch_size."""
    result: dict = {"domain_filter": None, "batch": 0, "batch_size": 0}
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


def parse_discussion_params(path: str) -> dict:
    """Parse ``/api/discussions`` query string."""
    result: dict = {"project": None, "batch": 0, "batch_size": 500}
    if "?" not in path:
        return result
    for p in path.split("?", 1)[1].split("&"):
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


def extract_domain_hub_ids(nodes: list[dict]) -> dict[str, str]:
    """Map domain label → node id across workflow-graph nodes."""
    hub_ids: dict[str, str] = {}
    for node in nodes:
        if node.get("type") == "domain" or node.get("kind") == "domain":
            domain_key = node.get("label") or node.get("domain") or ""
            if domain_key:
                hub_ids[domain_key] = node["id"]
    return hub_ids


def _compute_memory_vitals(store) -> dict:
    """Aggregate consolidation-stage counts, mean heat, and store-type split."""
    memories = store.get_hot_memories(min_heat=0.0, limit=0)
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
    return {
        "consolidation_pipeline": stages,
        "mean_heat": round(sum(heats) / max(len(heats), 1), 4),
        "total_memories": len(memories),
        "episodic": episodic,
        "semantic": semantic,
    }


def _session_counts_from_profiles(profiles: dict) -> dict[str, int]:
    """Extract per-domain session counts from a profiles.json payload."""
    out: dict[str, int] = {}
    for did, ddata in (profiles.get("domains") or {}).items():
        out[did] = ddata.get("sessionCount", 0)
    return out


def build_and_cache_graph(store, domain_filter: str | None) -> None:
    """Build the workflow graph and update the module-level cache.

    Guarded by a non-blocking lock so concurrent requests collapse into
    a single build. All exceptions are caught and traced to stderr so a
    bad cache build never takes the background thread with it.
    """
    from mcp_server.handlers.workflow_graph import build_workflow_graph
    from mcp_server.infrastructure.profile_store import load_profiles

    global _graph_cache, _graph_cache_ts, _cached_domain_hub_ids

    acquired = _graph_build_lock.acquire(blocking=False)
    if not acquired:
        return

    try:
        data = build_workflow_graph(store, domain_filter=domain_filter)
        data["meta"]["system_vitals"] = _compute_memory_vitals(store)
        data["meta"]["session_counts"] = _session_counts_from_profiles(load_profiles())
        _cached_domain_hub_ids = extract_domain_hub_ids(data.get("nodes", []))
        _graph_cache = {"data": data, "domain_filter": domain_filter}
        _graph_cache_ts = time.monotonic()
        print(
            f"[cortex] Workflow graph cache ready: "
            f"{len(data.get('nodes', []))} nodes, "
            f"{len(data.get('edges', []))} edges",
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"[cortex] Workflow graph build error: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # Publish a deterministic failure payload. Without this the cache
        # stays empty and the client loops forever on warming=True — a
        # silent wrong (Feynman integrity audit 2026-04-22).
        _graph_cache = {
            "data": {
                "nodes": [],
                "edges": [],
                "links": [],
                "meta": {
                    "schema": "workflow_graph.v1",
                    "error": type(exc).__name__,
                    "node_count": 0,
                    "edge_count": 0,
                },
            },
            "domain_filter": domain_filter,
        }
        _graph_cache_ts = time.monotonic()
    finally:
        _graph_build_lock.release()


def get_graph_response(store, path: str) -> dict:
    """Return cached graph or a warming placeholder plus background build."""
    params = parse_graph_query(path)
    domain_filter = params["domain_filter"]
    now = time.monotonic()
    cache_valid = (
        _graph_cache
        and _graph_cache.get("domain_filter") == domain_filter
        and (now - _graph_cache_ts) < GRAPH_CACHE_TTL
    )
    if cache_valid:
        return _graph_cache["data"]
    threading.Thread(
        target=build_and_cache_graph,
        args=(store, domain_filter),
        daemon=True,
    ).start()
    return {
        "nodes": [],
        "edges": [],
        "clusters": [],
        "meta": {"warming": True, "node_count": 0},
    }


def _get_cached_conversations() -> list[dict]:
    """Shared cache wrapper — refreshes via ``discover_conversations``."""
    cached, ts = get_cached_conversations_state()
    now = time.time()
    if cached is None or (now - ts) > CONVERSATIONS_CACHE_TTL:
        from mcp_server.infrastructure.scanner import discover_conversations

        cached = discover_conversations()
        set_cached_conversations_state(cached, now)
    return cached


def build_discussions_response(path: str) -> dict:
    """Paginated response for ``/api/discussions``."""
    from mcp_server.core.graph_builder_discussions import build_discussion_nodes

    params = parse_discussion_params(path)
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


def _find_session_file(session_id: str):
    """Whitelist scan of every project dir for ``<session_id>.jsonl``."""
    from mcp_server.infrastructure.config import CLAUDE_DIR

    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.is_dir():
        return None
    target = session_id + ".jsonl"
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / target
        if candidate.is_file():
            return candidate
    return None


def build_discussion_detail(session_id: str) -> dict:
    """Detail response for ``/api/discussion/<session_id>``."""
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

    found_path = _find_session_file(session_id)
    if found_path is None:
        return {"error": "Session file not found", "sessionId": session_id}

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
