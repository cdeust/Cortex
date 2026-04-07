"""Handler: wiki_sync — render Cortex memory state as a Markdown wiki.

Composition root for the read-only wiki projection. Pulls a domain
snapshot from existing profile storage, hands it to core.wiki_projection
for pure rendering, and writes the result via infrastructure.wiki_writer.

Slice 1: global INDEX.md + per-domain INDEX.md only. Schemas, causal
chains and Mermaid diagrams arrive in later slices. Never touches the
recall hot path; not invoked from `consolidate`.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.wiki_projection import (
    CausalChain,
    DomainSummary,
    SchemaInfo,
    WikiSnapshot,
    build_pages,
)

_CHAIN_TOP_MEMORIES_PER_DOMAIN = 3
_CHAIN_BFS_DEPTH = 2
_CHAIN_BFS_MAX_EDGES = 12
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.profile_store import load_profiles
from mcp_server.infrastructure.wiki_writer import sync as wiki_sync_write

_store: MemoryStore | None = None


def _get_store() -> MemoryStore | None:
    """Lazily acquire the memory store. Returns None if backend is unavailable."""
    global _store
    if _store is None:
        try:
            settings = get_memory_settings()
            _store = MemoryStore(settings.SQLITE_FALLBACK_PATH, settings.EMBEDDING_DIM)
        except Exception:
            return None
    return _store

schema = {
    "description": (
        "Render Cortex memory state as a browsable Markdown wiki under "
        "~/.claude/methodology/wiki/. Read-only projection of PostgreSQL "
        "state — never a source of truth. Use for inspectability."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Limit to a single domain id (default: all).",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Plan only; do not write files.",
            },
        },
    },
}


def _domain_to_summary(d: dict[str, Any]) -> DomainSummary:
    cats = d.get("categories") or {}
    top = tuple(
        cat for cat, _ in sorted(cats.items(), key=lambda x: x[1], reverse=True)[:3]
    )
    shape = d.get("sessionShape") or {}
    return DomainSummary(
        id=str(d.get("id") or "unknown"),
        label=str(d.get("label") or d.get("id") or "Unknown"),
        session_count=int(d.get("sessionCount") or 0),
        confidence=float(d.get("confidence") or 0.0),
        last_active=d.get("lastUpdated"),
        top_categories=top,
        dominant_mode=shape.get("dominantMode") if isinstance(shape, dict) else None,
    )


def _row_to_schema(row: dict[str, Any]) -> SchemaInfo:
    """Convert a `schemas` row to a SchemaInfo. Tolerates JSON or dict."""
    sig = row.get("entity_signature") or {}
    if isinstance(sig, str):
        import json

        try:
            sig = json.loads(sig)
        except (ValueError, TypeError):
            sig = {}
    tags = row.get("tag_signature") or {}
    if isinstance(tags, str):
        import json

        try:
            tags = json.loads(tags)
        except (ValueError, TypeError):
            tags = {}
    return SchemaInfo(
        schema_id=str(row.get("schema_id") or ""),
        domain_id=str(row.get("domain") or ""),
        label=str(row.get("label") or row.get("schema_id") or ""),
        entity_signature={k: float(v) for k, v in (sig or {}).items()},
        tag_signature={k: float(v) for k, v in (tags or {}).items()},
        formation_count=int(row.get("formation_count") or 0),
        assimilation_count=int(row.get("assimilation_count") or 0),
        violation_count=int(row.get("violation_count") or 0),
    )


def _collect_schemas(domain_ids: list[str]) -> tuple[SchemaInfo, ...]:
    store = _get_store()
    if store is None or not hasattr(store, "get_schemas_for_domain"):
        return ()
    out: list[SchemaInfo] = []
    for did in domain_ids:
        try:
            rows = store.get_schemas_for_domain(did) or []
        except Exception:
            continue
        out.extend(_row_to_schema(r) for r in rows)
    return tuple(out)


def _bfs_edges(store: Any, start_entity_id: int) -> list[tuple[str, str, str]]:
    """BFS the entity graph from a seed; resolve names. Tolerant of failure."""
    from collections import deque

    edges: list[tuple[str, str, str]] = []
    visited: set[int] = {start_entity_id}
    queue: deque[tuple[int, int]] = deque([(start_entity_id, 0)])
    name_cache: dict[int, str] = {}

    def _name(eid: int) -> str:
        if eid in name_cache:
            return name_cache[eid]
        try:
            ent = store.get_entity_by_id(eid)
        except Exception:
            ent = None
        name = ent.get("name") if ent else f"entity:{eid}"
        name_cache[eid] = name
        return name

    while queue and len(edges) < _CHAIN_BFS_MAX_EDGES:
        eid, depth = queue.popleft()
        if depth >= _CHAIN_BFS_DEPTH:
            continue
        try:
            rels = store.get_relationships_for_entity(eid, direction="both", limit=10)
        except Exception:
            continue
        for rel in rels or []:
            if len(edges) >= _CHAIN_BFS_MAX_EDGES:
                break
            src_id = rel.get("source_entity_id")
            tgt_id = rel.get("target_entity_id")
            if src_id is None or tgt_id is None:
                continue
            edges.append(
                (_name(src_id), str(rel.get("relationship_type") or "related"), _name(tgt_id))
            )
            for nxt in (src_id, tgt_id):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, depth + 1))
    return edges


def _seed_chain_from_memory(
    store: Any, domain_id: str, memory: dict[str, Any]
) -> CausalChain | None:
    """Extract the first known entity from a memory and BFS from it."""
    try:
        from mcp_server.core.knowledge_graph import extract_entities
    except Exception:
        return None

    content = memory.get("content") or ""
    extracted = extract_entities(content) or []
    seed_entity = None
    for ent in extracted:
        try:
            found = store.get_entity_by_name(ent.get("name", ""))
        except Exception:
            found = None
        if found:
            seed_entity = found
            break
    if not seed_entity:
        return None

    edges = _bfs_edges(store, int(seed_entity["id"]))
    if not edges:
        return None

    mem_id = int(memory.get("id") or 0)
    label = (content[:60] + "…") if len(content) > 60 else content or f"memory {mem_id}"
    return CausalChain(
        chain_id=f"mem_{mem_id}",
        domain_id=domain_id,
        seed_memory_id=mem_id,
        seed_label=label.replace("\n", " ").strip(),
        seed_heat=float(memory.get("heat") or 0.0),
        edges=tuple(edges),
    )


def _collect_chains(domain_ids: list[str]) -> tuple[CausalChain, ...]:
    store = _get_store()
    if store is None or not hasattr(store, "get_memories_for_domain"):
        return ()
    out: list[CausalChain] = []
    for did in domain_ids:
        try:
            mems = store.get_memories_for_domain(did, min_heat=0.3, limit=50) or []
        except Exception:
            continue
        mems_sorted = sorted(
            mems, key=lambda m: float(m.get("heat") or 0.0), reverse=True
        )[:_CHAIN_TOP_MEMORIES_PER_DOMAIN]
        for mem in mems_sorted:
            chain = _seed_chain_from_memory(store, did, mem)
            if chain is not None:
                out.append(chain)
    return tuple(out)


def _build_snapshot(domain_filter: str | None) -> WikiSnapshot:
    profiles = load_profiles() or {}
    raw_domains = (profiles.get("domains") or {}).values()
    summaries = [_domain_to_summary(d) for d in raw_domains]
    if domain_filter:
        summaries = [s for s in summaries if s.id == domain_filter]
    domain_ids = [s.id for s in summaries]
    schemas = _collect_schemas(domain_ids)
    chains = _collect_chains(domain_ids)
    return WikiSnapshot(
        domains=tuple(summaries),
        global_style=profiles.get("globalStyle"),
        schemas=schemas,
        chains=chains,
    )


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Render the wiki projection to disk and return a sync summary."""
    args = args or {}
    domain_filter = args.get("domain") or None
    dry_run = bool(args.get("dry_run", False))

    snapshot = _build_snapshot(domain_filter)
    pages = build_pages(snapshot)
    result = wiki_sync_write(WIKI_ROOT, pages, dry_run=dry_run)

    return {
        "written": result.written,
        "skipped": result.skipped,
        "pruned": result.pruned,
        "root": result.root,
        "domains": len(snapshot.domains),
        "pages": len(pages),
        "dry_run": dry_run,
    }
