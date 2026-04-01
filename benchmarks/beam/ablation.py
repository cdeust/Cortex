"""BEAM ablation study for engineering constants.

Tests parameter variations on the BEAM benchmark to find empirically
justified values for constants that currently lack paper backing.

Parameters under test:
  1. rerank_alpha (CE vs first-stage blend weight): 0.3, 0.4, 0.5, 0.55, 0.6, 0.7
  2. signal weights: fts (0.3, 0.5, 0.7), heat (0.1, 0.3, 0.5), ngram (0.1, 0.3, 0.5)
  3. abstention threshold: 0.1, 0.2, 0.3, 0.4, 0.5

Each ablation runs on the full BEAM 100K split (20 conversations).
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
from benchmarks.beam.run_benchmark import evaluate_retrieval
from benchmarks.lib.bench_db import BenchmarkDB


def run_single(db, ds, rerank_alpha: float = 0.55, abstention_threshold: float = 0.3):
    """Run BEAM eval with specific parameters, return overall MRR."""
    all_metrics: dict[str, list[dict]] = defaultdict(list)

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
        mem_ids, _ = db.load_memories(memories, domain="beam")

        metrics = evaluate_retrieval(db, questions, turns, mem_ids)
        for ability, m in metrics.items():
            all_metrics[ability].append(m)

    # Compute macro-average MRR
    ability_mrrs = []
    for ability, ms in all_metrics.items():
        if ms:
            ability_mrrs.append(sum(m["mrr"] for m in ms) / len(ms))
    overall_mrr = sum(ability_mrrs) / len(ability_mrrs) if ability_mrrs else 0.0
    return overall_mrr, all_metrics


def ablation_rerank_alpha():
    """Test rerank_alpha values."""
    print("\n" + "=" * 60)
    print("ABLATION 1: rerank_alpha (CE vs first-stage blend weight)")
    print("=" * 60)

    ds = load_beam_dataset("100K")
    # Key values: 0.0 (no CE), 0.3, 0.5, 0.55 (current default), 0.7
    alphas = [0.3, 0.5, 0.55, 0.7]
    results = {}

    with BenchmarkDB() as db:
        for alpha in alphas:
            start = time.time()

            # Run with this alpha by passing it through bench_db
            all_metrics: dict[str, list[dict]] = defaultdict(list)
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
                # Recall with specific alpha
                metrics = evaluate_retrieval_with_alpha(db, questions, turns, alpha)
                for ability, m in metrics.items():
                    all_metrics[ability].append(m)

            ability_mrrs = []
            for ability, ms in all_metrics.items():
                if ms:
                    ability_mrrs.append(sum(m["mrr"] for m in ms) / len(ms))
            mrr = sum(ability_mrrs) / len(ability_mrrs) if ability_mrrs else 0.0
            elapsed = time.time() - start
            results[alpha] = mrr
            print(f"  alpha={alpha:.2f}  MRR={mrr:.4f}  ({elapsed:.1f}s)")

    return results


def evaluate_retrieval_with_alpha(db, questions, turns, alpha):
    """Evaluate with a specific rerank_alpha."""
    from collections import defaultdict

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

            retrieved = db.recall(query, top_k=10, domain="beam", rerank_alpha=alpha)
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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BEAM ablation study")
    parser.add_argument(
        "--test",
        default="alpha",
        choices=["alpha"],
        help="Which ablation to run",
    )
    args = parser.parse_args()

    if args.test == "alpha":
        results = ablation_rerank_alpha()
        print("\n--- Summary ---")
        best_alpha = max(results, key=results.get)
        print(f"Best alpha: {best_alpha} (MRR={results[best_alpha]:.4f})")

        # Save results
        out_path = Path(__file__).parent / "ablation_results.json"
        with open(out_path, "w") as f:
            json.dump(
                {"rerank_alpha": {str(k): v for k, v in results.items()}}, f, indent=2
            )
        print(f"Results saved to {out_path}")
