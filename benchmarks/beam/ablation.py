"""BEAM ablation study for engineering constants.

Tests parameter variations on the BEAM benchmark to find empirically
justified values for constants that currently lack paper backing.

Parameters under test:
  1. rerank_alpha: CE vs first-stage blend weight (completed: 0.70 optimal)
  2. signal_weights: fts, heat, ngram weight combinations
  3. gate_threshold: CE confidence gate for abstention

Each ablation runs on the full BEAM 100K split (20 conversations, 395 Qs).
Results are printed as a table and written to ablation_results.json.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.beam.data import (
    extract_conversation_turns,
    load_beam_dataset,
    parse_probing_questions,
    turns_to_memories,
)
from benchmarks.lib.bench_db import BenchmarkDB
from mcp_server.core.pg_recall import recall as pg_recall


def _evaluate_with_params(db, questions, turns, **recall_kwargs):
    """Evaluate retrieval with custom recall parameters."""
    results_data: dict[str, list[dict]] = defaultdict(list)

    for ability, qs in questions.items():
        if not isinstance(qs, list):
            qs = [qs]
        for q in qs:
            if not isinstance(q, dict):
                continue
            query = q.get("question", "")
            if not query:
                continue

            raw_ids = q.get("source_chat_ids", [])
            if isinstance(raw_ids, dict):
                source_ids = []
                for v in raw_ids.values():
                    if isinstance(v, list):
                        source_ids.extend(v)
                    elif isinstance(v, int):
                        source_ids.append(v)
            else:
                source_ids = raw_ids if isinstance(raw_ids, list) else []

            if not source_ids and ability != "abstention":
                continue

            # Use pg_recall directly with custom params
            retrieved = pg_recall(
                query=query,
                store=db._store,
                embeddings=db._embeddings,
                top_k=10,
                domain="beam",
                include_globals=False,
                **recall_kwargs,
            )
            answer = q.get("answer", "")

            source_contents = set()
            for turn in turns:
                turn_id = turn.get("id", -1)
                if turn_id in source_ids:
                    text = turn.get("content", "")
                    if text and len(text) > 10:
                        source_contents.add(text[:80].lower())

            hit_rank = None
            answer_lower = answer.lower().strip() if answer else ""

            if ability == "abstention":
                if not retrieved or retrieved[0].get("score", 0) < 0.3:
                    hit_rank = 1
            else:
                for rank, r in enumerate(retrieved):
                    content_lower = r["content"].lower()
                    if (
                        answer_lower
                        and len(answer_lower) > 2
                        and answer_lower in content_lower
                    ):
                        hit_rank = rank + 1
                        break
                    for src in source_contents:
                        if src and src in content_lower:
                            hit_rank = rank + 1
                            break
                    if hit_rank:
                        break

            results_data[ability].append(
                {
                    "query": query,
                    "hit_rank": hit_rank,
                    "retrieved_count": len(retrieved),
                    "source_ids": source_ids,
                }
            )

    metrics: dict[str, dict] = {}
    for ability, ability_results in results_data.items():
        mrr_sum = 0.0
        recall_at_5 = 0
        recall_at_10 = 0
        total = len(ability_results)
        for r in ability_results:
            rank = r["hit_rank"]
            if rank is not None:
                mrr_sum += 1.0 / rank
                if rank <= 5:
                    recall_at_5 += 1
                if rank <= 10:
                    recall_at_10 += 1
        metrics[ability] = {
            "mrr": mrr_sum / total if total > 0 else 0.0,
            "recall_at_5": recall_at_5 / total if total > 0 else 0.0,
            "recall_at_10": recall_at_10 / total if total > 0 else 0.0,
            "total_questions": total,
        }

    return metrics


def _run_ablation(ds, db, label, **recall_kwargs):
    """Run full BEAM eval with given params, return macro MRR + per-ability."""
    all_metrics: dict[str, list[dict]] = defaultdict(list)
    start = time.time()

    for conversation in ds:
        chat = conversation.get("chat", "")
        turns = extract_conversation_turns(chat)
        memories = turns_to_memories(turns)
        if not memories:
            continue
        raw_pq = conversation.get("probing_questions", "{}")
        questions = parse_probing_questions(raw_pq)
        if not questions:
            continue
        db.clear()
        db.load_memories(memories, domain="beam")
        metrics = _evaluate_with_params(db, questions, turns, **recall_kwargs)
        for ability, m in metrics.items():
            all_metrics[ability].append(m)

    ability_mrrs = {}
    for ability, ms in all_metrics.items():
        if ms:
            ability_mrrs[ability] = sum(m["mrr"] for m in ms) / len(ms)
    overall = sum(ability_mrrs.values()) / len(ability_mrrs) if ability_mrrs else 0.0
    elapsed = time.time() - start

    print(f"  {label:<40s}  MRR={overall:.4f}  ({elapsed:.0f}s)")
    for ab in sorted(ability_mrrs):
        print(f"    {ab:<30s} {ability_mrrs[ab]:.3f}")

    return {"overall": overall, "per_ability": ability_mrrs, "elapsed": elapsed}


def ablation_rerank_alpha(ds, db):
    """Test rerank_alpha values."""
    print("\n" + "=" * 60)
    print("ABLATION: rerank_alpha")
    print("=" * 60)

    results = {}
    for alpha in [0.3, 0.5, 0.55, 0.7]:
        r = _run_ablation(ds, db, f"alpha={alpha:.2f}", rerank_alpha=alpha)
        results[str(alpha)] = r["overall"]
    return results


def ablation_signal_weights(ds, db):
    """Test signal weight configurations.

    We test each signal independently while holding others at baseline.
    This isolates the contribution of each signal.

    Baseline: vector=1.0, fts=0.5, heat=0.3, ngram=0.3
    """
    print("\n" + "=" * 60)
    print("ABLATION: signal weights (one-at-a-time)")
    print("=" * 60)

    # Baseline first
    results = {}

    # The recall function computes weights internally via compute_pg_weights().
    # We can't override weights directly through the recall() API — the weights
    # are computed from intent classification. Instead, we'll test with rerank
    # disabled to isolate the PG fusion signal, then with rerank enabled.

    # Test FTS weight variations
    print("\n--- FTS weight ---")
    # We need to monkey-patch compute_pg_weights for this
    import mcp_server.core.pg_recall as pgr

    original_compute = pgr.compute_pg_weights

    for fts_w in [0.0, 0.3, 0.5, 0.7, 1.0]:
        label = f"fts={fts_w:.1f}"

        def make_patched(fts_val):
            def patched(intent, core_weights=None):
                w = original_compute(intent, core_weights)
                w["fts"] = fts_val
                w["ngram"] = fts_val * 0.6
                return w

            return patched

        pgr.compute_pg_weights = make_patched(fts_w)
        r = _run_ablation(ds, db, label, rerank_alpha=0.70)
        results[label] = r
        pgr.compute_pg_weights = original_compute

    # Test heat weight variations
    print("\n--- Heat weight ---")
    for heat_w in [0.0, 0.1, 0.3, 0.5, 0.7]:
        label = f"heat={heat_w:.1f}"

        def make_patched_heat(heat_val):
            def patched(intent, core_weights=None):
                w = original_compute(intent, core_weights)
                w["heat"] = heat_val
                return w

            return patched

        pgr.compute_pg_weights = make_patched_heat(heat_w)
        r = _run_ablation(ds, db, label, rerank_alpha=0.70)
        results[label] = r
        pgr.compute_pg_weights = original_compute

    # Test ngram ratio (relative to fts)
    print("\n--- Ngram ratio (ngram = fts * ratio) ---")
    for ratio in [0.0, 0.3, 0.6, 1.0]:
        label = f"ngram_ratio={ratio:.1f}"

        def make_patched_ngram(r):
            def patched(intent, core_weights=None):
                w = original_compute(intent, core_weights)
                w["ngram"] = w["fts"] * r
                return w

            return patched

        pgr.compute_pg_weights = make_patched_ngram(ratio)
        r = _run_ablation(ds, db, label, rerank_alpha=0.70)
        results[label] = r
        pgr.compute_pg_weights = original_compute

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BEAM ablation study")
    parser.add_argument(
        "--test",
        default="weights",
        choices=["alpha", "weights", "all"],
        help="Which ablation to run",
    )
    args = parser.parse_args()

    ds = load_beam_dataset("100K")

    with BenchmarkDB() as db:
        all_results = {}

        # Load existing results
        out_path = Path(__file__).parent / "ablation_results.json"
        if out_path.exists():
            with open(out_path) as f:
                all_results = json.load(f)

        if args.test in ("alpha", "all"):
            all_results["rerank_alpha"] = ablation_rerank_alpha(ds, db)

        if args.test in ("weights", "all"):
            weight_results = ablation_signal_weights(ds, db)
            # Flatten for JSON
            all_results["signal_weights"] = {
                k: {"overall": v["overall"], "per_ability": v["per_ability"]}
                for k, v in weight_results.items()
            }

        # Save
        with open(out_path, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\nResults saved to {out_path}")

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        if "signal_weights" in all_results:
            sw = all_results["signal_weights"]
            for k in sorted(sw, key=lambda x: sw[x]["overall"], reverse=True):
                print(f"  {k:<40s}  MRR={sw[k]['overall']:.4f}")
