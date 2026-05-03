"""LoCoMo benchmark runner for Cortex memory system.

LoCoMo (Maharana et al., ACL 2024): 10 conversations, 1,986 QA pairs, 5 categories.
Uses the production PostgreSQL + pgvector retrieval pipeline.

Run:
    python3 benchmarks/locomo/run_benchmark.py [--limit N] [--verbose]
                                               [--with-consolidation]
                                               [--ablate MECH]
                                               [--results-out PATH]
"""

from __future__ import annotations

import argparse
import asyncio
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


# ── Consolidation pass ────────────────────────────────────────────────────


def _run_consolidation_pass() -> float:
    """Invoke the production consolidate handler once. Returns wall seconds.

    Precondition: corpus already loaded into PG via BenchmarkDB; CORTEX_ABLATE_*
    env vars (if any) already set so the ablation guard fires inside the
    handler's stages.
    Postcondition: returns elapsed seconds.

    For LoCoMo this is invoked ONCE per conversation, after all sessions for
    that conversation are loaded and BEFORE QA evaluation — exercising
    consolidation across the just-loaded session set. Mirrors the LME-S
    "after load, before recall" pattern at the conversation grain (since
    LoCoMo evaluates a conversation's QA against its own multi-session
    haystack, not across conversations).
    """
    from mcp_server.handlers import consolidate as consolidate_handler

    t0 = time.monotonic()
    asyncio.run(consolidate_handler.handler({}))
    return time.monotonic() - t0


# ── Main ─────────────────────────────────────────────────────────────────


