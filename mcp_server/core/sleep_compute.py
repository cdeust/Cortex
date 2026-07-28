"""Core: sleep_compute — deep consolidation (dream replay).

Biologically inspired offline consolidation pass:
  1. Dream replay:  re-process hot memories through enrichment pipeline
  2. Cluster summarization: synthesize text summaries for fractal L1/L2 clusters
  3. Re-embedding:  re-encode stale/compressed memories with current encoder
  4. Auto-narration: generate a brief project narrative and store as semantic memory

Pure business logic — no I/O.  All storage is done by the caller (consolidate handler).
"""

from __future__ import annotations

import heapq
import re
from typing import Any, Iterable

from mcp_server.core.enrichment import (
    build_enriched_content,
)
from mcp_server.core.targeted_reactivation import cue_match_score

# ── Dream Replay ──────────────────────────────────────────────────────────────


# Content shorter than this many characters is skipped by dream replay
# enrichment.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_ENRICHABLE_CONTENT_CHARS = 30


def _replay_updates_for(
    hottest: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enrich an already-selected set of hottest memories.

    Returns update dicts ``{memory_id, enriched_content}``. The hottest set is
    chosen by the streaming heap in ``run_sleep_compute_streamed`` (bounded),
    so this only ever processes ``max_replay`` items.
    """
    updates = []
    for mem in hottest:
        content = mem.get("content", "")
        if not content or len(content) < _MIN_ENRICHABLE_CONTENT_CHARS:
            continue
        # Skip already-enriched content to avoid double-appending.
        if "<!-- doc2query -->" in content:
            continue
        enriched = build_enriched_content(content)
        if enriched != content:
            updates.append({"memory_id": mem["id"], "enriched_content": enriched})
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


# ── Auto-narration (streaming accumulators) ───────────────────────────────────

_FILLER_RE = re.compile(
    r"\b(the|a|an|is|are|was|were|this|that|it|be|been|being)\b", re.I
)


def _accumulate_keywords(freq: dict[str, int], text: str) -> None:
    """Fold one memory's keywords into a running frequency dict (bounded vocab).

    O(words-in-text) work, O(vocabulary) memory — independent of corpus size,
    so it composes into the single streaming pass.
    """
    for w in re.findall(r"[a-zA-Z]{4,}", text.lower()):
        if not _FILLER_RE.match(w):
            freq[w] = freq.get(w, 0) + 1


def _narration_from_accumulators(
    freq: dict[str, int],
    top_importance: dict[str, Any] | None,
    count: int,
    directory: str,
    period_label: str,
) -> dict[str, Any]:
    """Build the narration dict from the streaming pass's accumulators."""
    if count == 0:
        return {
            "narrative_text": "No memories found for narration.",
            "keyword_summary": [],
            "memory_count": 0,
            "period": period_label,
        }
    keywords = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:8]
    kw_phrase = (
        ", ".join(kw for kw, _ in keywords[:5]) if keywords else "various topics"
    )
    label = directory or "this project"
    lines = [
        f"During {period_label}, {count} memories were stored for {label}.",
        f"Key themes: {kw_phrase}.",
    ]
    if top_importance is not None:
        lines.append(f'Most important: "{top_importance.get("content", "")[:120]}"')
    return {
        "narrative_text": " ".join(lines),
        "keyword_summary": [{"keyword": kw, "count": cnt} for kw, cnt in keywords],
        "memory_count": count,
        "period": period_label,
    }


# ── Sleep Compute Orchestrator ────────────────────────────────────────────────


def _is_stale_embedding(mem: dict[str, Any]) -> bool:
    """Whether a memory needs re-embedding (mirrors select_stale_embeddings)."""
    if not mem.get("embedding"):
        return True
    return mem.get("compression_level", 0) > 0 and not mem.get(
        "reembedded_after_compression"
    )


