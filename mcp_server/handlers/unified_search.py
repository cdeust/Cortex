"""Handler: unified_search — RRF-fuse Cortex memory recall with AP code
search (ADR-0046 Phase 3).

Composition root: cortex.recall (semantic memory) + ap.search_codebase
(code symbols) → core.unified_search_fusion → single ranked list.

When AP is off, the handler returns Cortex-only results marked
``status: partial, sources: [cortex]`` — never fails. When Cortex
returns nothing and AP is on, the response is the AP-only hits.

The fusion contract: each input list must present unique string ids.
- Memories use ``memory:<memory_id>`` (added by this handler).
- AP symbols use ``symbol:<file>::<qualname>`` (added by the infra
  layer).
Ids never collide across sources.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.unified_search_fusion import DEFAULT_K, fuse
from mcp_server.handlers.recall import handler as recall_handler
from mcp_server.infrastructure.ap_bridge import is_enabled
from mcp_server.infrastructure.workflow_graph_source_ast import (
    WorkflowGraphASTSource,
)
from mcp_server.handlers._tool_meta import READ_ONLY


schema = {
    "title": "Unified search",
    "annotations": READ_ONLY,
    "description": (
        "Unified search across Cortex memories and the automatised-"
        "pipeline code graph (ADR-0046 Phase 3). Runs cortex.recall and "
        "ap.search_codebase in parallel, then merges via Reciprocal "
        "Rank Fusion (k=60, Cormack 2009). Returns a single ranked "
        "list with ``source_ranks`` on every record so the UI can "
        "explain where each hit came from. Falls back to Cortex-only "
        "when CORTEX_ENABLE_AP is unset (status=partial)."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "Natural-language query."},
            "domain": {
                "type": "string",
                "description": "Optional Cortex domain filter.",
            },
            "max_results": {
                "type": "integer",
                "default": 10,
                "description": "Top-N of the fused list.",
            },
            "k": {
                "type": "integer",
                "default": DEFAULT_K,
                "description": "RRF constant (default 60).",
            },
        },
    },
}


def _prep_memories(results: list[dict]) -> list[dict]:
    """Tag memory records with fusion-friendly ``id`` and preserve the
    retriever's own ordering (this is the one RRF consumes)."""
    out: list[dict] = []
    for r in results or []:
        mid = r.get("memory_id") or r.get("id")
        if mid is None:
            continue
        rec = {**r}
        rec["id"] = f"memory:{mid}"
        rec.setdefault("source", "cortex")
        out.append(rec)
    return out


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    top_n = int(args.get("max_results") or 10)
    k = int(args.get("k") or DEFAULT_K)

    # Run Cortex recall. We ask for 2× top_n so the fusion has room.
    recall_args = {k: v for k, v in args.items() if k != "k"}
    recall_args["max_results"] = max(top_n * 2, top_n)
    cortex_result = await recall_handler(recall_args)
    memories = _prep_memories(cortex_result.get("results") or [])

    sources = ["cortex"]
    ap_hits: list[dict] = []
    if is_enabled():
        ast_source = WorkflowGraphASTSource()
        ap_hits = ast_source.search_codebase(query, limit=max(top_n * 2, top_n))
        sources.append("ap")

    fused = fuse(
        [("cortex", memories), ("ap", ap_hits)],
        k=k,
        top_n=top_n,
    )
    return {
        "status": "ok" if is_enabled() else "partial",
        "query": query,
        "sources": sources,
        "counts": {
            "cortex": len(memories),
            "ap": len(ap_hits),
            "fused": len(fused),
        },
        "results": fused,
        "k": k,
    }


__all__ = ["handler", "schema"]
