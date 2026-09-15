"""Gate-precision benchmark — flat vs hierarchical write-gate novelty scoring.

source: ADR-0831
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Force CPU — Metal GPU backend crashes on macOS with validation assertions
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from benchmarks.lib.bench_db import BenchmarkDB
from mcp_server.hooks.wiring import wire_composition_root  # noqa: E402 — source: issue #560

wire_composition_root()

from mcp_server.core import write_gate_calibration  # noqa: E402
from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: E402
from mcp_server.handlers.remember_helpers import evaluate_gate  # noqa: E402

DATA_PATH = Path(__file__).parent.parent / "longmemeval" / "longmemeval_s.json"
RESULTS_DIR = Path(__file__).parent.parent / "results" / "gate_precision"

MIN_CHARS = 80  # build spec: only substantive messages
SEED_N = 150  # build spec: store-warming set
POS_N = 100  # build spec: held-out novel candidates
NEG_N = 100  # build spec: duplicate candidates
RNG_SEED = 0  # source: ADR-0831
PASS_BAND = 0.02  # source: ADR-0831
HIER_FLAG = "CORTEX_MEMORY_WRITE_GATE_HIERARCHICAL"


# ── Corpus extraction ────────────────────────────────────────────────────────


def extract_corpus(path: Path) -> list[str]:
    """Distinct message contents (>= MIN_CHARS) from LongMemEval-S.

    source: ADR-0831"""
    with open(path) as f:
        questions = json.load(f)
    seen_sessions: set[str] = set()
    seen_keys: set[str] = set()
    corpus: list[str] = []
    for q in questions:
        # strict=True: both lists come from the same haystack record and
        # are documented to correspond 1:1 by index.
        for sid, session in zip(
            q["haystack_session_ids"], q["haystack_sessions"], strict=True
        ):
            if sid in seen_sessions:
                continue
            seen_sessions.add(sid)
            for msg in session:
                content = (msg.get("content") or "").strip()
                if len(content) < MIN_CHARS:
                    continue
                key = " ".join(content.lower().split())
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                corpus.append(content)
    return corpus


def make_negative(seed_content: str, index: int) -> tuple[str, str]:
    """Deterministic duplicate of a stored seed entry.

    Round-robin over three trivial perturbation classes (build spec:
    exact + near-dup via trailing space / one synonym). All three are
    non-novel by definition.
    """
    cls = index % 3
    if cls == 0:
        return seed_content, "exact"
    if cls == 1:
        return seed_content + " ", "trailing_space"
    swapped = seed_content.replace(" and ", " plus ", 1)
    if swapped == seed_content:  # no " and " present — fall back
        return seed_content + " ", "trailing_space"
    return swapped, "synonym_swap"


def build_dataset(
    corpus: list[str],
) -> tuple[list[str], list[dict]]:
    """Split corpus into (seeds, shuffled labelled candidates)."""
    needed = SEED_N + POS_N
    if len(corpus) < needed:
        raise SystemExit(f"corpus too small: {len(corpus)} < {needed}")
    rng = random.Random(RNG_SEED)
    rng.shuffle(corpus)
    seeds = corpus[:SEED_N]
    positives = corpus[SEED_N : SEED_N + POS_N]
    candidates = [{"content": c, "label": 1, "kind": "novel"} for c in positives]
    for i in range(NEG_N):
        content, kind = make_negative(seeds[i], i)
        candidates.append({"content": content, "label": 0, "kind": kind})
    rng.shuffle(candidates)  # source: ADR-0831
    return seeds, candidates


# ── Mode execution ───────────────────────────────────────────────────────────


def _set_mode(mode: str) -> None:
    """Toggle the hierarchical flag and bust the settings/calibration caches.

    source: ADR-0831
    """

    if mode == "hierarchical":
        os.environ[HIER_FLAG] = "1"
    else:
        os.environ.pop(HIER_FLAG, None)
    get_memory_settings.cache_clear()
    write_gate_calibration.reset_all_states()


def run_mode(mode: str, seeds: list[str], candidates: list[dict]) -> list[dict]:
    """Seed a clean store, run evaluate_gate on every candidate."""

    _set_mode(mode)
    assert get_memory_settings().WRITE_GATE_HIERARCHICAL == (mode == "hierarchical")
    results: list[dict] = []
    with BenchmarkDB() as db:
        db.load_memories(
            [{"content": s, "source": "gateeval_seed"} for s in seeds],
            domain="gateeval",
            decompose=False,  # source: ADR-0831
        )
        for cand in candidates:
            emb = db._embeddings.encode(cand["content"])
            gate = evaluate_gate(
                cand["content"],
                tags=[],
                embedding=emb,
                force=False,
                store=db._store,
                emb_engine=db._embeddings,
                domain="gateeval",
            )
            results.append(
                {
                    "label": cand["label"],
                    "kind": cand["kind"],
                    "score": gate["score"],
                    "should_store": gate["should_store"],
                    "gate_reason": gate["gate_reason"],
                    "gate_threshold": gate["gate_threshold"],
                }
            )
    return results


# ── Metrics ──────────────────────────────────────────────────────────────────


def roc_auc(labels: list[int], scores: list[float]) -> float:
    """AUC via the rank-sum (Wilcoxon-Mann-Whitney) statistic.

    source: ADR-0831"""
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ValueError("need both classes")
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1  # 1-based average rank for the tie group
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    # strict=True: ranks has len(scores), and labels/scores are the
    # function's paired input (one label per score) by contract.
    rank_sum_pos = sum(r for r, lab in zip(ranks, labels, strict=True) if lab == 1)
    u_stat = rank_sum_pos - n_pos * (n_pos + 1) / 2
    return u_stat / (n_pos * n_neg)


def summarize(results: list[dict], default_threshold: float) -> dict:
    """AUC + accuracies + confusion for one mode."""
    labels = [r["label"] for r in results]
    scores = [r["score"] for r in results]
    auc = roc_auc(labels, scores)
    # source: ADR-0831
    tp = sum(1 for r in results if r["label"] == 1 and r["score"] >= default_threshold)
    fn = sum(1 for r in results if r["label"] == 1 and r["score"] < default_threshold)
    tn = sum(1 for r in results if r["label"] == 0 and r["score"] < default_threshold)
    fp = sum(1 for r in results if r["label"] == 0 and r["score"] >= default_threshold)

    # source: ADR-0831
    def is_bypass(r: dict) -> bool:
        return r["gate_reason"].startswith(("bypass", "forced"))

    bypassed = [r for r in results if is_bypass(r)]
    decided = [r for r in results if not is_bypass(r)]
    gate_correct = sum(1 for r in decided if int(r["should_store"]) == r["label"])
    by_kind: dict[str, dict] = {}
    for r in results:
        k = by_kind.setdefault(r["kind"], {"n": 0, "accepted_at_default": 0})
        k["n"] += 1
        k["accepted_at_default"] += int(r["score"] >= default_threshold)
    return {
        "auc": round(auc, 4),
        "accuracy_at_default_threshold": round((tp + tn) / len(results), 4),
        "confusion_at_default": {"tp": tp, "fn": fn, "tn": tn, "fp": fp},
        "gate_decision_accuracy_excl_bypass": (
            round(gate_correct / len(decided), 4) if decided else None
        ),
        "bypass_count": len(bypassed),
        "by_kind": by_kind,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA_PATH)
    args = parser.parse_args()

    default_threshold = get_memory_settings().WRITE_GATE_THRESHOLD
    corpus = extract_corpus(args.data)
    seeds, candidates = build_dataset(corpus)
    print(
        f"corpus={len(corpus)} distinct messages | seeds={len(seeds)} "
        f"candidates={len(candidates)} (pos={POS_N} neg={NEG_N})"
    )

    report: dict = {
        "benchmark": "gate_precision",
        "date": datetime.now(timezone.utc).isoformat(),
        "database_url": os.environ.get("DATABASE_URL", "<default>"),
        "rng_seed": RNG_SEED,
        "default_threshold": default_threshold,
        "modes": {},
    }
    for mode in ("flat", "hierarchical"):
        t0 = time.time()
        results = run_mode(mode, seeds, candidates)
        summary = summarize(results, default_threshold)
        summary["wall_seconds"] = round(time.time() - t0, 1)
        report["modes"][mode] = summary
        print(f"\n[{mode}] {json.dumps(summary, indent=2)}")

    auc_flat = report["modes"]["flat"]["auc"]
    auc_hier = report["modes"]["hierarchical"]["auc"]
    report["auc_delta"] = round(auc_hier - auc_flat, 4)
    report["pass"] = auc_hier >= auc_flat - PASS_BAND
    print(
        f"\nAUC flat={auc_flat:.4f}  hierarchical={auc_hier:.4f}  "
        f"delta={report['auc_delta']:+.4f}  "
        f"PASS={report['pass']} (band {PASS_BAND})"
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"results written to {out}")


if __name__ == "__main__":
    main()
