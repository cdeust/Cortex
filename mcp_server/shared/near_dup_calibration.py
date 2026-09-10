"""Calibrate near-duplicate thresholds and group candidate pairs for supersession.

source: ADR-0659
"""

from __future__ import annotations

from typing import NamedTuple

# source: ADR-0659


STRATA: tuple[tuple[float, float], ...] = (
    (0.75, 0.80),
    (0.80, 0.85),
    (0.85, 0.90),
    (0.90, 0.95),
    (0.95, 1.0001),  # source: ADR-0659
)

# source: ADR-0659


THRESHOLD_CANDIDATES: tuple[float, ...] = tuple(low for low, _high in STRATA)

# Floor of the whole candidate scan — below this, a pair is not even
# considered a near-dup candidate (I6-D2: "au-dessus de ~0.75").
SCAN_FLOOR = 0.75


class CandidatePair(NamedTuple):
    """One measured (id_a < id_b, similarity) candidate above SCAN_FLOOR.

    source: ADR-0659
    """

    id_a: int
    id_b: int
    similarity: float


class LabeledPair(NamedTuple):
    """One candidate pair with a human/LLM-judged verdict.

    ``verdict`` is ``True`` for "duplicate" (same fact, collapse is
    correct), ``False`` for "distinct" (different facts despite the
    embedding similarity — a false positive for auto-collapse purposes).
    """

    id_a: int
    id_b: int
    similarity: float
    verdict: bool
    justification: str


def stratum_for(similarity: float) -> str | None:
    """Return the stratum label ``"{low:.2f}-{high:.2f}"`` for ``similarity``.

    source: ADR-0659"""
    for low, high in STRATA:
        if low <= similarity < high:
            return f"{low:.2f}-{high if high <= 1.0 else 1.0:.2f}"
    return None


def bucket_by_stratum(
    pairs: list[CandidatePair],
) -> dict[str, list[CandidatePair]]:
    """Group ``pairs`` by stratum label, dropping anything outside the strata.

    Post-condition: every returned list is non-empty; the union of all
    returned pairs is exactly the input pairs whose ``similarity`` falls
    in ``[SCAN_FLOOR, 1.0001)``. Order within each bucket is preserved
    from the input.
    """
    buckets: dict[str, list[CandidatePair]] = {}
    for pair in pairs:
        label = stratum_for(pair.similarity)
        if label is None:
            continue
        buckets.setdefault(label, []).append(pair)
    return buckets


def stratified_sample(
    pairs: list[CandidatePair], per_stratum: int = 20
) -> list[CandidatePair]:
    """Deterministically sub-sample up to ``per_stratum`` pairs per stratum.

    source: ADR-0659"""
    buckets = bucket_by_stratum(pairs)
    sample: list[CandidatePair] = []
    for low, high in STRATA:
        label = f"{low:.2f}-{high if high <= 1.0 else 1.0:.2f}"
        bucket = sorted(buckets.get(label, []), key=lambda p: (p.id_a, p.id_b))
        if len(bucket) <= per_stratum:
            sample.extend(bucket)
            continue
        # source: ADR-0659

        step = len(bucket) / per_stratum
        indices = sorted({int(i * step) for i in range(per_stratum)})
        sample.extend(bucket[i] for i in indices)
    return sample


class ThresholdStats(NamedTuple):
    """Measured precision at one candidate threshold.

    source: ADR-0659
    """

    threshold: float
    n_labeled: int
    n_duplicate: int
    precision: float


def precision_by_threshold(
    labeled: list[LabeledPair],
    thresholds: tuple[float, ...] = THRESHOLD_CANDIDATES,
) -> list[ThresholdStats]:
    """Measured precision of "everything >= threshold is a duplicate", per candidate.

    source: ADR-0659

    Post-condition: one ``ThresholdStats`` per ``thresholds`` entry, in
                    the same order. ``precision`` = (# labeled pairs with
                    ``similarity >= threshold`` AND ``verdict is True``)
                    / (# labeled pairs with ``similarity >= threshold``).
                    A threshold with zero labeled pairs at/above it has
                    ``n_labeled == 0`` and ``precision == 0.0`` (caller
                    must check ``n_labeled`` before trusting precision —
                    an empty sample is not evidence of 100% precision).
    """
    stats: list[ThresholdStats] = []
    for threshold in thresholds:
        at_or_above = [p for p in labeled if p.similarity >= threshold]
        n = len(at_or_above)
        n_dup = sum(1 for p in at_or_above if p.verdict)
        precision = (n_dup / n) if n > 0 else 0.0
        stats.append(
            ThresholdStats(
                threshold=threshold, n_labeled=n, n_duplicate=n_dup, precision=precision
            )
        )
    return stats


def select_threshold(stats: list[ThresholdStats]) -> float | None:
    """Lowest threshold with measured 100% precision AND >= 1 labeled pair.

    source: ADR-0659

    Pre-condition:  ``stats`` is ``precision_by_threshold``'s output,
                    threshold values in ascending order (matches
                    ``THRESHOLD_CANDIDATES``).
    Post-condition: returns the smallest ``threshold`` for which
                    ``precision == 1.0`` and ``n_labeled >= 1`` (Q2: "la
                    plus basse borne S telle que precision = 100% ...
                    aucun faux positif"). Returns ``None`` if no
                    candidate threshold reaches 100% precision on the
                    sample — per I6-D2 step 6, this means NO auto-collapse
                    at all; the caller must not invent a fallback
                    threshold.
    """
    qualifying = [s.threshold for s in stats if s.n_labeled >= 1 and s.precision >= 1.0]
    return min(qualifying) if qualifying else None


# ── Connected components (transitive near-dup families) ────────────────


def build_components(pairs: list[CandidatePair]) -> list[frozenset[int]]:
    """Group candidate pairs into connected components (union-find).

    source: ADR-0659"""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for pair in pairs:
        parent.setdefault(pair.id_a, pair.id_a)
        parent.setdefault(pair.id_b, pair.id_b)
        union(pair.id_a, pair.id_b)

    groups: dict[int, set[int]] = {}
    for node in parent:
        root = find(node)
        groups.setdefault(root, set()).add(node)

    components = [frozenset(members) for members in groups.values()]
    return sorted(components, key=lambda c: min(c))


__all__ = [
    "SCAN_FLOOR",
    "STRATA",
    "THRESHOLD_CANDIDATES",
    "CandidatePair",
    "LabeledPair",
    "ThresholdStats",
    "stratum_for",
    "bucket_by_stratum",
    "stratified_sample",
    "precision_by_threshold",
    "select_threshold",
    "build_components",
]
