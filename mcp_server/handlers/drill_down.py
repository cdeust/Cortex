"""Handler: drill_down — navigate into a fractal memory cluster.

Given a cluster ID (L2-N or L1-N), returns the children of that cluster.
L2 -> L1 child clusters.
L1 -> individual memory IDs with content.

Cluster IDs are returned by recall_hierarchical in the hierarchy response.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import fractal
from mcp_server.infrastructure.embedding_engine import get_embedding_engine
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.handlers._tool_meta import READ_ONLY

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "title": "Drill down",
    "annotations": READ_ONLY,
    "description": (
        "Descend one level into a fractal memory cluster previously "
        "returned by `recall_hierarchical`: an L2 root cluster expands to "
        "its L1 sub-clusters; an L1 cluster expands to the individual "
        "memories it contains (full content, heat, tags). Cluster IDs use "
        "the form `L<level>-<index>`. Use this for interactive top-down "
        "exploration — start broad with `recall_hierarchical`, then drill "
        "the most-relevant cluster repeatedly until you reach memories. "
        "Distinct from `recall` (flat ranked list, no hierarchy), "
        "`navigate_memory` (graph BFS via co-access edges, not cluster "
        "tree), and `recall_hierarchical` (entry point that builds the "
        "tree). Mutates access_count on surfaced memories (drives "
        "consolidation cascade). Latency <100ms. Returns {cluster_id, "
        "level, children: [{id, label, members?, content?}]}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["cluster_id"],
        "properties": {
            "cluster_id": {
                "type": "string",
                "description": (
                    "Cluster identifier returned by recall_hierarchical. "
                    "Format: 'L<level>-<index>'."
                ),
                "pattern": "^L[0-9]+-[0-9]+$",
                "examples": ["L2-0", "L1-3", "L1-12"],
            },
            "domain": {
                "type": "string",
                "description": "Cognitive domain to build the underlying hierarchy from. Omit for global.",
                "examples": ["cortex", "auth-service"],
            },
            "min_heat": {
                "type": "number",
                "description": "Minimum heat (0.0-1.0) for a memory to be eligible for the hierarchy.",
                "default": 0.05,
                "minimum": 0.0,
                "maximum": 1.0,
                "examples": [0.0, 0.05, 0.3],
            },
        },
    },
}

# ── Singletons ────────────────────────────────────────────────────────────

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Helpers ───────────────────────────────────────────────────────────────


def _fetch_candidate_memories(
    store: MemoryStore,
    domain: str,
    min_heat: float,
) -> list[dict]:
    """Fetch memories eligible for hierarchy building."""
    if domain:
        return store.get_memories_for_domain(domain, min_heat=min_heat, limit=500)

    all_mems = store.get_all_memories_for_decay()
    return [m for m in all_mems if m.get("heat", 0) >= min_heat]


def _enrich_leaf_memories(
    children_raw: list[dict],
    store: MemoryStore,
) -> list[dict]:
    """Enrich L1 leaf children with full memory data."""
    children = []
    for item in children_raw:
        mid = item.get("memory_id")
        mem = store.get_memory(mid) if mid else None
        if mem:
            children.append(
                {
                    "memory_id": mid,
                    "content": mem["content"],
                    "heat": round(mem.get("heat", 0), 4),
                    "domain": mem.get("domain", ""),
                    "tags": mem.get("tags", []),
                }
            )
    return children


def _format_cluster_children(children_raw: list[dict]) -> list[dict]:
    """Format L2 -> L1 cluster children."""
    return [
        {
            "cluster_id": cluster.get("cluster_id"),
            "level": cluster.get("level"),
            "size": cluster.get("size", 0),
            "avg_heat": round(cluster.get("avg_heat", 0), 4),
            "memory_ids": cluster.get("memory_ids", []),
        }
        for cluster in children_raw
    ]


def _build_hierarchy_from_store(
    domain: str,
    min_heat: float,
) -> dict:
    """Fetch memories and build the fractal hierarchy."""
    store = _get_store()
    embeddings = get_embedding_engine()
    settings = get_memory_settings()

    memories = _fetch_candidate_memories(store, domain, min_heat)
    if not memories:
        return {}

    return fractal.build_hierarchy(
        memories=memories,
        similarity_fn=embeddings.similarity,
        embedding_dim=settings.EMBEDDING_DIM,
    )


# ── Handler ───────────────────────────────────────────────────────────────


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Drill into a fractal memory cluster."""
    if not args or not args.get("cluster_id"):
        return {"children": [], "cluster_id": None}

    cluster_id = args["cluster_id"]
    domain = args.get("domain", "")
    min_heat = float(args.get("min_heat", 0.05))

    hierarchy = _build_hierarchy_from_store(domain, min_heat)
    if not hierarchy:
        return {"children": [], "cluster_id": cluster_id, "reason": "no_memories"}

    children_raw = fractal.drill_down(cluster_id, hierarchy)
    if not children_raw:
        return {
            "children": [],
            "cluster_id": cluster_id,
            "reason": "cluster_not_found_or_empty",
        }

    store = _get_store()
    if "memory_id" in children_raw[0]:
        children = _enrich_leaf_memories(children_raw, store)
        # Track replay for drilled-into memories
        for child in children:
            mid = child.get("memory_id")
            if mid:
                try:
                    store.update_memory_access(mid)
                    store.increment_replay_count(mid)
                except Exception:
                    pass
    else:
        children = _format_cluster_children(children_raw)

    return {
        "cluster_id": cluster_id,
        "children": children,
        "child_count": len(children),
    }
