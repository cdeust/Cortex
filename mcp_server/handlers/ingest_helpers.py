"""Shared helpers for ingest_codebase and ingest_prd handlers.

Two concerns live here:

1. Graph-path memoisation — after a codebase analysis, the returned
   graph_path is stored as a protected Cortex memory tagged
   ``_code_graph:<project-id>`` so subsequent ingest runs can reuse
   the same graph without re-indexing.

2. Safe MCP calls — wraps mcp_client_pool.get_client + call with a
   uniform error shape so ingest handlers don't each re-derive the
   try/except boilerplate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mcp_server.infrastructure.mcp_client_pool import get_client

CODE_GRAPH_TAG_PREFIX = "_code_graph:"


def project_key(project_path: str) -> str:
    """Stable project key = last path segment + short hash of full path."""
    p = Path(project_path).expanduser().resolve()
    digest = hashlib.sha256(str(p).encode("utf-8")).hexdigest()[:8]
    return f"{p.name}-{digest}"


def code_graph_tag(project_path: str) -> str:
    """Canonical tag used to memoise a code graph path for a project."""
    return f"{CODE_GRAPH_TAG_PREFIX}{project_key(project_path)}"


def find_cached_graph(store, project_path: str) -> str | None:
    """Return the cached graph_path for a project, or None if not cached.

    Reads the most-recent memory tagged with the project's code-graph tag.
    """
    tag = code_graph_tag(project_path)
    try:
        mems = store.get_all_memories_for_decay()
    except Exception:
        return None
    for mem in mems:
        raw_tags = mem.get("tags", [])
        if isinstance(raw_tags, str):
            try:
                raw_tags = json.loads(raw_tags)
            except (ValueError, TypeError):
                raw_tags = []
        if tag in raw_tags:
            content = mem.get("content") or ""
            if content.startswith("graph_path="):
                return content[len("graph_path=") :].strip()
    return None


def memoise_graph_path(store, project_path: str, graph_path: str) -> int | None:
    """Persist the graph path as a protected memory for future lookups.

    Uses raw insert_memory (not the predictive-coding gate) so ingestion
    state is always recorded, even when low-surprise.
    """
    tag = code_graph_tag(project_path)
    record = {
        "content": f"graph_path={graph_path}",
        "tags": [tag, "_ingest", "code-graph"],
        "source": "ingest_codebase",
        "domain": "cortex-ingest",
        "directory_context": str(Path(project_path).expanduser().resolve()),
        "is_protected": True,
        "importance": 1.0,
        "heat": 1.0,
    }
    try:
        return store.insert_memory(record)
    except Exception:
        return None


async def call_upstream(
    server_name: str,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Invoke a tool on an upstream MCP server; return parsed result.

    Raises McpConnectionError on connection/transport failure. Returns
    the tool result as a plain dict when the server answers successfully.
    """
    client = await get_client(server_name)
    response = await client.call(tool_name, args)
    if isinstance(response, dict):
        return response
    if isinstance(response, str):
        try:
            return json.loads(response)
        except (ValueError, TypeError):
            return {"text": response}
    return {"value": response}


def normalise_mcp_payload(payload: Any) -> Any:
    """MCP call() sometimes returns a dict with a 'content' array.

    The pipeline's tools emit ``{"content": [{"type": "text", "text": "{...}"}]}``;
    callers want the inner JSON. Other servers answer with a plain dict.
    This helper collapses both shapes to the underlying object.
    """
    if isinstance(payload, dict) and "content" in payload:
        content = payload["content"]
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and first.get("type") == "text":
                text = first.get("text", "")
                try:
                    return json.loads(text)
                except (ValueError, TypeError):
                    return {"text": text}
    return payload
