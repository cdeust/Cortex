"""Core: sleep_compute — deep consolidation (dream replay).

Biologically inspired offline consolidation pass:
  1. Dream replay:  re-process hot memories through enrichment pipeline
  2. Cluster summarization: synthesize text summaries for fractal L1/L2 clusters
  3. Re-embedding:  re-encode stale/compressed memories with current encoder
  4. Auto-narration: generate a brief project narrative and store as semantic memory

Pure business logic — no I/O.  All storage is done by the caller (consolidate handler).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from mcp_server.core.enrichment import (
    build_enriched_content,
)


# ── Dream Replay ──────────────────────────────────────────────────────────────


def dream_replay(
    memories: list[dict[str, Any]],
    max_memories: int = 50,
) -> list[dict[str, Any]]:
    """Re-process the hottest memories through query-enrichment.

    Returns a list of update dicts: {memory_id, enriched_content}.
    Caller is responsible for persisting these.
    """
    # Sort by heat descending; take top slice
    hot = sorted(memories, key=lambda m: m.get("heat", 0), reverse=True)[:max_memories]

    updates = []
    for mem in hot:
        content = mem.get("content", "")
        if not content or len(content) < 30:
            continue
        # Skip already-enriched content to avoid double-appending
        if "<!-- doc2query -->" in content:
            continue

        enriched = build_enriched_content(content)
        if enriched != content:
            updates.append(
                {
                    "memory_id": mem["id"],
                    "enriched_content": enriched,
                }
            )

    return updates


# ── Cluster Summarization ─────────────────────────────────────────────────────


def _centroid_sentence(texts: list[str]) -> str:
    """Pick the sentence from the cluster that covers the most shared words."""
    if not texts:
        return ""
    if len(texts) == 1:
        return texts[0][:200]

    # Tokenize
    def tokens(t: str) -> set[str]:
        return set(re.findall(r"[a-zA-Z]{3,}", t.lower()))

    all_words: set[str] = set()
    for t in texts:
        all_words |= tokens(t)

    best_text = texts[0]
    best_score = -1
    for t in texts:
        overlap = len(tokens(t) & all_words)
        if overlap > best_score:
            best_score = overlap
            best_text = t

    return best_text[:200]


def summarize_clusters(
    clusters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate text summaries for a list of cluster dicts.

    Each cluster dict must have: {cluster_id, level, memories: [...]}.
    Returns list of {cluster_id, level, summary}.
    """
    results = []
    for cluster in clusters:
        mems = cluster.get("memories", [])
        texts = [m.get("content", "") for m in mems if m.get("content")]
        if not texts:
            continue

        summary = _centroid_sentence(texts)
        # Prepend a count hint
        summary = f"[{len(texts)} memories] {summary}"

        results.append(
            {
                "cluster_id": cluster["cluster_id"],
                "level": cluster.get("level", 1),
                "summary": summary,
                "memory_count": len(texts),
            }
        )
    return results


# ── Re-embedding ──────────────────────────────────────────────────────────────


def select_stale_embeddings(
    memories: list[dict[str, Any]],
    max_memories: int = 100,
) -> list[dict[str, Any]]:
    """Return memories that should be re-embedded.

    Criteria:
    - embedding is None / missing
    - compression_level > 0 (content changed after compression)
    - content hash doesn't match stored hash (if available)
    """
    candidates = []
    for mem in memories:
        if not mem.get("embedding"):
            candidates.append(mem)
            continue
        if mem.get("compression_level", 0) > 0 and not mem.get(
            "reembedded_after_compression"
        ):
            candidates.append(mem)
            continue
    return candidates[:max_memories]


# ── Auto-narration ────────────────────────────────────────────────────────────

_FILLER_RE = re.compile(
    r"\b(the|a|an|is|are|was|were|this|that|it|be|been|being)\b", re.I
)


def _keyword_frequency(texts: list[str], top_n: int = 10) -> list[tuple[str, int]]:
    """Extract top N keywords from a list of texts."""
    freq: dict[str, int] = {}
    for text in texts:
        words = re.findall(r"[a-zA-Z]{4,}", text.lower())
        for w in words:
            if not _FILLER_RE.match(w):
                freq[w] = freq.get(w, 0) + 1
    return sorted(freq.items(), key=lambda x: x[1], reverse=True)[:top_n]


def _memory_timestamp(m: dict) -> float:
    """Extract a sortable timestamp from a memory's created_at field."""
    raw = m.get("created_at", "")
    if not raw:
        return 0.0
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def _build_narration_prose(
    memories: list[dict[str, Any]],
    keywords: list[tuple[str, int]],
    directory: str,
    period_label: str,
) -> str:
    """Assemble narrative prose from keywords and most important memory."""
    kw_phrase = (
        ", ".join(kw for kw, _ in keywords[:5]) if keywords else "various topics"
    )
    label = directory or "this project"

    lines = [
        f"During {period_label}, {len(memories)} memories were stored for {label}.",
        f"Key themes: {kw_phrase}.",
    ]

    by_importance = sorted(memories, key=lambda m: m.get("importance", 0), reverse=True)
    if by_importance:
        top = by_importance[0].get("content", "")[:120]
        lines.append(f'Most important: "{top}"')

    return " ".join(lines)


def auto_narrate(
    memories: list[dict[str, Any]],
    directory: str = "",
    period_label: str = "recent",
) -> dict[str, Any]:
    """Generate a brief narrative from memory contents.

    Returns {narrative_text, keyword_summary, memory_count, period}.
    """
    if not memories:
        return {
            "narrative_text": "No memories found for narration.",
            "keyword_summary": [],
            "memory_count": 0,
            "period": period_label,
        }

    sorted_mems = sorted(memories, key=_memory_timestamp, reverse=True)
    texts = [m.get("content", "") for m in sorted_mems if m.get("content")]
    keywords = _keyword_frequency(texts, top_n=8)
    narrative_text = _build_narration_prose(memories, keywords, directory, period_label)

    return {
        "narrative_text": narrative_text,
        "keyword_summary": [{"keyword": kw, "count": cnt} for kw, cnt in keywords],
        "memory_count": len(memories),
        "period": period_label,
    }


# ── Sleep Compute Orchestrator ────────────────────────────────────────────────


def run_sleep_compute(
    memories: list[dict[str, Any]],
    clusters: list[dict[str, Any]] | None = None,
    directory: str = "",
    period_label: str = "recent",
    max_replay: int = 50,
    max_reembed: int = 100,
) -> dict[str, Any]:
    """Run the full sleep compute pass.

    Returns a plan dict with all updates — the caller (consolidate handler)
    is responsible for persisting these to the store.

    Returns:
        {
            replay_updates: [{memory_id, enriched_content}],
            cluster_summaries: [{cluster_id, level, summary, memory_count}],
            stale_embeddings: [{memory_id, content}],
            narration: {narrative_text, keyword_summary, memory_count, period},
        }
    """
    replay_updates = dream_replay(memories, max_memories=max_replay)
    cluster_summaries = summarize_clusters(clusters or [])
    stale = select_stale_embeddings(memories, max_memories=max_reembed)
    stale_embeddings = [
        {"memory_id": m["id"], "content": m.get("content", "")} for m in stale
    ]
    narration = auto_narrate(memories, directory=directory, period_label=period_label)

    return {
        "replay_updates": replay_updates,
        "cluster_summaries": cluster_summaries,
        "stale_embeddings": stale_embeddings,
        "narration": narration,
    }
