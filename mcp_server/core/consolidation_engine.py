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

from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.dual_store_cls import classify_memory
from mcp_server.core.dual_store_cls_abstraction import (
    abstract_to_schema,
    check_consistency,
    cluster_by_similarity,
    filter_recurring_patterns,
)
from mcp_server.core.stress_modulation import consolidation_gain
from mcp_server.core.source_monitoring import promotion_confabulation_risk
from datetime import datetime, timezone

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


def stress_scaled_min_occurrences(base_min_occurrences: int, stress: float) -> int:
    """Scale the pattern-recurrence threshold by the D1 session-stress gain.

    Stress-hormone modulation (D1) scales how strongly/broadly the offline pass
    consolidates along an inverted-U (Roozendaal & McGaugh 2011; McGaugh 2000):
    moderate session stress ENHANCES consolidation, extreme stress IMPAIRS it.
    Here "consolidation scope" is the recurrence bar a pattern must clear to be
    abstracted into a semantic memory: dividing it by the gain means

      - moderate stress (gain > 1) => LOWER effective threshold => more patterns
        qualify => broader/stronger consolidation (the enhancement lobe);
      - extreme stress (gain < 1) => HIGHER effective threshold => fewer patterns
        qualify => weaker consolidation (the impairment lobe);
      - neutral stress OR ablated (gain == 1.0) => threshold UNCHANGED — exact
        identity, so existing callers that pass no stress are unaffected.

    The gain's own ablation guard (CORTEX_ABLATE_STRESS_MODULATION=1 forces gain
    1.0) therefore flows through to a no-op here. The result is floored at 1 (a
    pattern always needs at least one occurrence).

    This is a DESIGN INFERENCE — a deterministic one-parameter modulation of the
    consolidation scope, not a validated glucocorticoid model; see
    stress_modulation.py's honesty note.
    """

    gain = consolidation_gain(stress)
    if gain == 1.0:
        return base_min_occurrences
    scaled = round(base_min_occurrences / gain)
    return max(1, int(scaled))


def plan_cls_consolidation(
    episodic_memories: list[dict[str, Any]],
    existing_semantics: list[dict[str, Any]],
    similarity_fn,
    cluster_threshold: float = 0.6,
    dedup_threshold: float = 0.85,
    min_occurrences: int = 3,
    min_sessions: int = 2,
    session_stress: float = 0.0,
) -> dict[str, Any]:
    """Plan CLS consolidation actions without executing I/O.

    Returns a plan dict:
      - new_semantics: list of {schema, source_memory_ids, tags}
      - skipped_inconsistent: count
      - skipped_duplicate: count
      - patterns_found: count
      - consolidation_gain: the D1 stress gain applied (1.0 = unmodulated)
      - effective_min_occurrences: the recurrence bar actually used

    D1 stress-hormone modulation. ``session_stress`` (a scalar in [0, 1] from
    ``stress_modulation.compute_session_stress`` / ``assess_session_stress``)
    scales the consolidation SCOPE along the inverted-U: it modulates the
    effective ``min_occurrences`` via ``stress_scaled_min_occurrences``. The
    default ``session_stress=0.0`` yields gain 1.0 and leaves ``min_occurrences``
    unchanged — behavior-preserving identity for every existing caller. When
    Mechanism.STRESS_MODULATION is ablated the gain is forced to 1.0, so this is
    likewise a no-op.
    """

    gain = consolidation_gain(session_stress)
    effective_min_occurrences = stress_scaled_min_occurrences(
        min_occurrences, session_stress
    )

    clusters = cluster_by_similarity(
        episodic_memories, similarity_fn, threshold=cluster_threshold
    )
    patterns = filter_recurring_patterns(
        clusters,
        min_occurrences=effective_min_occurrences,
        min_sessions=min_sessions,
    )

    plan = _process_patterns(
        patterns, existing_semantics, similarity_fn, dedup_threshold
    )
    plan["consolidation_gain"] = gain
    plan["effective_min_occurrences"] = effective_min_occurrences
    return plan


def _try_abstract_pattern(
    pattern: dict,
    existing_semantics: list[dict[str, Any]],
    similarity_fn,
    dedup_threshold: float,
) -> dict | None:
    """Try to abstract a single pattern into a semantic entry. Returns None if skipped.

    C1 read-side enforcement (source/reality monitoring). Before returning the
    abstraction, the confabulation gate
    (``source_monitoring.promotion_confabulation_risk``) checks whether the
    cluster being crystallized into a semantic FACT is internally generated
    (INFERRED) with zero perceptual grounding — Johnson & Raye's (1981)
    reality-monitoring failure, a confabulation being promoted to knowledge. The
    result carries a ``confabulation_risk`` boolean so the caller (and the
    downstream semantic-memory writer) can flag it. This is NON-FATAL and
    behavior-preserving: a flagged cluster is STILL abstracted and STILL
    eligible for promotion; the gate annotates, it does not drop. When
    ``Mechanism.CONFABULATION_GATE`` is ablated
    (``CORTEX_ABLATE_CONFABULATION_GATE=1``) the check is skipped and the flag is
    left False — identical set of returned abstractions either way.
    """
    cluster_mems = pattern["memories"]
    schema = abstract_to_schema(cluster_mems)
    if not schema:
        return None
    if _is_duplicate_schema(
        cluster_mems, existing_semantics, similarity_fn, dedup_threshold
    ):
        return None
    confabulation_risk = False
    if not is_mechanism_disabled(Mechanism.CONFABULATION_GATE):
        confabulation_risk = promotion_confabulation_risk(cluster_mems)
    return {
        "schema": schema,
        "source_memory_ids": pattern["memory_ids"],
        "tags": _collect_common_tags(cluster_mems),
        "count": pattern["count"],
        "session_count": pattern["session_count"],
        "confabulation_risk": confabulation_risk,
    }


