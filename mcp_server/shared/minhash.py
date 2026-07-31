"""MinHash sketches + band-LSH blocking — dependency-free (numpy only).

Used by the entity-graph fuzzy deduplicator (``core.entity_dedup``) to block
candidate near-duplicate entity labels in sub-quadratic time before the exact
Jaro-Winkler verification pass.

Sources:
    - MinHash (Jaccard estimation via min-wise permutations):
      Broder, A. (1997). "On the resemblance and containment of documents."
      Compression and Complexity of Sequences (SEQUENCES '97).
    - Band-LSH (banding trades false-positive/false-negative rate against the
      Jaccard threshold): Indyk & Motwani (1998), and Leskovec, Rajaraman &
      Ullman, *Mining of Massive Datasets*, 3rd ed., Ch. 3.

The hash family (Mersenne-prime affine permutations) and band structure are
equivalent to ``datasketch`` so dedup quality is unchanged, but this module
deliberately avoids ``datasketch``/``scipy``: datasketch.lsh imports
``scipy.integrate.quad`` at module load, whose array_api_compat layer can hang
for minutes under EDR software on some platforms (graphify issue, ported here).

Pure utility — no I/O, no domain knowledge. Shared layer.
"""

from __future__ import annotations

import hashlib
import struct

import numpy as np

_MERSENNE_PRIME = np.uint64((1 << 61) - 1)  # source: Broder 1997 hash family
_HASH_MASK = np.uint64(0xFFFF_FFFF)  # mask permuted values to 32 bits

# One (a, b) affine-coefficient pair-array per num_perm, shared across instances.
# Seeded deterministically so sketches are reproducible run-to-run.
_COEFFS: dict[int, tuple[np.ndarray, np.ndarray]] = {}


def _coeffs(num_perm: int) -> tuple[np.ndarray, np.ndarray]:
    """Return cached (a, b) coefficient arrays for ``num_perm`` permutations."""
    if num_perm not in _COEFFS:
        rng = np.random.RandomState(1)  # fixed seed → deterministic sketches
        a = rng.randint(1, int(_MERSENNE_PRIME), num_perm, dtype=np.uint64)
        b = rng.randint(0, int(_MERSENNE_PRIME), num_perm, dtype=np.uint64)
        _COEFFS[num_perm] = (a, b)
    return _COEFFS[num_perm]


class MinHash:
    """A MinHash sketch estimating Jaccard similarity between shingle sets."""

    __slots__ = ("num_perm", "hashvalues", "_a", "_b")

    def __init__(self, num_perm: int = 128) -> None:
        self.num_perm = num_perm
        self.hashvalues = np.full(num_perm, int(_HASH_MASK), dtype=np.uint64)
        self._a, self._b = _coeffs(num_perm)

    def update(self, value: bytes) -> None:
        """Fold one shingle into the sketch (keeps the per-permutation minimum)."""
        # usedforsecurity=False: sha1 here is only a fast, uniformly-
        # distributed hash function for MinHash shingle bucketing, never
        # a security/integrity check — also lets this run under FIPS
        # mode, which blocks sha1 unless explicitly marked non-security.
        digest = hashlib.sha1(value, usedforsecurity=False).digest()
        hv = np.uint64(struct.unpack("<I", digest[:4])[0])
        permuted = np.bitwise_and(
            (self._a * hv + self._b) % _MERSENNE_PRIME, _HASH_MASK
        )
        self.hashvalues = np.minimum(self.hashvalues, permuted)

    def jaccard(self, other: "MinHash") -> float:
        """Estimate Jaccard similarity as the fraction of agreeing permutations."""
        if self.num_perm != other.num_perm:
            raise ValueError("MinHash.jaccard: sketches have different num_perm")  # noqa: TRY003 — one-off message, not reused (§3.3)
        return (
            float(np.count_nonzero(self.hashvalues == other.hashvalues)) / self.num_perm
        )


def _integrate(f, lo: float, hi: float, n: int = 128) -> float:
    """Left-Riemann numerical integration — replaces scipy.integrate.quad."""
    h = (hi - lo) / n
    return h * sum(f(lo + i * h) for i in range(n))


_LSH_PARAMS_CACHE: dict[tuple[float, int], tuple[int, int]] = {}


def optimal_lsh_params(threshold: float, num_perm: int) -> tuple[int, int]:
    """Find (bands, rows) minimising the weighted false-positive/negative error.

    The S-curve probability that two sets with Jaccard ``s`` collide in at
    least one band is ``1 - (1 - s**rows)**bands``. We pick the (bands, rows)
    split with bands*rows <= num_perm that minimises the symmetric error around
    ``threshold`` (Leskovec/Rajaraman/Ullman, *MMDS* Ch. 3.4.2).
    """
    key = (threshold, num_perm)
    if key in _LSH_PARAMS_CACHE:
        return _LSH_PARAMS_CACHE[key]
    best_err, best = float("inf"), (1, 1)
    for b in range(1, num_perm + 1):
        for r in range(1, num_perm // b + 1):
            fp = _integrate(
                lambda s, _b=float(b), _r=float(r): 1 - (1 - s**_r) ** _b,
                0.0,
                threshold,
            )
            fn = _integrate(
                lambda s, _b=float(b), _r=float(r): 1 - (1 - (1 - s**_r) ** _b),
                threshold,
                1.0,
            )
            err = 0.5 * fp + 0.5 * fn
            if err < best_err:
                best_err, best = err, (b, r)
    _LSH_PARAMS_CACHE[key] = best
    return best


class MinHashLSH:
    """Band-hashing locality-sensitive index over MinHash sketches.

    ``insert`` buckets a sketch by each of its ``bands`` band-signatures;
    ``query`` returns every key sharing at least one band with the probe — the
    candidate set for exact verification.
    """

    def __init__(self, threshold: float = 0.5, num_perm: int = 128) -> None:
        self.b, self.r = optimal_lsh_params(threshold, num_perm)
        self._tables: list[dict[bytes, list[str]]] = [{} for _ in range(self.b)]
        self._keys: set[str] = set()

    def insert(self, key: str, minhash: MinHash) -> None:
        if key in self._keys:
            raise ValueError(f"MinHashLSH: key {key!r} already inserted")  # noqa: TRY003 — one-off message, not reused (§3.3)
        self._keys.add(key)
        hv = minhash.hashvalues
        for i, table in enumerate(self._tables):
            band = hv[i * self.r : (i + 1) * self.r].tobytes()
            table.setdefault(band, []).append(key)

    def query(self, minhash: MinHash) -> list[str]:
        hv = minhash.hashvalues
        candidates: set[str] = set()
        for i, table in enumerate(self._tables):
            band = hv[i * self.r : (i + 1) * self.r].tobytes()
            candidates.update(table.get(band, []))
        return list(candidates)
