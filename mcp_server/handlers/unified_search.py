"""Handler: unified_search — RRF-fuse Cortex memory recall with AP code
search.

Composition root: cortex.recall (semantic memory) + ap.search_codebase
(code symbols) → core.unified_search_fusion → single ranked list.

The fusion contract: each input list must present unique string ids.
- Memories use ``memory:<memory_id>`` (added by this handler).
- AP symbols use ``symbol:<file>::<qualname>`` (added by the infra
  layer).
Ids never collide across sources.

source: ADR-0450"""

from __future__ import annotations

from typing import Any

from mcp_server.core.response_budget import ListTarget, bound_payload
from mcp_server.core.unified_search_fusion import DEFAULT_K, fuse
from mcp_server.handlers.recall import handler as recall_handler
from mcp_server.handlers.decision_recall import (
    SCOPE_PROPERTIES,
    exact_lookup,
    search_wiki,
)
from mcp_server.infrastructure.ap_bridge import is_enabled
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.workflow_graph_source_ast import (
    WorkflowGraphASTSource,
)
from mcp_server.handlers._tool_meta import READ_ONLY


schema = {
    "title": "Unified search",
    "annotations": READ_ONLY,
    "description": (
        # source: ADR-0450
        "Unified search across Cortex memories and the "
        "automatised-pipeline code graph. Runs cortex.recall and "
        "ap.search_codebase in parallel, then merges via Reciprocal Rank "
        "Fusion (k=60). Returns a single ranked list with "
        "``source_ranks`` on every record so the UI can explain where "
        "each hit came from. Falls back to Cortex-only when AP is "
        "disabled (CORTEX_MEMORY_AP_ENABLED=0) or unreachable "
        "(status=partial). An explicit project_root adds authored wiki "
        "pages matching every query token. Bare ADR-NNNN or exact_id "
        "queries resolve only the canonical wiki page, before memory/AP "
        "calls."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["query"],
        "properties": {
            **SCOPE_PROPERTIES,
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
            "cross_domain": {
                "type": "boolean",
                "default": False,
                "description": (
                    # source: ADR-0450
                    "Forwarded to cortex.recall's spreading-activation cross-domain "
                    "opt-in. Defaults to false, excluding candidates reached from "
                    "other domains."
                ),
            },
            "sa_mode": {
                "type": "string",
                "enum": ["tail", "augment", "off"],
                "default": "tail",
                "description": (
                    # source: ADR-0450
                    "Forwarded to cortex.recall's spreading-activation mode. Defaults "
                    "to ``tail``; see recall's schema for mode semantics."
                ),
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


def _exact_response(exact: dict, query: str) -> dict:
    results = exact["memories"]
    response = {
        "status": exact["status"],
        "query": query,
        "sources": ["wiki"],
        "degraded": None,
        "counts": {"wiki": len(results), "fused": len(results)},
        "results": results,
    }
    if "reason" in exact:
        response["reason"] = exact["reason"]
    response = bound_payload(
        response, [ListTarget("results")], get_memory_settings().MAX_RESPONSE_CHARS
    )
    response["counts"]["fused"] = len(response["results"])
    return response


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    query = str(args.get("query") or "").strip()
    top_n = int(args.get("max_results") or 10)
    k = int(args.get("k") or DEFAULT_K)

    exact = exact_lookup(args)
    if exact is not None:
        return _exact_response(exact, query)
    if not query:
        return {"error": "query is required"}
    try:
        wiki_hits = search_wiki(args, top_n)
    except (ValueError, OSError) as exc:
        return {"status": "error", "error": str(exc), "results": []}

    # Run Cortex recall. We ask for 2× top_n so the fusion has room.
    recall_args = {k: v for k, v in args.items() if k != "k"}
    recall_args["max_results"] = max(top_n * 2, top_n)
    cortex_result = await recall_handler(recall_args)
    memories = _prep_memories(cortex_result.get("memories") or [])

    return _fused_response(args, memories, wiki_hits, top_n, k)


def _ap_results(query: str, top_n: int) -> tuple[list[dict], str | None]:
    if not is_enabled():
        return [], None
    ast_source = WorkflowGraphASTSource()
    hits = ast_source.search_codebase(query, limit=max(top_n * 2, top_n))
    return hits, ast_source.last_search_degraded_reason


def _fused_response(
    args: dict, memories: list, wiki_hits: list, top_n: int, k: int
) -> dict:
    query = str(args["query"]).strip()
    sources = ["cortex"] + (["wiki"] if args.get("project_root") else [])
    ap_hits, ap_degraded_reason = _ap_results(query, top_n)
    if is_enabled():
        sources.append("ap")
    fused = fuse(
        [("cortex", memories), ("ap", ap_hits), ("wiki", wiki_hits)],
        k=k,
        top_n=top_n,
    )
    status = "partial" if not is_enabled() or ap_degraded_reason else "ok"
    degraded = (
        {"source": "ap", "reason": ap_degraded_reason} if ap_degraded_reason else None
    )
    resp = {
        "status": status,
        "degraded": degraded,
        "query": query,
        "sources": sources,
        "counts": {
            "cortex": len(memories),
            "ap": len(ap_hits),
            **({"wiki": len(wiki_hits)} if args.get("project_root") else {}),
            "fused": len(fused),
        },
        "results": fused,
        "k": k,
    }
    return _bounded_results(resp)


def _bounded_results(resp: dict) -> dict:
    # Memory bodies, AP snippets, and wiki pages share the existing host budget.
    resp = bound_payload(
        resp,
        [
            ListTarget("results", weight_key="score"),
            ListTarget("results", content_key="snippet", weight_key="score"),
        ],
        get_memory_settings().MAX_RESPONSE_CHARS,
    )
    resp["counts"]["fused"] = len(resp["results"])
    return resp


__all__ = ["handler", "schema"]