def run_sleep_compute_streamed(
    memory_chunks: Iterable[list[dict[str, Any]]],
    clusters: list[dict[str, Any]] | None = None,
    directory: str = "",
    period_label: str = "recent",
    max_replay: int = 50,
    max_reembed: int = 100,
    cue: str | None = None,
    cue_boost: float = 1.0,
) -> dict[str, Any]:
    """Single-pass, constant-memory sleep compute over chunked memories.

    Every full-list scan in the legacy pass is a BOUNDED reduction, so the
    whole computation needs only O(max_replay + max_reembed + vocab) RAM
    regardless of corpus size:
      - dream replay  → a size-``max_replay`` min-heap of hottest memories;
      - re-embedding  → the first ``max_reembed`` stale memories;
      - narration     → a streaming keyword-frequency dict + running top-1
        importance + a count.
    Peak RAM is one chunk plus those bounded accumulators — so it scales to
    millions of memories. ``run_sleep_compute`` delegates here with a single
    chunk for callers that already hold a list.

    Targeted memory reactivation (F2). The bounded replay heap keys on a replay
    *priority*, not raw heat. With no cue (``cue is None`` / empty) the priority
    is exactly ``heat``, so the hottest set retained and its ordering are
    identical to the pre-F2 pass (identity). With a cue, each memory's priority
    is ``heat + cue_boost * cue_match_score(cue, mem)`` (see
    ``targeted_reactivation``), so cue-matching memories are preferentially
    retained in the bounded top-``max_replay`` set and enriched first — the
    cue-directed replay of Rasch et al. (2007). The cue only ever *adds* a
    non-negative boost. This function stays pure; the ablation guard
    (Mechanism.TARGETED_REACTIVATION) is applied by the caller
    (``sleep_phases``), which passes ``cue=None`` when the mechanism is ablated.
    """
    heat_heap: list[tuple[float, int, dict[str, Any]]] = []
    stale: list[dict[str, Any]] = []
    freq: dict[str, int] = {}
    top_imp: dict[str, Any] | None = None
    count = 0
    order = 0
    has_cue = bool((cue or "").strip())
    for chunk in memory_chunks:
        for mem in chunk:
            # Consumer-side supersession skip. The chunks come from the decay
            # cursor (iter_memories_for_decay), which MUST keep seeing
            # superseded physical rows so decay/forgetting/homeostatic keep
            # cooling them — so the cursor cannot filter. Sleep, however,
            # SERVES content: replay re-enriches the row and the narration
            # folds its content into a new semantic memory. A superseded
            # version must reach neither. Single-occurrence filter at the
            # consumer boundary, per the read-path supersession audit
            # (docs/program/pr2-read-path-supersession-audit.json).
            if mem.get("superseded_by_id") is not None:
                continue
            count += 1
            order += 1
            heat = float(mem.get("heat", 0) or 0)
            # Replay priority = heat + cue boost. No cue → priority == heat, so
            # the retained hottest set and its order are byte-for-byte the
            # pre-F2 selection (identity).
            priority = heat
            if has_cue:
                priority = heat + cue_boost * cue_match_score(cue, mem)
            if len(heat_heap) < max_replay:
                heapq.heappush(heat_heap, (priority, order, mem))
            elif priority > heat_heap[0][0]:
                heapq.heapreplace(heat_heap, (priority, order, mem))
            if len(stale) < max_reembed and _is_stale_embedding(mem):
                stale.append(mem)
            content = mem.get("content", "")
            if content:
                _accumulate_keywords(freq, content)
            if top_imp is None or float(mem.get("importance", 0) or 0) > float(
                top_imp.get("importance", 0) or 0
            ):
                top_imp = mem

    hottest = [m for _, _, m in sorted(heat_heap, key=lambda t: t[0], reverse=True)]
    return {
        "replay_updates": _replay_updates_for(hottest),
        "cluster_summaries": summarize_clusters(clusters or []),
        "stale_embeddings": [
            {"memory_id": m["id"], "content": m.get("content", "")} for m in stale
        ],
        "narration": _narration_from_accumulators(
            freq, top_imp, count, directory, period_label
        ),
    }


def run_sleep_compute(
    memories: list[dict[str, Any]],
    clusters: list[dict[str, Any]] | None = None,
    directory: str = "",
    period_label: str = "recent",
    max_replay: int = 50,
    max_reembed: int = 100,
    cue: str | None = None,
    cue_boost: float = 1.0,
) -> dict[str, Any]:
    """Run the full sleep compute pass over an in-memory list.

    Thin wrapper over ``run_sleep_compute_streamed`` (one chunk) so existing
    list-holding callers keep working; new callers should stream chunks. The
    optional ``cue`` (F2 targeted reactivation) is forwarded verbatim; no cue
    means the pass is identical to pre-F2.
    """
    return run_sleep_compute_streamed(
        [memories],
        clusters=clusters,
        directory=directory,
        period_label=period_label,
        max_replay=max_replay,
        max_reembed=max_reembed,
        cue=cue,
        cue_boost=cue_boost,
    )
