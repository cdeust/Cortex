"""Ad-hoc comparison harness for issue #184.

Measures three embedding variants on LongMemEval-S (n=50) through the exact
#169 SQLite fallback path, by monkeypatching the embed_text the fallback
provider calls:

  - off        : stride forced to 1 (no subsampling at all)
  - current    : shipped document-length striding (strides the WHOLE loop)
  - faithful_a : CBM-faithful — first-order terms always complete; only a
                 token whose within-document occurrence count exceeds
                 _MAX_OCCUR has its co-occurrence pass strided.

Reuses run_sqlite_fallback_bench._eval_mode verbatim so scoring is identical.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]  # …/benchmarks/results/<dir>/file
sys.path.insert(0, str(REPO))

import mcp_server.infrastructure.embedding_fallback_provider as fp  # noqa: E402
from mcp_server.shared.algorithmic_embedding import (  # noqa: E402
    _MAX_OCCUR,
    _tokenize,
    _WINDOW,
    index_vector,
)
import json  # noqa: E402


def _tf_weights(tokens):
    counts = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    return {t: 1.0 + math.log(c) for t, c in counts.items()}


def embed_off(text: str, dim: int) -> np.ndarray:
    tokens = _tokenize(text)
    if not tokens:
        return np.zeros(dim, dtype=np.float32)
    tf = _tf_weights(tokens)
    cache = {t: index_vector(t, dim) for t in tf}
    acc = np.zeros(dim, dtype=np.float32)
    n = len(tokens)
    for i in range(0, n, 1):
        tok = tokens[i]
        w = tf[tok]
        acc += w * cache[tok]
        lo = max(0, i - _WINDOW)
        hi = min(n, i + _WINDOW + 1)
        for j in range(lo, hi):
            if j == i:
                continue
            acc += (w / abs(j - i)) * cache[tokens[j]]
    norm = float(np.linalg.norm(acc))
    if norm > 0.0:
        acc /= norm
    return acc.astype(np.float32)


def embed_current(text: str, dim: int) -> np.ndarray:
    tokens = _tokenize(text)
    if not tokens:
        return np.zeros(dim, dtype=np.float32)
    tf = _tf_weights(tokens)
    cache = {t: index_vector(t, dim) for t in tf}
    acc = np.zeros(dim, dtype=np.float32)
    n = len(tokens)
    stride = max(1, n // _MAX_OCCUR)
    for i in range(0, n, stride):
        tok = tokens[i]
        w = tf[tok]
        acc += w * cache[tok]
        lo = max(0, i - _WINDOW)
        hi = min(n, i + _WINDOW + 1)
        for j in range(lo, hi):
            if j == i:
                continue
            acc += (w / abs(j - i)) * cache[tokens[j]]
    norm = float(np.linalg.norm(acc))
    if norm > 0.0:
        acc /= norm
    return acc.astype(np.float32)


def embed_faithful_a(text: str, dim: int) -> np.ndarray:
    tokens = _tokenize(text)
    if not tokens:
        return np.zeros(dim, dtype=np.float32)
    tf = _tf_weights(tokens)
    cache = {t: index_vector(t, dim) for t in tf}
    n = len(tokens)
    acc = np.zeros(dim, dtype=np.float32)
    # First-order terms: always complete (CBM never subsamples these).
    for i in range(n):
        tok = tokens[i]
        acc += tf[tok] * cache[tok]
    # Co-occurrence pass: group occurrence positions per token; a token whose
    # within-document occurrence count exceeds _MAX_OCCUR has its occurrence
    # positions strided (CBM cooccur_sparse_one_target).
    positions: dict[str, list[int]] = {}
    for i, tok in enumerate(tokens):
        positions.setdefault(tok, []).append(i)
    for tok, occ in positions.items():
        step = 1
        if len(occ) > _MAX_OCCUR:
            step = len(occ) // _MAX_OCCUR
        w = tf[tok]
        for i in occ[::step]:
            lo = max(0, i - _WINDOW)
            hi = min(n, i + _WINDOW + 1)
            for j in range(lo, hi):
                if j == i:
                    continue
                acc += (w / abs(j - i)) * cache[tokens[j]]
    norm = float(np.linalg.norm(acc))
    if norm > 0.0:
        acc /= norm
    return acc.astype(np.float32)


VARIANTS = {
    "off": embed_off,
    "current": embed_current,
    "faithful_a": embed_faithful_a,
}


def main() -> None:
    import benchmarks.longmemeval.run_sqlite_fallback_bench as bench  # noqa: PLC0415 — deferred: module hard-imports pgvector/psycopg/psycopg_pool at top level; hoisting would break installs without it

    data_path = REPO / "benchmarks/longmemeval/longmemeval_s.json"
    dataset = json.loads(data_path.read_text())[:50]

    out = {}
    for name, fn in VARIANTS.items():
        fp.embed_text = fn  # patch the provider's bound reference
        print(f"[running] {name} over {len(dataset)} questions ...", flush=True)
        r = bench._eval_mode("fallback", dataset)
        out[name] = r
        print(
            f"  {name}: MRR={r['mrr']:.4f} R@10={r['recall10']:.4f} "
            f"elapsed={r['elapsed_s']}s",
            flush=True,
        )

    print("\n=== issue #184 subsampling comparison (LongMemEval-S, n=50) ===")
    print(f"{'variant':<14}{'MRR':>10}{'Recall@10':>12}{'elapsed':>10}")
    for name in VARIANTS:
        r = out[name]
        print(
            f"{name:<14}{r['mrr']:>10.4f}{r['recall10']:>11.1%}{r['elapsed_s']:>9.1f}s"
        )
    base = out["off"]
    for name in ("current", "faithful_a"):
        r = out[name]
        print(
            f"{name} vs off: dMRR={r['mrr'] - base['mrr']:+.4f} "
            f"dR@10={r['recall10'] - base['recall10']:+.1%}"
        )
    (Path(__file__).parent / "on-off-faithful-3way.json").write_text(
        json.dumps(out, indent=2)
    )


if __name__ == "__main__":
    main()