def _process_patterns(
    patterns: list[dict],
    existing_semantics: list[dict[str, Any]],
    similarity_fn,
    dedup_threshold: float,
) -> dict[str, Any]:
    """Process filtered patterns into semantic consolidation actions.

    ``confabulation_risk_promotions`` counts the abstractions the C1 gate flagged
    as a confabulation being crystallized as a semantic fact (INFERRED cluster,
    zero perceptual grounding). These are STILL promoted (non-fatal flag), so the
    count is an audit signal, not a drop count; it is 0 when the gate is ablated.
    """
    new_semantics: list[dict] = []
    skipped_inconsistent = 0
    skipped_duplicate = 0
    confabulation_risk_promotions = 0

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
            if result.get("confabulation_risk"):
                confabulation_risk_promotions += 1
            new_semantics.append(result)

    return {
        "new_semantics": new_semantics,
        "patterns_found": len(patterns),
        "skipped_inconsistent": skipped_inconsistent,
        "skipped_duplicate": skipped_duplicate,
        "confabulation_risk_promotions": confabulation_risk_promotions,
    }


# ── Duplicate Detection ──────────────────────────────────────────────────


def _parse_created_at(memory: dict[str, Any]) -> float:
    """Return created_at as a UTC timestamp float, or 0.0 if unparseable.

    Precondition: memory is a dict optionally containing 'created_at' as
    an ISO string or datetime.
    Postcondition: returns a non-negative float (unix timestamp); 0.0 means
    the timestamp was absent or unparseable.
    """

    raw = memory.get("created_at")
    if raw is None:
        return 0.0
    if isinstance(raw, datetime):
        dt = raw if raw.tzinfo is not None else raw.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError):
            return 0.0
    return 0.0


def find_near_duplicates(
    memories: list[dict[str, Any]],
    similarity_fn,
    threshold: float = 0.95,
) -> list[tuple[int, int]]:
    """Find pairs of near-duplicate memories.

    Returns list of (keep_id, remove_id) pairs.

    Tie-break policy — prefer the MORE RECENT memory (higher created_at),
    falling back to higher heat only when timestamps are equal or both absent.

    Rationale: a fresh correction of a stale fact has low heat (just stored)
    but a newer created_at.  The old stale duplicate has high heat from
    prior accesses.  Keeping by heat would discard the correction.
    Keeping by recency ensures the supersession is respected.

    Precondition: each element of `memories` has an 'id' key.
    Postcondition: (keep_id, remove_id) — keep_id is the more-recent memory.
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
                # Prefer the newer memory (higher created_at timestamp).
                # Fall back to heat only when timestamps are identical / absent.
                ts_i = _parse_created_at(memories[i])
                ts_j = _parse_created_at(memories[j])
                if ts_i != ts_j:
                    keep_newer = i if ts_i > ts_j else j
                    drop_older = j if ts_i > ts_j else i
                else:
                    # Timestamps equal or both absent: fall back to heat.
                    heat_i = memories[i].get("heat", 0)
                    heat_j = memories[j].get("heat", 0)
                    keep_newer = i if heat_i >= heat_j else j
                    drop_older = j if heat_i >= heat_j else i
                duplicates.append(
                    (memories[keep_newer]["id"], memories[drop_older]["id"])
                )
                seen.add(drop_older)
                # If the anchor (i) was dropped, it cannot win any further
                # comparisons — stop the inner loop.
                if drop_older == i:
                    break

    return duplicates


# ── Action Log Summarization ─────────────────────────────────────────────


# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MAX_FILES_IN_SUMMARY = 5  # summary lists this many files, then a count


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
        file_list = ", ".join(sorted(files_touched)[:_MAX_FILES_IN_SUMMARY])
        if len(files_touched) > _MAX_FILES_IN_SUMMARY:
            file_list += f" (+{len(files_touched) - _MAX_FILES_IN_SUMMARY} more)"
        summary += f". Files: {file_list}"

    return summary


# ── Entity Classification Enhancement ────────────────────────────────────


# source: graduation conditions documented in the should_reclassify
# docstring ("Accessed >= 5 times", ">= 3 related semantic memories");  # noqa: ERA001
# tuning provenance not recorded
_MIN_ACCESSES_FOR_SEMANTIC = 5
_MIN_RELATED_SEMANTICS = 3


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

    return (
        access_count >= _MIN_ACCESSES_FOR_SEMANTIC
        or related_semantics >= _MIN_RELATED_SEMANTICS
    )
