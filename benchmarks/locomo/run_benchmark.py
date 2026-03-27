"""LoCoMo benchmark runner for Cortex memory system.

LoCoMo (Maharana et al., ACL 2024): 10 conversations, 1,986 QA pairs, 5 categories.
Uses the production PostgreSQL + pgvector retrieval pipeline.

Run:
    python3 benchmarks/locomo/run_benchmark.py [--limit N] [--verbose]
"""

from __future__ import annotations

import argparse
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

from benchmarks.lib.bench_db import BenchmarkDB
from benchmarks.locomo.data import (
    CATEGORY_NAMES,
    extract_sessions,
    load_locomo,
    parse_evidence_refs,
)


# ── Evaluation ───────────────────────────────────────────────────────────


def evaluate_conversation(
    db: BenchmarkDB,
    sessions: list[dict],
    mem_ids: list[int],
    source_map: dict[int, str],
    qa_pairs: list[dict],
) -> dict[str, list[dict]]:
    """Evaluate retrieval for all QA pairs in one conversation."""
    # Map memory_id → session_idx via source provenance from ingestion
    mid_to_sidx: dict[int, int] = {}
    for mid, src in source_map.items():
        if src.startswith("session_"):
            try:
                mid_to_sidx[mid] = int(src.split("_", 1)[1])
            except (ValueError, IndexError):
                pass

    results: dict[str, list[dict]] = defaultdict(list)

    for qa in qa_pairs:
        question = qa["question"]
        evidence = qa.get("evidence", [])
        category = qa.get("category", 0)
        cat_name = CATEGORY_NAMES.get(category, f"unknown_{category}")

        refs = parse_evidence_refs(evidence)
        target_sessions = {ref[0] for ref in refs}
        if not target_sessions:
            continue

        retrieved = db.recall(question, top_k=10, domain="locomo")

        hit_rank = None
        for rank, r in enumerate(retrieved):
            sidx = mid_to_sidx.get(r["memory_id"])
            if sidx in target_sessions:
                hit_rank = rank + 1
                break

        results[cat_name].append(
            {
                "question": question,
                "hit_rank": hit_rank,
                "target_sessions": list(target_sessions),
            }
        )

    return results


# ── Reporting ────────────────────────────────────────────────────────────


def print_results(
    all_results: dict[str, list[dict]],
    total_time: float,
    n_convs: int,
):
    print()
    print("=" * 72)
    print("LoCoMo Benchmark Results — Cortex (PostgreSQL)")
    print("=" * 72)
    print()
    print(f"{'Category':<20} {'MRR':>6} {'R@5':>6} {'R@10':>6} {'Qs':>5}")
    print("-" * 55)

    overall_mrr_sum, overall_r5, overall_r10, overall_total = 0.0, 0, 0, 0

    for cat in ["single_hop", "multi_hop", "temporal", "open_domain", "adversarial"]:
        rs = all_results.get(cat, [])
        if not rs:
            continue
        mrr_sum = sum(1.0 / r["hit_rank"] for r in rs if r["hit_rank"])
        r5 = sum(1 for r in rs if r["hit_rank"] and r["hit_rank"] <= 5)
        r10 = sum(1 for r in rs if r["hit_rank"] and r["hit_rank"] <= 10)
        n = len(rs)
        print(f"{cat:<20} {mrr_sum / n:>6.3f} {r5 / n:>5.1%} {r10 / n:>5.1%} {n:>5}")
        overall_mrr_sum += mrr_sum
        overall_r5 += r5
        overall_r10 += r10
        overall_total += n

    print("-" * 55)
    if overall_total > 0:
        print(
            f"{'OVERALL':<20} {overall_mrr_sum / overall_total:>6.3f} "
            f"{overall_r5 / overall_total:>5.1%} {overall_r10 / overall_total:>5.1%} "
            f"{overall_total:>5}"
        )
    print(f"\nTotal time: {total_time:.1f}s")
    print(f"Conversations: {n_convs}, Questions: {overall_total}")


# ── Main ─────────────────────────────────────────────────────────────────


def run_benchmark(data_path: str, limit: int | None = None, verbose: bool = False):
    data = load_locomo(data_path)
    if limit:
        data = data[:limit]

    print(
        f"Running benchmark on {len(data)} conversations, "
        f"{sum(len(c['qa']) for c in data)} QA pairs (PostgreSQL backend)..."
    )

    all_results: dict[str, list[dict]] = defaultdict(list)
    total_start = time.time()

    with BenchmarkDB() as db:
        for conv_idx, conv in enumerate(data):
            sessions = extract_sessions(conv["conversation"])

            # Clean up previous conversation, load new sessions
            db.clear()
            memories = [
                {
                    "content": s["content"],
                    "user_content": s.get("user_content", ""),
                    "created_at": s.get("date", ""),
                    "source": f"session_{s['session_idx']}",
                    "tags": ["locomo"],
                }
                for s in sessions
            ]
            mem_ids, source_map = db.load_memories(memories, domain="locomo")

            conv_results = evaluate_conversation(
                db, sessions, mem_ids, source_map, conv["qa"]
            )
            for cat, rs in conv_results.items():
                all_results[cat].extend(rs)

            total_q = sum(len(rs) for rs in all_results.values())
            print(
                f"  [{conv_idx + 1}/{len(data)}] questions={total_q} "
                f"({time.time() - total_start:.1f}s)"
            )

    print_results(all_results, time.time() - total_start, len(data))

    if verbose:
        print("\nMissed questions (no hit in top 10):")
        for cat, rs in all_results.items():
            for m in [r for r in rs if not r["hit_rank"] or r["hit_rank"] > 10][:3]:
                print(f"  [{cat}] {m['question'][:80]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LoCoMo benchmark for Cortex")
    parser.add_argument("--limit", type=int, help="Limit conversations")
    parser.add_argument("--verbose", action="store_true", help="Show misses")
    args = parser.parse_args()

    data_dir = Path(__file__).parent
    data_path = data_dir / "locomo10.json"
    if not data_path.exists():
        print(f"Dataset not found at {data_path}")
        print("Download with:")
        print(
            f'  curl -sL -o {data_path} "https://huggingface.co/datasets/Percena/locomo-mc10/resolve/main/raw/locomo10.json"'
        )
        sys.exit(1)

    run_benchmark(str(data_path), limit=args.limit, verbose=args.verbose)