def run_benchmark(
    data_path: str,
    limit: int | None = None,
    verbose: bool = False,
    *,
    with_consolidation: bool = False,
    ablate_mechanism: str | None = None,
) -> dict:
    data = load_locomo(data_path)
    if limit:
        data = data[:limit]

    print(
        f"Running benchmark on {len(data)} conversations, "
        f"{sum(len(c['qa']) for c in data)} QA pairs (PostgreSQL backend)..."
    )
    if with_consolidation:
        print("  consolidation: ON (between session-load and QA, per conversation)")
    if ablate_mechanism:
        print(f"  ablation: CORTEX_ABLATE_{ablate_mechanism}=1")
    print()

    all_results: dict[str, list[dict]] = defaultdict(list)
    total_start = time.time()
    consolidation_total_wall_s = 0.0
    consolidation_call_count = 0

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

            # Consolidation pass between session-load and QA. Off by default to
            # preserve historical reproducibility. ON exercises the
            # consolidation-only mechanisms (CASCADE, INTERFERENCE,
            # HOMEOSTATIC_PLASTICITY, SYNAPTIC_PLASTICITY, MICROGLIAL_PRUNING,
            # TWO_STAGE_MODEL, EMOTIONAL_DECAY, TRIPARTITE_SYNAPSE,
            # SCHEMA_ENGINE) so per-mechanism ablation deltas become
            # attributable on the longitudinal benchmark.
            if with_consolidation:
                consolidation_total_wall_s += _run_consolidation_pass()
                consolidation_call_count += 1

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

    elapsed = time.time() - total_start
    print_results(all_results, elapsed, len(data))

    if verbose:
        print("\nMissed questions (no hit in top 10):")
        for cat, rs in all_results.items():
            for m in [r for r in rs if not r["hit_rank"] or r["hit_rank"] > 10][:3]:
                print(f"  [{cat}] {m['question'][:80]}")

    # Aggregate metrics for results-out / driver consumption.
    overall_mrr_sum = 0.0
    overall_r10 = 0
    overall_total = 0
    category_mrr: dict[str, float] = {}
    category_recall10: dict[str, float] = {}
    for cat, rs in all_results.items():
        if not rs:
            continue
        mrr_sum = sum(1.0 / r["hit_rank"] for r in rs if r["hit_rank"])
        r10 = sum(1 for r in rs if r["hit_rank"] and r["hit_rank"] <= 10)
        n = len(rs)
        category_mrr[cat] = mrr_sum / n
        category_recall10[cat] = r10 / n
        overall_mrr_sum += mrr_sum
        overall_r10 += r10
        overall_total += n

    overall_mrr = overall_mrr_sum / overall_total if overall_total else 0.0
    overall_recall10 = overall_r10 / overall_total if overall_total else 0.0

    if with_consolidation:
        avg_ms = (
            consolidation_total_wall_s / consolidation_call_count * 1000
            if consolidation_call_count
            else 0.0
        )
        print(
            f"Consolidation: {consolidation_call_count} calls, "
            f"total {consolidation_total_wall_s:.1f}s "
            f"(avg {avg_ms:.1f}ms/call) — excluded from per-question stats"
        )

    manifest = {
        "with_consolidation": with_consolidation,
        "ablate_mechanism": ablate_mechanism,
        "ablate_env_var": (
            f"CORTEX_ABLATE_{ablate_mechanism}=1" if ablate_mechanism else None
        ),
        "n_conversations": len(data),
        "n_questions": overall_total,
        "consolidation_call_count": consolidation_call_count,
        "consolidation_total_wall_s": consolidation_total_wall_s,
    }

    return {
        "overall_mrr": overall_mrr,
        "overall_recall10": overall_recall10,
        "category_mrr": category_mrr,
        "category_recall10": category_recall10,
        "elapsed_s": elapsed,
        "consolidation_total_wall_s": consolidation_total_wall_s,
        "consolidation_call_count": consolidation_call_count,
        "manifest": manifest,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LoCoMo benchmark for Cortex")
    parser.add_argument("--limit", type=int, help="Limit conversations")
    parser.add_argument("--verbose", action="store_true", help="Show misses")
    parser.add_argument(
        "--with-consolidation",
        action="store_true",
        help=(
            "After loading each conversation's sessions and BEFORE QA, invoke "
            "the production consolidate handler so consolidation-only "
            "mechanisms (CASCADE, INTERFERENCE, HOMEOSTATIC_PLASTICITY, "
            "SYNAPTIC_PLASTICITY, MICROGLIAL_PRUNING, TWO_STAGE_MODEL, "
            "EMOTIONAL_DECAY, TRIPARTITE_SYNAPSE, SCHEMA_ENGINE) are "
            "exercised. Required for honest per-mechanism ablation."
        ),
    )
    parser.add_argument(
        "--ablate",
        type=str,
        default=None,
        metavar="MECH",
        help=(
            "Set CORTEX_ABLATE_<MECH>=1 BEFORE consolidation and recall. "
            "MECH is the Mechanism enum NAME (e.g. CASCADE, RECONSOLIDATION, "
            "CO_ACTIVATION, ADAPTIVE_DECAY)."
        ),
    )
    parser.add_argument(
        "--results-out",
        type=str,
        default=None,
        help="Optional path to write the result+manifest JSON.",
    )
    args = parser.parse_args()

    # Export ablation env var BEFORE any handler/store import touches it. The
    # ablation.is_disabled reads os.environ on every call, so setting it here
    # is sufficient as long as we do it before run_benchmark.
    ablate_mech: str | None = None
    if args.ablate:
        ablate_mech = args.ablate.strip().upper()
        os.environ[f"CORTEX_ABLATE_{ablate_mech}"] = "1"

    data_dir = Path(__file__).parent
    data_path = data_dir / "locomo10.json"
    if not data_path.exists():
        print(f"Dataset not found at {data_path}")
        print("Download with:")
        print(
            f'  curl -sL -o {data_path} "https://huggingface.co/datasets/Percena/locomo-mc10/resolve/main/raw/locomo10.json"'
        )
        sys.exit(1)

    results = run_benchmark(
        str(data_path),
        limit=args.limit,
        verbose=args.verbose,
        with_consolidation=args.with_consolidation,
        ablate_mechanism=ablate_mech,
    )

    if args.results_out:
        out_path = Path(args.results_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"Results written to {out_path}")
