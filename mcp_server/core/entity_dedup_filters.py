"""Pure predicates for fuzzy entity deduplication.

Normalization, entropy gating, shingle/MinHash construction, and the three
false-positive blockers that keep near-miss-but-distinct labels from merging.
Ported from graphify's dedup pipeline (graphify/dedup.py) and adapted to
Cortex's entity model. Pure logic — no I/O.

Constants are inherited from graphify's empirically-tuned pipeline; they are
re-validated by the dup-collapse benchmark (benchmarks/entity_dedup/). Each
carries its source below.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict

from mcp_server.shared.minhash import MinHash
from mcp_server.shared.string_distance import osa_distance

# ── tunable constants (source: graphify graphify/dedup.py) ──────────────────
ENTROPY_THRESHOLD = 2.5  # bits/char; gate out low-information labels (Shannon 1948)
LSH_THRESHOLD = 0.7  # MinHash band-LSH blocking threshold
MERGE_THRESHOLD = 0.92  # Jaro-Winkler similarity required to merge
NUM_PERM = 128  # MinHash permutations
_SHORT_LABEL_MAX = 12  # below this, fuzzy edits are usually variants not typos
_SAME_LEN_SUB_JW = 0.97  # JW floor for an allowed same-length single substitution

_SHINGLE_K = 3  # character k-gram size for MinHash


def normalize_label(label: str | None) -> str:
    """Lowercase + collapse non-alphanumeric runs to a single space (NFKC)."""
    if not isinstance(label, str):
        label = "" if label is None else str(label)
    label = unicodedata.normalize("NFKC", label)
    return re.sub(r"[\W_]+", " ", label.casefold(), flags=re.UNICODE).strip()


def entropy(label: str) -> float:
    """Shannon entropy (bits/char) of the normalized label (Shannon 1948)."""
    s = normalize_label(label)
    if not s:
        return 0.0
    freq: dict[str, int] = defaultdict(int)
    for ch in s:
        freq[ch] += 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def shingles(text: str, k: int = _SHINGLE_K) -> set[str]:
    """Character k-gram shingles; the whole string if shorter than k."""
    if len(text) < k:
        return {text}
    return {text[i : i + k] for i in range(len(text) - k + 1)}


def make_minhash(normalized: str, num_perm: int = NUM_PERM) -> MinHash:
    """MinHash over space-stripped shingles so 'a b' and 'ab' share shingles."""
    m = MinHash(num_perm=num_perm)
    for shingle in shingles(normalized.replace(" ", "")):
        m.update(shingle.encode("utf-8"))
    return m


# Trailing version/variant suffix: digits (+letters) like "v2", "A55", or a
# 2+ letter codename revision. Stem must end in a letter so plain words don't
# match. Source: graphify _VARIANT_SUFFIX.
_VARIANT_SUFFIX = re.compile(r"^(.*[a-z])([0-9]+[a-z]*|[a-z]{2,})$")


def is_variant_pair(a: str, b: str) -> bool:
    """True if a, b are sibling variants (same stem, different suffix).

    Only meaningful for short labels (< 12 chars); longer labels go through
    Jaro-Winkler normally. Source: graphify _is_variant_pair.
    """
    if a == b or max(len(a), len(b)) >= _SHORT_LABEL_MAX:
        return False
    ma, mb = _VARIANT_SUFFIX.match(a), _VARIANT_SUFFIX.match(b)
    if not (ma and mb):
        return False
    return ma.group(1) == mb.group(1) and ma.group(2) != mb.group(2)


def short_label_blocked(a: str, b: str, jw_score: float) -> bool:
    """Block fuzzy merge of short labels except a same-length single substitution.

    Insertions/deletions on short strings (cranel/cranelr, M1/M1 Pro) score high
    on Jaro-Winkler via the prefix bonus but are rarely true duplicates. Allow
    only a same-length, single-character substitution (a real typo like
    Extractor/Extractar). Source: graphify _short_label_blocked. ``jw_score`` is
    in [0, 1].
    """
    if max(len(a), len(b)) >= _SHORT_LABEL_MAX:
        return False
    if jw_score >= _SAME_LEN_SUB_JW and len(a) == len(b) and osa_distance(a, b) <= 1:
        return False
    return True


def is_affix_extension(a: str, b: str) -> bool:
    """True if one label strictly contains the other as a prefix or suffix.

    Prefix extensions (getActiveSession / getActiveSessions, parseConfig /
    parseConfigFile — graphify #1201) and suffix extensions (MemoryStore /
    PgMemoryStore, Store / FileStore) are specializations, not duplicates: the
    longer label adds a qualifier. Both inflate Jaro-Winkler via shared
    substrings. Block regardless of score.
    """
    lo, hi = sorted((a, b), key=len)
    return hi != lo and (hi.startswith(lo) or hi.endswith(lo))


# source: rule documented in is_structural_identifier docstring (graphify
# #1205 exemption) — multi-segment dotted paths have >= 2 dots; single-dot
# names like "Node.js" do not qualify
_MIN_DOTS_FOR_MODULE_PATH = 2


def is_structural_identifier(label: str) -> bool:
    """True for dotted module paths or slash file paths (code identifiers).

    Cortex mis-types module identifiers like ``mcp_server.core.engram`` as
    ``technology``. These are code symbols whose identity is structural, not a
    fuzzy concept label — and their long shared prefixes (``mcp_server.core.``)
    inflate Jaro-Winkler past the merge threshold for unrelated modules. Exempt
    them from the fuzzy pass exactly as graphify exempts ``file_type=="code"``
    (graphify #1205). Multi-segment dotted paths (>= 2 dots, e.g.
    ``a.b.c``) and any slash path qualify; single-dot names (``Node.js``,
    ``Vue.js``) do not.
    """
    s = label.strip()
    return "/" in s or s.count(".") >= _MIN_DOTS_FOR_MODULE_PATH


def _common_prefix_len(a: str, b: str) -> int:
    p = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        p += 1
    return p


def affixes_sandwich_difference(a: str, b: str) -> bool:
    """Block when a shared prefix AND suffix sandwich dissimilar middles.

    teststoreclassification / testcoreclassification share the prefix "test" and
    a long suffix ("classification") but differ in the middle (store/core) — the
    discriminating concept. Jaro-Winkler scores the shared majority high. Works
    on the normalized (glued) form, so it catches CamelCase identifiers that have
    no separators to tokenize on. When one middle is empty (the labels differ
    only by an affix, e.g. embeddingengine / embedding engine) this does not
    fire — that case is a real merge or handled by is_affix_extension.
    """
    p = _common_prefix_len(a, b)
    s = _common_prefix_len(a[::-1], b[::-1])
    # Clamp so prefix and suffix don't overlap on the shorter string.
    s = min(s, min(len(a), len(b)) - p)
    if s < 0 or p + s < 0.5 * min(len(a), len(b)):
        return False
    mid_a, mid_b = a[p : len(a) - s], b[p : len(b) - s]
    if not mid_a or not mid_b:
        return False
    from mcp_server.shared.string_distance import jaro_winkler_similarity

    return jaro_winkler_similarity(mid_a, mid_b) < MERGE_THRESHOLD


def shared_prefix_masks_difference(a: str, b: str) -> bool:
    """True when a dominant shared prefix hides dissimilar tails.

    Jaro-Winkler's prefix bonus (Winkler 1990) was calibrated for short personal
    names; on longer strings a long common prefix over-credits the score even
    when the discriminating remainders differ. When the longest common prefix is
    at least half of the shorter label, require the post-prefix remainders to
    themselves clear MERGE_THRESHOLD — otherwise block. Defense-in-depth beyond
    is_structural_identifier for long shared-prefix concept labels.
    """
    n = min(len(a), len(b))
    p = _common_prefix_len(a, b)
    if p == 0 or p < 0.5 * n:
        return False
    ra, rb = a[p:], b[p:]
    if not ra or not rb:  # one is a prefix of the other → is_suffix_extension's job
        return False
    from mcp_server.shared.string_distance import jaro_winkler_similarity

    return jaro_winkler_similarity(ra, rb) < MERGE_THRESHOLD
