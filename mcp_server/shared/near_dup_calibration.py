"""Calibrate the near-duplicate similarity threshold on measured data
(I6-D2, INC6.4 campaign) and group candidate pairs into connected
components for supersession.

The write-path curation gate (``core/curation.py::decide_curation_action``,
``MERGE_THRESHOLD = 0.85``) is an *ingestion-time hypothesis*: it decides
merge/link/create for ONE new memory against its near-neighbors at
``remember`` time, and has never been validated retrospectively against
the existing corpus (I6-D2 design doc, 2026-07-10). This module holds the
pure logic for that retrospective validation:

  1. bucket measured (id_a, id_b, cosine_similarity) candidate pairs into
     fixed strata around the 0.85 hypothesis;
  2. deterministically sub-sample each stratum for manual labeling
     (duplicate/distinct), so an auditor can regenerate the exact same
     sample from the same candidate list;
  3. given labels, compute precision at each stratum boundary and select
     the lowest boundary S with 100% measured precision (Q2 arbitration:
     auto-supersession is only justified where zero false positives were
     observed) — or report that no boundary qualifies;
  4. group pairs at/above S into connected components (a near-dup
     "family" is transitive: A~B and B~C both measured similar enough
     implies all three collapse together), reusing the same
     survivor-election contract as the exact-dedup campaign
     (``core.memory_dedup_exact.elect_survivor``) once the caller has
     fetched each member's ``effective_heat``/``created_at``.

Pure logic, no I/O — mirrors ``core/memory_dedup_exact.py``'s DI split
(coding-standards.md §2, Dependency Rule: core imports stdlib only).
"""

from __future__ import annotations

from typing import NamedTuple

# Stratum boundaries around the write-path's MERGE_THRESHOLD hypothesis
# (core/curation.py::MERGE_THRESHOLD = 0.85). Half-open intervals
# [low, high) except the last, which is closed at 1.0 (cosine similarity
# never exceeds 1.0 for normalized embeddings).
# source: I6-D2 design doc (inc6-design-campagne-memoire.md) — "étiqueter
# a la main ~100 paires autour de l'hypothese de depart 0.85", strata
# specified verbatim: 0.75-0.80, 0.80-0.85, 0.85-0.90, 0.90-0.95, 0.95-1.0.
STRATA: tuple[tuple[float, float], ...] = (
    (0.75, 0.80),
    (0.80, 0.85),
    (0.85, 0.90),
    (0.90, 0.95),
    (0.95, 1.0001),  # +epsilon so a similarity of exactly 1.0 falls inside
)

# The boundary of each stratum is a threshold candidate for S (Q2: "la
# plus basse borne S telle que precision = 100%"). Sorted ascending so
# select_threshold can scan from the strictest (highest) requirement
# downward, or from the loosest upward, in one deterministic order.
THRESHOLD_CANDIDATES: tuple[float, ...] = tuple(low for low, _high in STRATA)

# Floor of the whole candidate scan — below this, a pair is not even
# considered a near-dup candidate (I6-D2: "au-dessus de ~0.75").
SCAN_FLOOR = 0.75


class CandidatePair(NamedTuple):
    """One measured (id_a < id_b, similarity) candidate above SCAN_FLOOR."""

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

    Post-condition: returns ``None`` if ``similarity < SCAN_FLOOR`` or
    ``similarity > 1.0001`` (out of the calibration's defined range);
    otherwise returns exactly one of the 5 labels in ``STRATA``, the
    unique stratum whose half-open interval contains ``similarity``.
    """
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

    Pre-condition:  ``pairs`` need not be sorted; this function sorts
                    each bucket internally.
    Post-condition: for each of the 5 strata with >= 1 candidate, returns
                    up to ``per_stratum`` pairs, chosen by evenly-spaced
                    index over the bucket SORTED by ``(id_a, id_b)`` —
                    fully deterministic (no RNG, no seed to document):
                    re-running this function on the same candidate list
                    reproduces the exact same sample byte-for-byte. When
                    a bucket has <= ``per_stratum`` members, all of them
                    are returned. Buckets are emitted in ``STRATA`` order
                    (low to high) so the artifact reads stratum-by-stratum.
    """
    buckets = bucket_by_stratum(pairs)
    sample: list[CandidatePair] = []
    for low, high in STRATA:
        label = f"{low:.2f}-{high if high <= 1.0 else 1.0:.2f}"
        bucket = sorted(buckets.get(label, []), key=lambda p: (p.id_a, p.id_b))
        if len(bucket) <= per_stratum:
            sample.extend(bucket)
            continue
        # Evenly-spaced indices across the sorted bucket: index i*step,
        # step = len(bucket) / per_stratum, floored — covers the full
        # similarity range within the stratum instead of clustering at
        # one end (a plain bucket[:per_stratum] would only sample the
        # lowest-id pairs, not a spread across the stratum's similarity
        # sub-range once combined with the caller's ORDER BY).
        step = len(bucket) / per_stratum
        indices = sorted({int(i * step) for i in range(per_stratum)})
        sample.extend(bucket[i] for i in indices)
    return sample


class ThresholdStats(NamedTuple):
    """Measured precision at one candidate threshold."""

    threshold: float
    n_labeled: int
    n_duplicate: int
    precision: float


def precision_by_threshold(
    labeled: list[LabeledPair],
    thresholds: tuple[float, ...] = THRESHOLD_CANDIDATES,
) -> list[ThresholdStats]:
    """Measured precision of "everything >= threshold is a duplicate", per candidate.

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

    A near-dup relation measured pairwise is applied transitively for
    collapse purposes: if A~B and B~C were both measured above the
    selected threshold, all three belong to one family that must elect
    a single survivor (matching how ``core/memory_dedup_exact.py``
    treats an exact-duplicate GROUP, not just a pair).

    Post-condition: returns one ``frozenset`` per connected component of
                    the graph whose edges are ``pairs``; the union of all
                    returned components is exactly the set of ids that
                    appear in at least one pair. Singleton ids not in any
                    pair are absent (a "component of size 1" has nothing
                    to supersede). Deterministic order: components sorted
                    by their minimum member id, ascending.
    """
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
