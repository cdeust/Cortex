"""Signal fusion: WRRF and critical mass quality zones.

Quality zones from ai-architect RAGCriticalMassMonitor (Liu et al. 2024).
WRRF constant K=60 (standard RRF baseline).
"""

from __future__ import annotations


class QualityZone:
    OPTIMAL = "optimal"  # 5-10 chunks
    ACCEPTABLE = "acceptable"  # 11-15 chunks
    DEGRADED = "degraded"  # 16-20 chunks
    CRITICAL = "critical"  # 21-25 chunks
    FAILED = "failed"  # >25 chunks


def assess_quality_zone(chunk_count: int) -> str:
    """Determine quality zone from chunk count."""
    if chunk_count <= 10:
        return QualityZone.OPTIMAL
    if chunk_count <= 15:
        return QualityZone.ACCEPTABLE
    if chunk_count <= 20:
        return QualityZone.DEGRADED
    if chunk_count <= 25:
        return QualityZone.CRITICAL
    return QualityZone.FAILED


def enforce_chunk_limit(requested: int, maximum: int = 25) -> int:
    """Hard cap to prevent quality collapse."""
    return min(requested, maximum)


def wrrf_fuse(
    signal_results: dict[str, list[tuple[int, float]]],
    signal_weights: dict[str, float],
    k: int = 60,
) -> list[tuple[int, float]]:
    """Weighted Reciprocal Rank Fusion across named signals.

    Each signal: ranked list of (doc_id, raw_score).
    Contribution per item = weight / (k + rank + 1).
    """
    scores: dict[int, float] = {}
    for name, results in signal_results.items():
        weight = signal_weights.get(name, 0.0)
        if weight <= 0:
            continue
        for rank, (doc_id, _) in enumerate(results):
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
