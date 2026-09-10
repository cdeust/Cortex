"""Edit-distance and prefix-weighted string similarity — dependency-free.

source: ADR-0666"""

from __future__ import annotations

# source: ADR-0666
_WINKLER_SCALING = 0.1  # source: ADR-0666
_WINKLER_MAX_PREFIX = 4  # source: ADR-0666


def _jaro_matches(s1: str, s2: str, window: int) -> tuple[list[bool], list[bool], int]:
    """Return (s1_matched, s2_matched, match_count) within the match window."""
    s1_matched = [False] * len(s1)
    s2_matched = [False] * len(s2)
    matches = 0
    for i in range(len(s1)):
        lo = max(0, i - window)
        hi = min(i + window + 1, len(s2))
        for j in range(lo, hi):
            if not s2_matched[j] and s1[i] == s2[j]:
                s1_matched[i] = s2_matched[j] = True
                matches += 1
                break
    return s1_matched, s2_matched, matches


def _jaro_transpositions(
    s1: str, s2: str, s1_matched: list[bool], s2_matched: list[bool]
) -> int:
    """Count half-transpositions: matched chars appearing out of order."""
    transpositions = 0
    k = 0
    for i in range(len(s1)):
        if not s1_matched[i]:
            continue
        while not s2_matched[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1
    return transpositions // 2


def jaro_similarity(s1: str, s2: str) -> float:
    """Jaro similarity in [0, 1].

    source: ADR-0666

    jaro = 0 if no matches, else (1/3)(m/|s1| + m/|s2| + (m - t)/m), where m is
    the count of matching characters (same char within a window of
    floor(max(|s1|, |s2|)/2) - 1) and t is half the number of transpositions.
    """
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0
    window = max(0, max(len1, len2) // 2 - 1)
    s1_matched, s2_matched, m = _jaro_matches(s1, s2, window)
    if m == 0:
        return 0.0
    t = _jaro_transpositions(s1, s2, s1_matched, s2_matched)
    return (m / len1 + m / len2 + (m - t) / m) / 3.0


def jaro_winkler_similarity(s1: str, s2: str) -> float:
    """Jaro-Winkler similarity in [0, 1].

    source: ADR-0666

    jw = jaro + l * p * (1 - jaro), where l is the common-prefix length capped
    at 4 and p = 0.1. The prefix boost is applied unconditionally (matching
    rapidfuzz's default, which graphify relied on — no 0.7 jaro gate).
    """
    jaro = jaro_similarity(s1, s2)
    prefix = 0
    # source: ADR-0666

    for c1, c2 in zip(s1, s2, strict=False):
        if c1 != c2:
            break
        prefix += 1
        if prefix == _WINKLER_MAX_PREFIX:
            break
    return jaro + prefix * _WINKLER_SCALING * (1.0 - jaro)


def osa_distance(s1: str, s2: str) -> int:
    """Optimal String Alignment distance (restricted Damerau-Levenshtein).

    source: ADR-0666

    Counts insertions, deletions, substitutions, and adjacent transpositions
    (each substring edited at most once). Used only for the bounded
    single-edit guard in entity_dedup, where the OSA and true-DL values
    coincide.
    """
    if s1 == s2:
        return 0
    len1, len2 = len(s1), len(s2)
    if len1 == 0:
        return len2
    if len2 == 0:
        return len1

    prev2: list[int] = []  # row i-2
    prev: list[int] = list(range(len2 + 1))  # row i-1
    for i in range(1, len1 + 1):
        cur = [i] + [0] * len2
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            cur[j] = min(
                cur[j - 1] + 1,  # insertion
                prev[j] + 1,  # deletion
                prev[j - 1] + cost,  # substitution
            )
            if i > 1 and j > 1 and s1[i - 1] == s2[j - 2] and s1[i - 2] == s2[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)  # adjacent transposition
        prev2, prev = prev, cur
    return prev[len2]
