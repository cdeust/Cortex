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
import asyncio
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

from benchmarks._repro import build_repro_manifest, multi_run_stats
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


def _run_consolidation_pass() -> float:
    """Invoke the production consolidate handler once. Returns wall seconds.

    Precondition: corpus already loaded into PG via BenchmarkDB; CORTEX_ABLATE_*
    env vars (if any) already set so the ablation guard fires inside the
    handler's stages.
    Postcondition: returns elapsed seconds; raises only on hard handler errors.
    Source: handler defaults run decay+plasticity+pruning, compress, cls,
    memify, cascade, homeostatic, emergence — exactly the consolidation-only
    mechanisms the Feynman audit identified as never-exercised on LME-S.
    """
    # Imported lazily so callers that never pass --with-consolidation don't
    # incur the import cost (and can't be broken by handler-side changes).
    from mcp_server.handlers import consolidate as consolidate_handler

    t0 = time.monotonic()
    asyncio.run(consolidate_handler.handler({}))
    return time.monotonic() - t0


def run_benchmark(
    data_path: str,
    limit: int = 0,
    verbose: bool = False,
    *,
    with_consolidation: bool = False,
    ablate_mechanism: str | None = None,
    n_runs: int = 1,
) -> dict:
    """Run the full LongMemEval benchmark using production PG retrieval.

    Precondition: PG schema initialized; if ``ablate_mechanism`` is given it
    must match a Mechanism enum NAME (e.g. "CASCADE");
    ``CORTEX_ABLATE_<NAME>=1`` must already be exported by caller (see
    __main__).  ``n_runs`` >= 1; default 1 preserves single-run behaviour.
    Postcondition: returns metric dict with keys: overall_mrr,
    overall_recall10, category_mrr, category_recall10, elapsed_s,
    consolidation_total_wall_s, consolidation_call_count, manifest.
    When n_runs > 1 the dict also contains ``runs_mrr`` and
    ``runs_recall10`` (per-run lists) and ``stats_mrr`` / ``stats_recall10``
    (mean, std, 95 % CI dicts from ``multi_run_stats``).
    Manifest fields include the reproducibility sidecar (git commit, library
    versions, platform, timestamp) and the with_consolidation flag so
    published scores cannot be mistaken for production-consolidation behaviour.
    """

    print(f"Loading dataset from {data_path}...")
    with open(data_path) as f:
        dataset = json.load(f)

    if limit > 0:
        dataset = dataset[:limit]

    print(f"Running benchmark on {len(dataset)} questions (PostgreSQL backend)...")
    if with_consolidation:
        print("  consolidation: ON (per-question warmup pass between load and recall)")
        print(
            "  WARNING: with_consolidation=True exercises 9 consolidation-only "
            "mechanisms. Scores are NOT comparable to consolidation=False runs."
        )
    else:
        print(
            "  consolidation: OFF — scores reflect retrieval WITHOUT consolidation "
            "mechanisms (CASCADE, INTERFERENCE, HOMEOSTATIC_PLASTICITY, etc.). "
            "Re-run with --with-consolidation for production-equivalent evaluation."
        )
    if ablate_mechanism:
        print(f"  ablation: CORTEX_ABLATE_{ablate_mechanism}=1")
    if n_runs > 1:
        print(f"  n_runs: {n_runs} (will report mean ± std and 95 % CI)")
    print()

    # Capture reproducibility sidecar once at benchmark start.
    repro = build_repro_manifest()

    # Per-run accumulators (outer list is runs; inner logic unchanged per run).
    runs_mrr: list[float] = []
    runs_recall10: list[float] = []

    # We track the last run's per-category breakdown for the printed report.
    final_category_mrr: dict[str, float] = {}
    final_category_recall10: dict[str, float] = {}
    final_elapsed = 0.0
    final_consolidation_total_wall_s = 0.0
    final_consolidation_call_count = 0

    for run_idx in range(n_runs):
        if n_runs > 1:
            print(f"--- Run {run_idx + 1}/{n_runs} ---")

        # Per-category metrics (reset each run)
        category_mrr_run: dict[str, list[float]] = defaultdict(list)
        category_recall10_run: dict[str, list[float]] = defaultdict(list)

        all_mrr: list[float] = []
        all_recall10: list[float] = []

        consolidation_total_wall_s = 0.0
        consolidation_call_count = 0

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

                # Consolidation warmup pass (Feynman audit fix). Off by default to
                # preserve historical run reproducibility. When ON, exercises the 9
                # consolidation-only mechanisms (CASCADE, INTERFERENCE,
                # HOMEOSTATIC_PLASTICITY, SYNAPTIC_PLASTICITY, MICROGLIAL_PRUNING,
                # TWO_STAGE_MODEL, EMOTIONAL_DECAY, TRIPARTITE_SYNAPSE, SCHEMA_ENGINE)
                # so per-mechanism ablation deltas become attributable on LME-S.
                # Wall time tracked separately so per-question stats stay clean.
                if with_consolidation:
                    consolidation_total_wall_s += _run_consolidation_pass()
                    consolidation_call_count += 1

                # Run production retrieval
                results = db.recall(question, top_k=10, domain="longmemeval")
                retrieved_sids = [source_map.get(r["memory_id"], "") for r in results]

                # Compute metrics
                mrr = compute_mrr(retrieved_sids, answer_sids)
                r10 = recall_at_k_binary(retrieved_sids, answer_sids)

                all_mrr.append(mrr)
                all_recall10.append(r10)
                category_mrr_run[category].append(mrr)
                category_recall10_run[category].append(r10)

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

        overall_mrr_run = sum(all_mrr) / len(all_mrr) if all_mrr else 0.0
        overall_recall10_run = (
            sum(all_recall10) / len(all_recall10) if all_recall10 else 0.0
        )

        runs_mrr.append(overall_mrr_run)
        runs_recall10.append(overall_recall10_run)

        # Keep the last run's breakdown for the final report.
        final_category_mrr = {k: sum(v) / len(v) for k, v in category_mrr_run.items()}
        final_category_recall10 = {
            k: sum(v) / len(v) for k, v in category_recall10_run.items()
        }
        final_elapsed = elapsed
        final_consolidation_total_wall_s = consolidation_total_wall_s
        final_consolidation_call_count = consolidation_call_count

    # Aggregate across runs
    overall_mrr = runs_mrr[-1] if runs_mrr else 0.0
    overall_recall10 = runs_recall10[-1] if runs_recall10 else 0.0
    stats_mrr = multi_run_stats(runs_mrr)
    stats_recall10 = multi_run_stats(runs_recall10)

    print()
    print("=" * 72)
    print("LongMemEval Benchmark Results — Cortex (PostgreSQL)")
    print("=" * 72)
    print()

    if n_runs > 1:
        mrr_display = stats_mrr["mean"]
        r10_display = stats_recall10["mean"]
        mrr_label = f"{mrr_display:.3f} ±{stats_mrr['std']:.3f} (n={n_runs})"
        r10_label = f"{r10_display:.1%} ±{stats_recall10['std']:.3f} (n={n_runs})"
        print(f"{'Metric':<25} {'Cortex (mean ± std)':>22} {'Best in paper':>14}")
        print("-" * 62)
        print(f"{'Recall@10':<25} {r10_label:>22} {'78.4%':>14}")
        print(f"{'MRR':<25} {mrr_label:>22} {'--':>14}")
    else:
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
        cat_mrr_val = final_category_mrr.get(cat)
        cat_r10_val = final_category_recall10.get(cat)
        if cat_mrr_val is None:
            continue
        print(f"{cat:<30} {cat_mrr_val:>7.3f} {cat_r10_val:>8.3f}")

    print()
    print(
        f"Total time: {final_elapsed:.1f}s "
        f"({final_elapsed / len(dataset) * 1000:.1f}ms/question)"
    )
    print(f"Questions: {len(dataset)}")
    if with_consolidation:
        avg_ms = (
            final_consolidation_total_wall_s / final_consolidation_call_count * 1000
            if final_consolidation_call_count
            else 0.0
        )
        print(
            f"Consolidation: {final_consolidation_call_count} calls, "
            f"total {final_consolidation_total_wall_s:.1f}s "
            f"(avg {avg_ms:.1f}ms/call) — excluded from per-question stats"
        )
    print()

    manifest = {
        # ── Experimental conditions (must be visible in every published score) ──
        "with_consolidation": with_consolidation,
        "with_consolidation_note": (
            None
            if with_consolidation
            else (
                "Scores collected with consolidation=False do NOT reflect "
                "production behaviour.  Consolidation-only mechanisms "
                "(CASCADE, INTERFERENCE, HOMEOSTATIC_PLASTICITY, "
                "SYNAPTIC_PLASTICITY, MICROGLIAL_PRUNING, TWO_STAGE_MODEL, "
                "EMOTIONAL_DECAY, TRIPARTITE_SYNAPSE, SCHEMA_ENGINE) are "
                "exercised only when with_consolidation=True.  "
                "Delta between the two conditions is unmeasured in this run."
            )
        ),
        "ablate_mechanism": ablate_mechanism,
        "ablate_env_var": (
            f"CORTEX_ABLATE_{ablate_mechanism}=1" if ablate_mechanism else None
        ),
        "n_questions": len(dataset),
        "n_runs": n_runs,
        "consolidation_call_count": final_consolidation_call_count,
        "consolidation_total_wall_s": final_consolidation_total_wall_s,
        # ── Reproducibility sidecar ──────────────────────────────────────────
        "repro": repro,
    }

    result: dict = {
        "overall_mrr": overall_mrr,
        "overall_recall10": overall_recall10,
        "category_mrr": final_category_mrr,
        "category_recall10": final_category_recall10,
        "elapsed_s": final_elapsed,
        "consolidation_total_wall_s": final_consolidation_total_wall_s,
        "consolidation_call_count": final_consolidation_call_count,
        "manifest": manifest,
    }
    if n_runs > 1:
        result["runs_mrr"] = runs_mrr
        result["runs_recall10"] = runs_recall10
        result["stats_mrr"] = stats_mrr
        result["stats_recall10"] = stats_recall10
    return result


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
    parser.add_argument(
        "--with-consolidation",
        action="store_true",
        help=(
            "After loading each question's haystack and BEFORE recall, invoke "
            "the production consolidate handler so consolidation-only "
            "mechanisms (CASCADE, INTERFERENCE, HOMEOSTATIC_PLASTICITY, "
            "SYNAPTIC_PLASTICITY, MICROGLIAL_PRUNING, TWO_STAGE_MODEL, "
            "EMOTIONAL_DECAY, TRIPARTITE_SYNAPSE, SCHEMA_ENGINE) are "
            "exercised. Off by default to preserve reproducibility of prior "
            "runs. Required for honest per-mechanism ablation on LME-S."
        ),
    )
    parser.add_argument(
        "--ablate",
        type=str,
        default=None,
        metavar="MECH",
        help=(
            "Set CORTEX_ABLATE_<MECH>=1 BEFORE consolidation and recall. MECH "
            "is the Mechanism enum NAME (e.g. CASCADE, SCHEMA_ENGINE, "
            "MICROGLIAL_PRUNING). Combine with --with-consolidation for "
            "consolidation-only mechanisms."
        ),
    )
    parser.add_argument(
        "--results-out",
        type=str,
        default=None,
        help="Optional path to write the result+manifest JSON.",
    )
    parser.add_argument(
        "--n-runs",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Repeat the full evaluation N times and report mean ± std and "
            "95 %% CI on MRR and Recall@10 (default: 1, preserves existing "
            "single-run behaviour)."
        ),
    )
    args = parser.parse_args()

    if args.n_runs < 1:
        parser.error("--n-runs must be >= 1")

    # Export ablation env var BEFORE any handler/store import touches it. The
    # consolidate handler imports its sub-modules at call time, but
    # mcp_server.core.ablation.is_disabled reads os.environ on every call, so
    # setting it here is sufficient as long as we do it before run_benchmark.
    ablate_mech: str | None = None
    if args.ablate:
        ablate_mech = args.ablate.strip().upper()
        os.environ[f"CORTEX_ABLATE_{ablate_mech}"] = "1"

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

    results = run_benchmark(
        str(data_path),
        limit=args.limit,
        verbose=args.verbose,
        with_consolidation=args.with_consolidation,
        ablate_mechanism=ablate_mech,
        n_runs=args.n_runs,
    )

    if args.results_out:
        out_path = Path(args.results_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"Results written to {out_path}")
