"""Compression cycle: compress aging memories along the rate-distortion curve.

Memories progress through levels: full text (0) -> gist (1) -> tag (2).
Protected and semantic memories are skipped.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.compression import (
    extract_gist,
    generate_tag,
    get_compression_schedule,
)
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def run_compression_cycle(
    store: MemoryStore,
    settings: Any,
    embeddings: EmbeddingEngine,
    memories: list[dict] | None = None,
) -> dict:
    """Compress aging memories along the rate-distortion curve.

    `memories` may be pre-loaded by the consolidate handler (issue #13).
    """
    if memories is None:
        memories = store.get_all_memories_for_decay()

    stats = {
        "compressed_to_gist": 0,
        "compressed_to_tag": 0,
        "protected_skipped": 0,
        "semantic_skipped": 0,
        "rows_scanned": len(memories),
    }

    for mem in memories:
        if mem.get("is_protected"):
            stats["protected_skipped"] += 1
            continue
        if mem.get("store_type") == "semantic":
            stats["semantic_skipped"] += 1
            continue

        _compress_memory(store, settings, embeddings, mem, stats)

    return stats


def _compress_memory(
    store: MemoryStore,
    settings: Any,
    embeddings: EmbeddingEngine,
    mem: dict,
    stats: dict,
) -> None:
    """Compress a single memory to the target level."""
    current_level = mem.get("compression_level", 0)
    target_level = get_compression_schedule(
        mem,
        gist_age_hours=settings.COMPRESSION_GIST_AGE_HOURS,
        tag_age_hours=settings.COMPRESSION_TAG_AGE_HOURS,
    )

    if target_level <= current_level:
        return

    try:
        if target_level >= 1 and current_level == 0:
            _compress_full_to_gist(store, embeddings, mem, stats)
            if target_level >= 2:
                _compress_to_tag_from_gist(store, embeddings, mem, stats)
        elif target_level >= 2 and current_level == 1:
            _compress_gist_to_tag(store, embeddings, mem, stats)
    except Exception:
        logger.exception("Failed to compress memory %d", mem["id"])


def _compress_full_to_gist(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    mem: dict,
    stats: dict,
) -> None:
    """Compress from full text (level 0) to gist (level 1)."""
    original = mem["content"]
    gist = extract_gist(original)
    new_emb = embeddings.encode(gist)

    store.insert_archive(
        {
            "original_memory_id": mem["id"],
            "content": original,
            "embedding": mem.get("embedding"),
            "archive_reason": "compression_gist",
        }
    )
    store.update_memory_compression(
        mem["id"],
        gist,
        new_emb,
        1,
        original_content=original,
    )
    stats["compressed_to_gist"] += 1


def _compress_to_tag_from_gist(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    mem: dict,
    stats: dict,
) -> None:
    """Continue compression from freshly created gist to tag (level 2)."""
    gist = extract_gist(mem["content"])
    tag = generate_tag(gist, mem)
    tag_emb = embeddings.encode(tag)

    store.insert_archive(
        {
            "original_memory_id": mem["id"],
            "content": gist,
            "embedding": embeddings.encode(gist),
            "archive_reason": "compression_tag",
        }
    )
    store.update_memory_compression(mem["id"], tag, tag_emb, 2)
    stats["compressed_to_tag"] += 1


def _compress_gist_to_tag(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    mem: dict,
    stats: dict,
) -> None:
    """Compress from gist (level 1) to tag (level 2)."""
    tag = generate_tag(mem["content"], mem)
    tag_emb = embeddings.encode(tag)

    store.insert_archive(
        {
            "original_memory_id": mem["id"],
            "content": mem["content"],
            "embedding": mem.get("embedding"),
            "archive_reason": "compression_tag",
        }
    )
    store.update_memory_compression(mem["id"], tag, tag_emb, 2)
    stats["compressed_to_tag"] += 1
