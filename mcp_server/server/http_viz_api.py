"""HTTP API handlers for entity detail and memory editing.

Thin wiring layer called by the viz server's HTTP handler.
Imports from handlers layer for actual business logic orchestration.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler


def parse_single_param(path: str, key: str) -> str | None:
    """Extract a single query parameter value from a URL path."""
    if "?" not in path:
        return None
    params = path.split("?", 1)[1]
    for p in params.split("&"):
        if p.startswith(key + "="):
            return p[len(key) + 1:]
    return None


def read_json_body(handler: BaseHTTPRequestHandler) -> dict | None:
    """Read and parse a JSON body from an HTTP request."""
    try:
        length = int(handler.headers.get("Content-Length", 0))
        if length <= 0:
            return None
        raw = handler.rfile.read(length)
        return json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None


def handle_entity_detail(store_getter, entity_id: int) -> dict:
    """Serve the entity detail API by wiring store to core."""
    from mcp_server.core.entity_profile import build_entity_profile

    store = store_getter()
    entity = store.get_entity_by_id(entity_id)
    if entity is None:
        return {"error": "entity_not_found", "entity_id": entity_id}

    entity_name = entity.get("name", "")
    memories = store.get_memories_mentioning_entity(entity_name, limit=50)
    relationships = store.get_relationships_for_entity(entity_id, direction="both")
    return {"entity": build_entity_profile(entity, memories, relationships)}


def handle_update_memory(store_getter, body: dict) -> dict:
    """Serve the update memory API by wiring store + embedding to core."""
    from mcp_server.core.knowledge_graph import extract_entities
    from mcp_server.core.write_post_store import persist_entities
    from mcp_server.infrastructure.embedding_engine import EmbeddingEngine

    memory_id = body.get("memory_id")
    content = body.get("content", "").strip()
    if memory_id is None:
        return {"error": "memory_id is required"}
    if not content:
        return {"error": "content is required"}

    store = store_getter()
    memory_id = int(memory_id)
    existing = store.get_memory(memory_id)
    if existing is None:
        return {"error": "memory_not_found", "memory_id": memory_id}
    if existing.get("is_protected"):
        return {"error": "memory_is_protected", "memory_id": memory_id}

    emb_engine = EmbeddingEngine()
    new_embedding = emb_engine.encode(content)
    store.update_memory_compression(
        memory_id,
        content,
        new_embedding,
        existing.get("compression_level", 0),
        original_content=existing.get("original_content") or existing["content"],
    )

    domain = existing.get("domain", "")
    extracted = extract_entities(content)
    persist_entities(extracted, domain, content, store)

    return {
        "updated": True,
        "memory_id": memory_id,
        "content_preview": content[:120],
        "entities_extracted": len(extracted),
    }
