"""MinHash sketches + band-LSH blocking — dependency-free (numpy only).

source: ADR-0658"""

from __future__ import annotations

import hashlib
import struct

import numpy as np

_MERSENNE_PRIME = np.uint64((1 << 61) - 1)  # source: ADR-0658
_HASH_MASK = np.uint64(0xFFFF_FFFF)  # mask permuted values to 32 bits

# source: ADR-0658

_COEFFS: dict[int, tuple[np.ndarray, np.ndarray]] = {}


def _coeffs(num_perm: int) -> tuple[np.ndarray, np.ndarray]:
    """Return cached (a, b) coefficient arrays for ``num_perm`` permutations."""
    if num_perm not in _COEFFS:
        rng = np.random.RandomState(1)  # source: ADR-0658
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
        hv = np.uint64(struct.unpack("<I", hashlib.sha1(value).digest()[:4])[0])
        permuted = np.bitwise_and(
            (self._a * hv + self._b) % _MERSENNE_PRIME, _HASH_MASK
        )
        self.hashvalues = np.minimum(self.hashvalues, permuted)

    def jaccard(self, other: "MinHash") -> float:
        """Estimate Jaccard similarity as the fraction of agreeing permutations."""
        if self.num_perm != other.num_perm:
            raise ValueError("MinHash.jaccard: sketches have different num_perm")
        return (
            float(np.count_nonzero(self.hashvalues == other.hashvalues)) / self.num_perm
        )


def _integrate(f, lo: float, hi: float, n: int = 128) -> float:
    """Integrate the function numerically using left Riemann sums.

    source: ADR-0658
    """
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
            raise ValueError(f"MinHashLSH: key {key!r} already inserted")
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
