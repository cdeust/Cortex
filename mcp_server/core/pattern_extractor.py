"""Extract entry points, recurring patterns, tool preferences, and session shape.

Agglomerative clustering for entry points (O(n^3), fine for 10-100 sessions).
N-gram mining for recurring patterns (bigrams + trigrams, >=3-session threshold).
Tool stats and session shape are delegated to session_shape module.
"""

from __future__ import annotations

import re
from typing import Any

from mcp_server.core.session_shape import (
    extract_session_shape,
    extract_tool_preferences,
)
from mcp_server.shared.similarity import jaccard_similarity
from mcp_server.shared.text import STOPWORDS, extract_keywords

_SPLIT_RE = re.compile(r"\W+")


# ---------------------------------------------------------------------------
# 1. Entry Points — Agglomerative clustering
# ---------------------------------------------------------------------------


def _agglomerative_clusters(items: list[dict], threshold: float) -> list[list[dict]]:
    """Merge items by average-linkage Jaccard similarity until below threshold."""
    clusters: list[list[dict]] = [[item] for item in items]

    while True:
        best_sim = -1.0
        best_i = -1
        best_j = -1

        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                sim_sum = 0.0
                sim_count = 0
                for a in clusters[i]:
                    for b in clusters[j]:
                        sim_sum += jaccard_similarity(a["keywords"], b["keywords"])
                        sim_count += 1
                sim = sim_sum / sim_count if sim_count > 0 else 0.0
                if sim > best_sim:
                    best_sim = sim
                    best_i = i
                    best_j = j

        if best_sim < threshold or best_i == -1:
            break

        merged = clusters[best_i] + clusters[best_j]
        next_clusters = [
            c for k, c in enumerate(clusters) if k != best_i and k != best_j
        ]
        next_clusters.append(merged)
        clusters = next_clusters

    return clusters


def _label_cluster(cluster: list[dict]) -> str:
    """Label a cluster by its top-3 most frequent keywords."""
    freq: dict[str, int] = {}
    for item in cluster:
        for kw in item["keywords"]:
            freq[kw] = freq.get(kw, 0) + 1
    top = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:3]
    return " / ".join(kw for kw, _ in top) or "general"


def _extract_first_user_message(conv: dict) -> str | None:
    """Extract the first user message from a conversation dict."""
    if conv.get("firstMessage"):
        return conv["firstMessage"]
    if conv.get("messages"):
        for m in conv["messages"]:
            role = m.get("role") or m.get("speaker") or ""
            if role == "user":
                if isinstance(m, str):
                    return m
                return m.get("content") or m.get("text") or ""
    return None


def extract_entry_points(conversations: list[dict]) -> list[dict[str, Any]]:
    """Cluster first-messages into entry point patterns."""
    items: list[dict] = []
    for conv in conversations:
        text = _extract_first_user_message(conv)
        if not text or not text.strip():
            continue
        items.append({"keywords": extract_keywords(text), "message": text.strip()})

    if not items:
        return []

    clusters = _agglomerative_clusters(items, threshold=0.3)
    clusters.sort(key=lambda c: len(c), reverse=True)
    total = len(items)

    results = []
    for cluster in clusters[:5]:
        frequency = len(cluster)
        results.append(
            {
                "pattern": _label_cluster(cluster),
                "frequency": frequency,
                "confidence": frequency / total if total > 0 else 0,
                "exampleMessages": [item["message"] for item in cluster[:3]],
            }
        )
    return results


# ---------------------------------------------------------------------------
# 2. Recurring Patterns (n-gram mining)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    return [
        w for w in _SPLIT_RE.split(text.lower()) if len(w) >= 2 and w not in STOPWORDS
    ]


def _extract_ngrams(tokens: list[str]) -> list[str]:
    ngrams = []
    for i in range(len(tokens) - 1):
        ngrams.append(f"{tokens[i]} {tokens[i + 1]}")
        if i < len(tokens) - 2:
            ngrams.append(f"{tokens[i]} {tokens[i + 1]} {tokens[i + 2]}")
    return ngrams


def _shared_keyword_count(a: str, b: str) -> int:
    return len(set(a.split()) & set(b.split()))


def _collect_ngram_sessions(
    conversations: list[dict],
) -> dict[str, set[int]]:
    """Build mapping of ngram -> set of session indices where it appears."""
    ngram_sessions: dict[str, set[int]] = {}
    for session_idx, conv in enumerate(conversations):
        all_text = conv.get("allText") or conv.get("fullText") or ""
        if not all_text.strip():
            continue
        tokens = _tokenize(all_text)
        for ng in set(_extract_ngrams(tokens)):
            if ng not in ngram_sessions:
                ngram_sessions[ng] = set()
            ngram_sessions[ng].add(session_idx)
    return ngram_sessions


def _group_qualified_ngrams(
    qualified: list[dict],
) -> list[dict]:
    """Group overlapping ngrams by shared keywords."""
    groups: list[dict] = []
    for item in qualified:
        merged = False
        for group in groups:
            overlaps = any(
                _shared_keyword_count(item["ngram"], existing) >= 2
                for existing in group["ngrams"]
            )
            if overlaps:
                group["ngrams"].append(item["ngram"])
                group["session_union"].update(item["sessions"])
                merged = True
                break
        if not merged:
            groups.append(
                {
                    "ngrams": [item["ngram"]],
                    "session_union": set(item["sessions"]),
                }
            )
    return groups


def _groups_to_results(
    groups: list[dict],
    ngram_sessions: dict[str, set[int]],
    total_sessions: int,
) -> list[dict[str, Any]]:
    """Convert ngram groups into result dicts with frequency and confidence."""
    results = []
    for group in groups:
        top_ngram = max(
            group["ngrams"],
            key=lambda ng: len(ngram_sessions.get(ng, set())),
        )
        sessions_observed = len(group["session_union"])
        frequency = len(ngram_sessions.get(top_ngram, set())) or sessions_observed
        results.append(
            {
                "pattern": top_ngram,
                "ngramSignature": group["ngrams"][:10],
                "frequency": frequency,
                "sessionsObserved": sessions_observed,
                "confidence": sessions_observed / total_sessions
                if total_sessions > 0
                else 0,
            }
        )
    return results


def extract_recurring_patterns(conversations: list[dict]) -> list[dict[str, Any]]:
    """Mine bigram/trigram patterns appearing in 3+ sessions."""
    total_sessions = len(conversations)
    if total_sessions == 0:
        return []

    ngram_sessions = _collect_ngram_sessions(conversations)

    min_sessions = 3
    qualified = sorted(
        [
            {"ngram": ng, "sessions": sessions}
            for ng, sessions in ngram_sessions.items()
            if len(sessions) >= min_sessions
        ],
        key=lambda x: len(x["sessions"]),
        reverse=True,
    )

    if not qualified:
        return []

    groups = _group_qualified_ngrams(qualified)
    return _groups_to_results(groups, ngram_sessions, total_sessions)


# ---------------------------------------------------------------------------
# Main export
# ---------------------------------------------------------------------------


def extract_patterns(conversations: list[dict]) -> dict[str, Any]:
    """Extract all pattern types from conversations for a single domain."""
    return {
        "entryPoints": extract_entry_points(conversations),
        "recurringPatterns": extract_recurring_patterns(conversations),
        "toolPreferences": extract_tool_preferences(conversations),
        "sessionShape": extract_session_shape(conversations),
    }
