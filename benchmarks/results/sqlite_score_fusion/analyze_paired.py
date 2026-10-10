"""Paired bootstrap over the JSONL of sqlite_fusion_paired.py.

Usage: python analyze_paired.py paired_n500.jsonl summary.json

source: percentile bootstrap, 10 000 resamples of questions, seed 20260924
"""

from __future__ import annotations

import json
import sys
from collections import Counter

import numpy as np

RESAMPLES = 10_000  # source: task specification
SEED = 20260924  # source: task specification
PRIMARY = ("rrf_rerank1", "score_rerank1")  # source: production pipeline arms
CONTROL = ("rrf_rerank0", "score_rerank0")  # source: first-stage-only arms
PG_N50 = {"mrr": 0.867, "recall10": 0.98}  # source: measured, same 50 questions
PG_N500 = {"mrr": 0.905, "recall10": 0.978}  # source: README v4.20.0 (unpaired)


def _ci(values: np.ndarray, indices: np.ndarray) -> list[float]:
    means = values[indices].mean(axis=1)
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


def _arm(records: list[dict], arm: str, key: str) -> np.ndarray:
    return np.array([r["arms"][arm][key] for r in records], dtype=float)


def _summarise(records: list[dict], indices: np.ndarray) -> dict:
    out: dict = {"n": len(records)}
    for arm in PRIMARY + CONTROL:
        out[arm] = {}
        for key in ("mrr", "recall10"):
            v = _arm(records, arm, key)
            out[arm][key] = {"mean": float(v.mean()), "ci95": _ci(v, indices)}
    for base, new in (PRIMARY, CONTROL):
        for key in ("mrr", "recall10"):
            d = _arm(records, new, key) - _arm(records, base, key)
            out[f"paired_{new}_minus_{base}_{key}"] = {
                "mean": float(d.mean()),
                "ci95": _ci(d, indices),
                "wins": int((d > 0).sum()),
                "losses": int((d < 0).sum()),
            }
    return out


def main(path: str, dest: str) -> None:
    records = [json.loads(line) for line in open(path)]
    records.sort(key=lambda r: r["index"])
    rng = np.random.default_rng(SEED)
    result: dict = {"resamples": RESAMPLES, "seed": SEED}
    subsets = {"first_50": records[:50], "all": records}
    for name, subset in subsets.items():
        indices = rng.integers(0, len(subset), size=(RESAMPLES, len(subset)))
        result[name] = _summarise(subset, indices)
    result["pg_reference"] = {
        "n50_paired_with_first_50": PG_N50,
        "n500_unpaired": PG_N500,
    }
    categories = sorted({r["question_type"] for r in records})
    result["category_counts"] = dict(Counter(r["question_type"] for r in records))
    result["by_category"] = {}
    for category in categories:
        subset = [r for r in records if r["question_type"] == category]
        indices = rng.integers(0, len(subset), size=(RESAMPLES, len(subset)))
        result["by_category"][category] = _summarise(subset, indices)
    json.dump(result, open(dest, "w"), indent=2)
    print(json.dumps({k: result[k] for k in ("first_50", "all")}, indent=2))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
