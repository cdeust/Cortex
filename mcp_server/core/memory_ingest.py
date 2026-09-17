"""Memory ingestion: decompose, extract entities, store.

source: ADR-0200"""

from __future__ import annotations

from typing import Any

from mcp_server.core.memory_decomposer import (
    build_entity_summary,
    decompose_memory,
)
from mcp_server.observability import silent_failure
from mcp_server.core import knowledge_graph, write_post_store
from mcp_server.core.team_scope import is_team_decision


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
        if entities.get("has_instruction"):
            tags.append("instruction")
        if entities.get("has_decision"):
            tags.append("decision")
        if entities.get("has_activity"):
            tags.append("activity")

        # source: ADR-0200

        is_decision = entities.get("has_decision", False)
        auto_protect = is_decision and not is_benchmark
        # source: ADR-0200

        importance_boost = 1.5 if is_decision else 1.0

        # source: ADR-0200

        agent_ctx = memory.get("agent_context", "")
        team_decision = not is_benchmark and is_team_decision(
            chunk_content,
            memory.get("capture_origin", "unknown"),
            memory.get("write_class", "deliberate"),
            agent_ctx,
        )

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
                "is_global": memory.get("is_global", False),
                "is_team_decision": team_decision,  # source: ADR-1083
                "directory_context": memory.get("directory_context", ""),
                "write_class": memory.get("write_class", "deliberate"),
                # source: ADR-0200
                "capture_origin": memory.get("capture_origin", "unknown"),
            }
        )
        ids.append(mid)
        # source: ADR-0200

        try:
            extracted = knowledge_graph.extract_entities(chunk_content)
            write_post_store.persist_entities(extracted, domain, chunk_content, store)
        except Exception as exc:  # noqa: BLE001 — source: ADR-0200
            # source: ADR-0200

            silent_failure.note("memory_ingest.entity_extraction", exc)

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
