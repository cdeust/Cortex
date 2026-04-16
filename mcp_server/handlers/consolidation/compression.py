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
            # Preconditions:
            #   - mem["content"] is the original full text.
            #   - current_level == 0.
            # Postconditions (if target_level == 1): memory written at level 1;
            #   exactly 1 encode() call.
            # Postconditions (if target_level >= 2): memory written at level 2;
            #   archive row at level-1 (gist) reuses the gist embedding already
            #   computed — no redundant re-encode. Exactly 2 encode() calls
            #   (one for the gist, one for the tag).
            gist, gist_emb = _compress_full_to_gist(store, embeddings, mem, stats)
            if target_level >= 2:
                _compress_to_tag_from_gist(
                    store, embeddings, mem, stats, gist=gist, gist_emb=gist_emb
                )
        elif target_level >= 2 and current_level == 1:
            _compress_gist_to_tag(store, embeddings, mem, stats)
    except Exception:
        logger.exception("Failed to compress memory %d", mem["id"])


def _compress_full_to_gist(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    mem: dict,
    stats: dict,
) -> tuple[str, list[float]]:
    """Compress from full text (level 0) to gist (level 1).

    Returns the freshly computed ``(gist, gist_embedding)`` so a caller
    advancing straight to level 2 can reuse them instead of re-encoding
    (see ``_compress_to_tag_from_gist``).
    """
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
    return gist, new_emb


def _compress_to_tag_from_gist(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    mem: dict,
    stats: dict,
    *,
    gist: str | None = None,
    gist_emb: list[float] | None = None,
) -> None:
    """Continue compression from a freshly created gist to tag (level 2).

    Precondition: either both ``gist`` and ``gist_emb`` are supplied by the
    caller (threaded through from ``_compress_full_to_gist`` — fast path),
    or neither is supplied (legacy path; we recompute the gist and encode it
    for the archive row).

    Postcondition — fast path: exactly **one** ``embeddings.encode()`` call
    is made here (the one for the tag). The gist embedding is reused for
    the archive row rather than being recomputed, eliminating the redundant
    encode on the 0→2 transition (was 3 encodes total → now 2).

    Postcondition — legacy path: behaviour is identical to the pre-change
    implementation (two encodes: one for the gist archive, one for the tag).
    """
    if gist is None or gist_emb is None:
        gist = extract_gist(mem["content"])
        gist_emb = embeddings.encode(gist)

    tag = generate_tag(gist, mem)
    tag_emb = embeddings.encode(tag)

    store.insert_archive(
        {
            "original_memory_id": mem["id"],
            "content": gist,
            "embedding": gist_emb,
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
