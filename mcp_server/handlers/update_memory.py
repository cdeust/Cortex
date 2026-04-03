"""Handler: update_memory — edit a memory's content and re-process.

Composition root: wires infrastructure (pg_store, embedding_engine)
to core (knowledge_graph) to update content, re-embed, and refresh
entity links for an existing memory.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.knowledge_graph import extract_entities
from mcp_server.core.write_post_store import persist_entities
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore


_store: MemoryStore | None = None
_emb_engine: EmbeddingEngine | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


def _get_emb_engine() -> EmbeddingEngine:
    global _emb_engine
    if _emb_engine is None:
        _emb_engine = EmbeddingEngine()
    return _emb_engine


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Update a memory's content, re-embed, and refresh entity links.

    Args (via args dict):
        memory_id: int — required.
        content: str — new content for the memory.

    Returns:
        Updated memory summary or error.
    """
    if not args or args.get("memory_id") is None:
        return {"error": "memory_id is required"}
    if not args.get("content"):
        return {"error": "content is required"}

    memory_id = int(args["memory_id"])
    new_content = str(args["content"]).strip()
    if not new_content:
        return {"error": "content cannot be empty"}

    store = _get_store()
    emb_engine = _get_emb_engine()

    existing = store.get_memory(memory_id)
    if existing is None:
        return {"error": "memory_not_found", "memory_id": memory_id}
    if existing.get("is_protected"):
        return {"error": "memory_is_protected", "memory_id": memory_id}

    new_embedding = emb_engine.encode(new_content)
    compression_level = existing.get("compression_level", 0)
    store.update_memory_compression(
        memory_id,
        new_content,
        new_embedding,
        compression_level,
        original_content=existing.get("original_content") or existing["content"],
    )

    domain = existing.get("domain", "")
    extracted = extract_entities(new_content)
    persist_entities(extracted, domain, new_content, store)

    return {
        "updated": True,
        "memory_id": memory_id,
        "content_preview": new_content[:120],
        "entities_extracted": len(extracted),
        "domain": domain,
    }
