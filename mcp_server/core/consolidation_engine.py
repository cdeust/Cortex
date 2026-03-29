"""Consolidation engine — episodic-to-semantic distillation orchestration.

Orchestrates the full consolidation cycle:
  1. Pattern detection in episodic memories (Go-CLS clustering)
  2. Consistency checking (contradiction detection)
  3. Schema abstraction (generalized knowledge extraction)
  4. Duplicate detection (avoid redundant semantics)

Pure business logic — receives data, returns actions to take.
The caller (handler/infrastructure) executes the I/O.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.dual_store_cls import classify_memory
from mcp_server.core.dual_store_cls_abstraction import (
    abstract_to_schema,
    check_consistency,
    cluster_by_similarity,
    filter_recurring_patterns,
)

# ── Consolidation Actions ─────────────────────────────────────────────────


def _is_duplicate_schema(
    cluster_mems: list[dict[str, Any]],
    existing_semantics: list[dict[str, Any]],
    similarity_fn,
    dedup_threshold: float,
) -> bool:
    """Check if a cluster's schema duplicates an existing semantic memory."""
    cluster_embedding = cluster_mems[0].get("embedding")
    for existing in existing_semantics:
        if (
            existing.get("content", "")
            and similarity_fn(existing.get("embedding"), cluster_embedding)
            > dedup_threshold
        ):
            return True
    return False


def _collect_common_tags(cluster_mems: list[dict[str, Any]]) -> list[str]:
    """Extract tags appearing in at least half of the cluster memories."""
    all_tags: dict[str, int] = {}
    for mem in cluster_mems:
        for tag in mem.get("tags", []):
            if isinstance(tag, str):
                all_tags[tag] = all_tags.get(tag, 0) + 1
    n = len(cluster_mems)
    common = [t for t, c in all_tags.items() if c >= max(1, n * 0.5)]
    return list(set(["semantic", "auto-abstracted"] + common))


def plan_cls_consolidation(
    episodic_memories: list[dict[str, Any]],
    existing_semantics: list[dict[str, Any]],
    similarity_fn,
    cluster_threshold: float = 0.6,
    dedup_threshold: float = 0.85,
    min_occurrences: int = 3,
    min_sessions: int = 2,
) -> dict[str, Any]:
    """Plan CLS consolidation actions without executing I/O.

    Returns a plan dict:
      - new_semantics: list of {schema, source_memory_ids, tags}
      - skipped_inconsistent: count
      - skipped_duplicate: count
      - patterns_found: count
    """
    clusters = cluster_by_similarity(
        episodic_memories, similarity_fn, threshold=cluster_threshold
    )
    patterns = filter_recurring_patterns(
        clusters, min_occurrences=min_occurrences, min_sessions=min_sessions
    )

    return _process_patterns(
        patterns, existing_semantics, similarity_fn, dedup_threshold
    )


def _try_abstract_pattern(
    pattern: dict,
    existing_semantics: list[dict[str, Any]],
    similarity_fn,
    dedup_threshold: float,
) -> dict | None:
    """Try to abstract a single pattern into a semantic entry. Returns None if skipped."""
    cluster_mems = pattern["memories"]
    schema = abstract_to_schema(cluster_mems)
    if not schema:
        return None
    if _is_duplicate_schema(
        cluster_mems, existing_semantics, similarity_fn, dedup_threshold
    ):
        return None
    return {
        "schema": schema,
        "source_memory_ids": pattern["memory_ids"],
        "tags": _collect_common_tags(cluster_mems),
        "count": pattern["count"],
        "session_count": pattern["session_count"],
    }


def _process_patterns(
    patterns: list[dict],
    existing_semantics: list[dict[str, Any]],
    similarity_fn,
    dedup_threshold: float,
) -> dict[str, Any]:
    """Process filtered patterns into semantic consolidation actions."""
    new_semantics: list[dict] = []
    skipped_inconsistent = 0
    skipped_duplicate = 0

    for pattern in patterns:
        if not check_consistency(pattern["memories"])["consistent"]:
            skipped_inconsistent += 1
            continue
        result = _try_abstract_pattern(
            pattern, existing_semantics, similarity_fn, dedup_threshold
        )
        if result is None:
            skipped_duplicate += 1
        else:
            new_semantics.append(result)

    return {
        "new_semantics": new_semantics,
        "patterns_found": len(patterns),
        "skipped_inconsistent": skipped_inconsistent,
        "skipped_duplicate": skipped_duplicate,
    }


# ── Duplicate Detection ──────────────────────────────────────────────────


def find_near_duplicates(
    memories: list[dict[str, Any]],
    similarity_fn,
    threshold: float = 0.95,
) -> list[tuple[int, int]]:
    """Find pairs of near-duplicate memories.

    Returns list of (keep_id, remove_id) pairs.
    The memory with higher heat is kept.
    """
    duplicates: list[tuple[int, int]] = []
    seen: set[int] = set()

    for i in range(len(memories)):
        if i in seen:
            continue
        for j in range(i + 1, len(memories)):
            if j in seen:
                continue
            emb_a = memories[i].get("embedding")
            emb_b = memories[j].get("embedding")
            if emb_a is None or emb_b is None:
                continue
            if similarity_fn(emb_a, emb_b) >= threshold:
                # Keep the one with higher heat
                heat_i = memories[i].get("heat", 0)
                heat_j = memories[j].get("heat", 0)
                if heat_i >= heat_j:
                    duplicates.append((memories[i]["id"], memories[j]["id"]))
                else:
                    duplicates.append((memories[j]["id"], memories[i]["id"]))
                seen.add(j)

    return duplicates


# ── Action Log Summarization ─────────────────────────────────────────────


def summarize_action_group(
    actions: list[dict[str, Any]],
    min_actions: int = 3,
) -> str | None:
    """Summarize a group of related actions into a single memory.

    Returns summary text or None if group is too small.
    """
    if len(actions) < min_actions:
        return None

    # Group by type
    type_counts: dict[str, int] = {}
    files_touched: set[str] = set()

    for action in actions:
        action_type = action.get("type", "unknown")
        type_counts[action_type] = type_counts.get(action_type, 0) + 1
        if action.get("file"):
            files_touched.add(action["file"])

    parts = []
    for atype, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        parts.append(f"{count}x {atype}")

    summary = f"Session activity: {', '.join(parts)}"
    if files_touched:
        file_list = ", ".join(sorted(files_touched)[:5])
        if len(files_touched) > 5:
            file_list += f" (+{len(files_touched) - 5} more)"
        summary += f". Files: {file_list}"

    return summary


# ── Entity Classification Enhancement ────────────────────────────────────


def should_reclassify(
    memory: dict[str, Any],
    access_count: int = 0,
    related_semantics: int = 0,
) -> bool:
    """Determine if an episodic memory should be reclassified as semantic.

    An episodic memory graduates to semantic when:
      - Accessed >= 5 times (frequent retrieval)
      - Or there are >= 3 related semantic memories (integration pressure)
      - And it's already classified as semantic by content analysis
    """
    if memory.get("store_type") == "semantic":
        return False

    content = memory.get("content", "")
    tags = memory.get("tags", [])
    if isinstance(tags, str):
        tags = tags.split(",")

    content_class = classify_memory(content, tags)
    if content_class != "semantic":
        return False

    return access_count >= 5 or related_semantics >= 3
