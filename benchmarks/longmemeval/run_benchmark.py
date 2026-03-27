"""LongMemEval benchmark for Cortex memory system.

Runs the LongMemEval benchmark (Wu et al., ICLR 2025) against the
production PostgreSQL + pgvector retrieval pipeline. 500 questions
across 6 categories, each embedded in ~50 sessions (~115k tokens).

Methodology:
  1. For each question, load all haystack sessions into PostgreSQL
     via BenchmarkDB (one memory per session, with full content).
  2. Set timestamps to match the original session dates.
  3. Run production recall_memories() PL/pgSQL + FlashRank reranking.
  4. Check if retrieved results contain the answer session(s).
  5. Compute MRR and Recall@K at session level.

Run:
    python3 benchmarks/longmemeval/run_benchmark.py [--limit N] [--variant oracle|s]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Force CPU — Metal GPU backend crashes on macOS with validation assertions
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from benchmarks.lib.bench_db import BenchmarkDB


# ── Date Parsing ─────────────────────────────────────────────────────────────


def parse_longmemeval_date(date_str: str) -> str:
    """Parse LongMemEval date format '2023/04/10 (Mon) 17:50' to ISO 8601."""
    try:
        cleaned = re.sub(r"\s*\(\w+\)\s*", " ", date_str).strip()
        dt = datetime.strptime(cleaned, "%Y/%m/%d %H:%M")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).isoformat()


# ── Session to Memory Conversion ────────────────────────────────────────────


def session_to_memory_content(session: list[dict], session_id: str) -> tuple[str, str]:
    """Convert a conversation session to memory strings.

    Returns (full_content, user_only_content).
    """
    parts = []
    user_parts = []
    for turn in session:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        parts.append(f"[{role}]: {content}")
        if role == "user":
            user_parts.append(content)
    return "\n".join(parts), "\n".join(user_parts)


def compute_heat_with_decay(
    date_iso: str,
    query_date_iso: str,
    fast_factor: float = 0.995,
    fast_hours: float = 168,
    slow_factor: float = 0.999,
) -> float:
    """Two-phase heat decay: fast initial, slow tail."""
    try:
        mem_dt = datetime.fromisoformat(date_iso)
        query_dt = datetime.fromisoformat(query_date_iso)
        hours = max(0, (query_dt - mem_dt).total_seconds() / 3600.0)
        if hours <= fast_hours:
            return fast_factor**hours
        base = fast_factor**fast_hours
        return base * (slow_factor ** (hours - fast_hours))
    except (ValueError, TypeError):
        return 0.5


# ── Metrics ──────────────────────────────────────────────────────────────────


def compute_mrr(
    retrieved_session_ids: list[str], answer_session_ids: list[str]
) -> float:
    """MRR = 1 / rank_of_first_relevant_result."""
    answer_set = set(answer_session_ids)
    for rank, sid in enumerate(retrieved_session_ids, 1):
        if sid in answer_set:
            return 1.0 / rank
    return 0.0


def recall_at_k_binary(
    retrieved_session_ids: list[str], answer_session_ids: list[str], k: int = 10
) -> float:
    """Binary Recall@K — did we find at least one relevant session in top K?"""
    answer_set = set(answer_session_ids)
    for sid in retrieved_session_ids[:k]:
        if sid in answer_set:
            return 1.0
    return 0.0


# ── Main Benchmark ───────────────────────────────────────────────────────────


def run_benchmark(data_path: str, limit: int = 0, verbose: bool = False) -> dict:
    """Run the full LongMemEval benchmark using production PG retrieval."""

    print(f"Loading dataset from {data_path}...")
    with open(data_path) as f:
        dataset = json.load(f)

    if limit > 0:
        dataset = dataset[:limit]

    print(f"Running benchmark on {len(dataset)} questions (PostgreSQL backend)...")
    print()

    # Per-category metrics
    category_mrr: dict[str, list[float]] = defaultdict(list)
    category_recall10: dict[str, list[float]] = defaultdict(list)

    all_mrr: list[float] = []
    all_recall10: list[float] = []

    t0 = time.monotonic()

    with BenchmarkDB() as db:
        for qi, item in enumerate(dataset):
            qtype = item["question_type"]
            question = item["question"]
            answer = item["answer"]
            question_date = parse_longmemeval_date(item["question_date"])
            answer_sids = item["answer_session_ids"]
            haystack_sessions = item["haystack_sessions"]
            haystack_sids = item["haystack_session_ids"]
            haystack_dates = item["haystack_dates"]

            category_map = {
                "single-session-user": "Single-session (user)",
                "single-session-assistant": "Single-session (assistant)",
                "single-session-preference": "Single-session (preference)",
                "multi-session": "Multi-session reasoning",
                "temporal-reasoning": "Temporal reasoning",
                "knowledge-update": "Knowledge updates",
            }
            category = category_map.get(qtype, qtype)

            # Clean up previous question's data, load new haystack
            db.clear()

            memories = []
            for si, (session, sid, date_str) in enumerate(
                zip(haystack_sessions, haystack_sids, haystack_dates)
            ):
                content, user_content = session_to_memory_content(session, sid)
                date_iso = parse_longmemeval_date(date_str)
                heat = compute_heat_with_decay(date_iso, question_date)

                memories.append(
                    {
                        "content": content,
                        "user_content": user_content,
                        "created_at": date_iso,
                        "heat": heat,
                        "source": sid,
                        "tags": [qtype],
                    }
                )

            mem_ids, source_map = db.load_memories(memories, domain="longmemeval")

            # Run production retrieval
            results = db.recall(question, top_k=10, domain="longmemeval")
            retrieved_sids = [source_map.get(r["memory_id"], "") for r in results]

            # Compute metrics
            mrr = compute_mrr(retrieved_sids, answer_sids)
            r10 = recall_at_k_binary(retrieved_sids, answer_sids)

            all_mrr.append(mrr)
            all_recall10.append(r10)
            category_mrr[category].append(mrr)
            category_recall10[category].append(r10)

            if verbose and mrr == 0:
                print(f"  MISS [{qtype}] Q: {question[:80]}")
                print(f"       A: {answer[:80]}")
                print(f"       Expected: {answer_sids[:3]}")
                print(f"       Got: {retrieved_sids[:3]}")
                print()

            if (qi + 1) % 50 == 0:
                elapsed = time.monotonic() - t0
                print(
                    f"  [{qi + 1}/{len(dataset)}] "
                    f"MRR={sum(all_mrr) / len(all_mrr):.3f} "
                    f"R@10={sum(all_recall10) / len(all_recall10):.3f} "
                    f"({elapsed:.1f}s)"
                )

    elapsed = time.monotonic() - t0

    # Compute aggregates
    overall_mrr = sum(all_mrr) / len(all_mrr) if all_mrr else 0.0
    overall_recall10 = sum(all_recall10) / len(all_recall10) if all_recall10 else 0.0

    print()
    print("=" * 72)
    print("LongMemEval Benchmark Results — Cortex (PostgreSQL)")
    print("=" * 72)
    print()

    print(f"{'Metric':<25} {'Cortex':>10} {'Best in paper':>14}")
    print("-" * 50)
    print(f"{'Recall@10':<25} {overall_recall10:>9.1%} {'78.4%':>14}")
    print(f"{'MRR':<25} {overall_mrr:>10.3f} {'--':>14}")
    print()

    print(f"{'Category':<30} {'MRR':>8} {'R@10':>8}")
    print("-" * 48)

    for cat in [
        "Single-session (user)",
        "Single-session (assistant)",
        "Single-session (preference)",
        "Multi-session reasoning",
        "Temporal reasoning",
        "Knowledge updates",
    ]:
        mrrs = category_mrr.get(cat, [])
        r10s = category_recall10.get(cat, [])
        if not mrrs:
            continue
        cat_mrr = sum(mrrs) / len(mrrs)
        cat_r10 = sum(r10s) / len(r10s)
        print(f"{cat:<30} {cat_mrr:>7.3f} {cat_r10:>8.3f}")

    print()
    print(
        f"Total time: {elapsed:.1f}s ({elapsed / len(dataset) * 1000:.1f}ms/question)"
    )
    print(f"Questions: {len(dataset)}")
    print()

    return {
        "overall_mrr": overall_mrr,
        "overall_recall10": overall_recall10,
        "category_mrr": {k: sum(v) / len(v) for k, v in category_mrr.items()},
        "category_recall10": {k: sum(v) / len(v) for k, v in category_recall10.items()},
        "elapsed_s": elapsed,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LongMemEval benchmark on Cortex")
    parser.add_argument(
        "--limit", type=int, default=0, help="Limit to N questions (0=all)"
    )
    parser.add_argument(
        "--variant",
        choices=["oracle", "s"],
        default="s",
        help="Dataset variant: oracle (evidence only) or s (~40 sessions)",
    )
    parser.add_argument("--verbose", action="store_true", help="Show missed questions")
    args = parser.parse_args()

    data_dir = Path(__file__).parent
    if args.variant == "oracle":
        data_path = data_dir / "longmemeval_oracle.json"
    else:
        data_path = data_dir / "longmemeval_s.json"

    if not data_path.exists():
        print(f"Dataset not found at {data_path}")
        print("Download with:")
        print(
            f'  curl -sL -o {data_path} "https://huggingface.co/datasets/xiaowu0162/LongMemEval/resolve/main/longmemeval_{args.variant}"'
        )
        sys.exit(1)

    results = run_benchmark(str(data_path), limit=args.limit, verbose=args.verbose)
