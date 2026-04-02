"""Memory ingestion: decompose, extract entities, store.

Handles the write path for memories that may need decomposition.
Uses structure-aware chunking (speaker turns for conversations,
headings for markdown) following the ai-architect artifact chunking
strategy. Each chunk gets entity-enriched embeddings.

Used by both production handlers and benchmarks.

Pure business logic — takes a store + embeddings, handles decomposition.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.memory_decomposer import (
    build_entity_summary,
    decompose_memory,
)


def ingest_memory(
    memory: dict[str, Any],
    store: Any,
    embeddings: Any,
    *,
    domain: str = "",
    decompose: bool = True,
    turns_per_chunk: int = 6,
    is_benchmark: bool = False,
) -> list[int]:
    """Ingest a memory, optionally decomposing at structural boundaries.

    Uses speaker-turn chunking for conversations, heading chunking for
    markdown. Each chunk gets entity-enriched embeddings for better
    retrieval. All chunks inherit the parent memory's source field.

    Args:
        memory: Dict with 'content' and optional metadata fields.
        store: PgMemoryStore instance.
        embeddings: EmbeddingEngine instance.
        domain: Domain tag for the memory.
        decompose: Whether to decompose long content.
        turns_per_chunk: Speaker turns per chunk (conversation content).

    Returns:
        List of inserted memory IDs.
    """
    content = memory.get("content", "")
    if not content or not content.strip():
        return []

    if decompose:
        chunks = decompose_memory(content, turns_per_chunk=turns_per_chunk)
    else:
        chunks = [{"content": content, "entities": {}}]

    ids = []
    for chunk in chunks:
        chunk_content = chunk["content"]
        entities = chunk.get("entities", {})

        # Build embedding with entity summary prefix for better targeting
        entity_summary = build_entity_summary(entities)
        embed_text = (
            f"{entity_summary}\n{chunk_content}" if entity_summary else chunk_content
        )

        emb = None
        if embeddings and hasattr(embeddings, "encode"):
            emb = embeddings.encode(embed_text[:2000])

        # Entity-derived tags
        tags = list(memory.get("tags", []))
        if entities.get("has_preference"):
            tags.append("preference")
        if entities.get("has_decision"):
            tags.append("decision")
        if entities.get("has_activity"):
            tags.append("activity")

        # ── Decision auto-protection ────────────────────────────────
        # Decisions carry resolved prediction error (dopamine burst),
        # warranting stronger consolidation and protection from decay.
        #
        # Paper backing (WHY decisions deserve protection):
        #   McGaugh 2004: emotionally significant → ~2x retention
        #   Adcock et al. 2006: reward-motivated → ~1.5x recall boost
        #   Schultz 1997: decision = resolved prediction error = DA burst
        #
        # Detection: regex in memory_decomposer.py (engineering heuristic,
        # NOT paper-prescribed — labels as such).
        #
        # Protection: is_protected=True survives decay (Frey & Morris 1997
        # synaptic tagging — strong events promote weak traces).
        is_decision = entities.get("has_decision", False)
        auto_protect = is_decision and not is_benchmark
        importance_boost = 1.5 if is_decision else 1.0  # Adcock et al. 2006

        # ── Team memory propagation (TMS) ──────────────────────────
        # Wegner 1987 Transactive Memory Systems: team knowledge requires
        # coordination — important discoveries should be visible across
        # agent boundaries. Protected/decision memories auto-propagate
        # to team scope via is_global flag.
        #
        # Zhang et al. ACL 2024: specialized agents with shared directory
        # outperform shared-everything by 10-15%.
        #
        # Implementation: agent-scoped by default (specialization), but
        # decisions and protected items become global (coordination).
        agent_ctx = memory.get("agent_context", "")
        is_global = memory.get("is_global", False)
        if auto_protect and agent_ctx and not is_benchmark:
            is_global = True  # TMS coordination: decisions propagate

        mid = store.insert_memory(
            {
                "content": chunk_content,
                "embedding": emb,
                "domain": domain,
                "source": memory.get("source", ""),
                "tags": tags,
                "created_at": memory.get("created_at") or memory.get("date"),
                "heat": memory.get("heat", 1.0),
                "importance": min(
                    memory.get("importance", 0.5) * importance_boost, 1.0
                ),
                "store_type": memory.get("store_type", "episodic"),
                "is_benchmark": is_benchmark,
                "is_protected": auto_protect,
                "agent_context": agent_ctx,
                "is_global": is_global,
            }
        )
        ids.append(mid)

    return ids


def ingest_memories_batch(
    memories: list[dict[str, Any]],
    store: Any,
    embeddings: Any,
    *,
    domain: str = "",
    decompose: bool = True,
    turns_per_chunk: int = 6,
    is_benchmark: bool = False,
) -> tuple[list[int], dict[int, str]]:
    """Batch ingest memories with structure-aware decomposition.

    Returns:
        ids: flat list of all inserted memory IDs
        source_map: {memory_id: source_string} for provenance tracking
    """
    all_ids = []
    source_map: dict[int, str] = {}
    for mem in memories:
        source = mem.get("source", "")
        ids = ingest_memory(
            mem,
            store,
            embeddings,
            domain=domain,
            decompose=decompose,
            turns_per_chunk=turns_per_chunk,
            is_benchmark=is_benchmark,
        )
        for mid in ids:
            source_map[mid] = source
        all_ids.extend(ids)
    return all_ids, source_map
