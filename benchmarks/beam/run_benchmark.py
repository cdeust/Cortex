"""BEAM benchmark for Cortex memory system.

Runs the BEAM benchmark (Tavakoli et al., ICLR 2026) — "Beyond a Million Tokens:
Benchmarking and Enhancing Long-Term Memory in LLMs."
Uses the production PostgreSQL + pgvector retrieval pipeline.

10 memory abilities tested:
  1. Abstention — withhold answers when evidence is missing
  2. Contradiction Resolution — detect inconsistent statements
  3. Event Ordering — reconstruct sequences of evolving information
  4. Information Extraction — recall entities and factual details
  5. Instruction Following — sustain adherence to constraints
  6. Knowledge Update — revise facts as new information emerges
  7. Multi-hop Reasoning — integrate evidence across non-adjacent segments
  8. Preference Following — adapt to evolving user preferences
  9. Summarization — abstract and compress dialogue content
  10. Temporal Reasoning — reason about time relations

Run:
    python3 benchmarks/beam/run_benchmark.py [--split 100K] [--limit N]
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

from benchmarks.beam.data import (
    extract_10m_chat,
    extract_conversation_turns,
    load_beam_dataset,
    parse_probing_questions,
    turns_to_memories,
)
from benchmarks.lib.bench_db import BenchmarkDB


# ── Evaluation ───────────────────────────────────────────────────────────


def _current_stage_for_question(
    q: dict, conversation_turns: list[dict]
) -> str:
    """Determine the stage ID the question is about.

    Must match the stage_id used in data.turns_to_memories when tagging
    memories' agent_context. For 10M: plan_id (e.g. "plan-0") takes
    precedence over time_anchor. For 100K/500K/1M: time_anchor is the
    stage boundary.
    """
    raw_ids = q.get("source_chat_ids", [])
    src_ids: set[int] = set()
    if isinstance(raw_ids, dict):
        for v in raw_ids.values():
            if isinstance(v, list):
                src_ids.update(v)
    elif isinstance(raw_ids, list):
        src_ids = {i for i in raw_ids if isinstance(i, int)}

    # Walk conversation, track both plan_id and time_anchor.
    # Return whichever the first source turn carries — matches
    # turns_to_memories' priority: plan_id > time_anchor > "stage-0".
    last_anchor = "stage-0"
    last_plan = ""
    for turn in conversation_turns:
        a = turn.get("time_anchor", "")
        p = turn.get("plan_id", "")
        if a:
            last_anchor = a
        if p:
            last_plan = p
        if turn.get("id") in src_ids:
            # Match turns_to_memories priority: plan_id > anchor
            return last_plan if last_plan else last_anchor
    return last_plan if last_plan else last_anchor


def evaluate_retrieval(
    db: BenchmarkDB,
    questions: dict,
    conversation_turns: list[dict],
    mem_ids: list[int],
) -> dict[str, dict]:
    """Evaluate retrieval quality per ability."""
    results: dict[str, list[dict]] = defaultdict(list)

    for ability, qs in questions.items():
        if not isinstance(qs, list):
            qs = [qs]

        for q in qs:
            if not isinstance(q, dict):
                continue

            query = q.get("question", "")
            if not query:
                continue

            # Flatten source_ids: may be list[int] or dict of lists
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

            # Abstention: no source_ids by design — still evaluate
            if not source_ids and ability != "abstention":
                continue

            # Optional: use the structured 3-phase context assembler
            # instead of flat top-k WRRF. Gated by env var so we can A/B
            # on the same benchmark without touching the production code.
            if os.environ.get("CORTEX_USE_ASSEMBLER") == "1":
                # Benchmark has no LLM reader: token_budget=None means
                # pure rank-based retrieval (Swift pattern: budget is
                # caller-provided from reasoner.contextWindowSize when
                # a reader exists; benchmarks have no reader).
                bstr = os.environ.get("CORTEX_ASSEMBLER_BUDGET")
                tbudget: int | None = int(bstr) if bstr else None
                asm = db.assemble_context(
                    query=query,
                    current_stage=f"beam:{_current_stage_for_question(q, conversation_turns)}",
                    token_budget=tbudget,
                    stage_field="agent_context",
                )
                retrieved = asm["selected_memories"]
            else:
                retrieved = db.recall(query, top_k=10, domain="beam")

            answer = q.get("answer", "")

            # Build source content set from turn IDs.
            # Match strategy: 80-char prefix of source turns compared against
            # retrieved content. This is an engineering heuristic — BEAM paper
            # evaluates via LLM-as-judge on full QA, not retrieval matching.
            # We use prefix matching as a proxy for retrieval quality since we
            # evaluate retrieval only (no LLM judge). The 80-char threshold
            # balances specificity (longer = fewer false positives) against
            # robustness (shorter = tolerates prefix variations).
            source_contents = set()
            for turn in conversation_turns:
                turn_id = turn.get("id", -1)
                if turn_id in source_ids:
                    text = turn.get("content", "")
                    if text and len(text) > 10:
                        source_contents.add(text[:80].lower())

            # Find rank of first hit
            hit_rank = None
            answer_lower = answer.lower().strip() if answer else ""

            if ability == "abstention":
                # Abstention: success = retrieval returns no confident match.
                # Threshold 0.3 is an engineering heuristic — BEAM paper uses
                # LLM-as-judge to evaluate abstention quality. We approximate
                # by checking if top retrieval score is low (indicating the
                # system correctly found nothing relevant). Needs calibration
                # against actual abstention accuracy.
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

            results[ability].append(
                {
                    "query": query,
                    "hit_rank": hit_rank,
                    "retrieved_count": len(retrieved),
                    "source_ids": source_ids,
                }
            )

    # Compute metrics per ability
    metrics: dict[str, dict] = {}
    for ability, ability_results in results.items():
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


# ── Main Benchmark ───────────────────────────────────────────────────────


def run_benchmark(split: str = "100K", limit: int | None = None, verbose: bool = False):
    """Run BEAM retrieval benchmark using production PG retrieval."""
    print(f"Loading BEAM dataset (split={split})...")
    ds = load_beam_dataset(split)

    if limit:
        ds = ds.select(range(min(limit, len(ds))))

    print(f"Running benchmark on {len(ds)} conversations (PostgreSQL backend)...")

    all_metrics: dict[str, list[dict]] = defaultdict(list)
    total_start = time.time()

    with BenchmarkDB() as db:
        for conv_idx, conversation in enumerate(ds):
            conv_start = time.time()

            # BEAM-10M aggregates 10 sub-plans into one ~10M-token convo
            if split == "10M":
                chat = extract_10m_chat(conversation)
            else:
                chat = conversation.get("chat", "")
            turns = extract_conversation_turns(chat)
            memories = turns_to_memories(turns)

            if not memories:
                continue

            raw_pq = conversation.get("probing_questions", "{}")
            questions = parse_probing_questions(raw_pq)

            if not questions:
                continue

            # Clean up previous, load new
            db.clear()
            mem_ids, _source_map = db.load_memories(memories, domain="beam")

            metrics = evaluate_retrieval(db, questions, turns, mem_ids)

            for ability, m in metrics.items():
                all_metrics[ability].append(m)

            elapsed = time.time() - conv_start
            if (conv_idx + 1) % 5 == 0 or conv_idx == 0:
                total_q = sum(
                    m["total_questions"] for ms in all_metrics.values() for m in ms
                )
                avg_mrr = 0.0
                if all_metrics:
                    ability_mrrs = []
                    for ms in all_metrics.values():
                        if ms:
                            ability_mrrs.append(sum(m["mrr"] for m in ms) / len(ms))
                    if ability_mrrs:
                        avg_mrr = sum(ability_mrrs) / len(ability_mrrs)
                print(
                    f"  [{conv_idx + 1}/{len(ds)}] avg_MRR={avg_mrr:.3f} "
                    f"questions={total_q} ({elapsed:.1f}s/conv)"
                )

    total_time = time.time() - total_start

    # Report
    print()
    print("=" * 72)
    print("BEAM Benchmark Results — Cortex (PostgreSQL)")
    print("=" * 72)
    print()

    # LIGHT (LLM-as-judge QA) scores from Tavakoli et al., ICLR 2026
    # Table 2, "LIGHT" column, 100K split. These are full QA scores
    # (not retrieval-only) shown for reference comparison only.
    light_scores = {
        "abstention": 0.750,
        "contradiction_resolution": 0.050,
        "event_ordering": 0.266,
        "information_extraction": 0.375,
        "instruction_following": 0.500,
        "knowledge_update": 0.375,
        "multi_hop_reasoning": 0.135,
        "preference_following": 0.483,
        "summarization": 0.277,
        "temporal_reasoning": 0.075,
    }

    print(f"{'Ability':<28} {'MRR':>6} {'R@5':>6} {'R@10':>6} {'Qs':>4}  {'LIGHT':>6}")
    print("-" * 70)

    overall_mrr = []
    overall_r5 = []
    overall_r10 = []
    total_qs = 0

    for ability in sorted(all_metrics.keys()):
        ms = all_metrics[ability]
        if not ms:
            continue
        mrr = sum(m["mrr"] for m in ms) / len(ms)
        r5 = sum(m["recall_at_5"] for m in ms) / len(ms)
        r10 = sum(m["recall_at_10"] for m in ms) / len(ms)
        qs = sum(m["total_questions"] for m in ms)

        light = light_scores.get(ability, 0.0)

        print(
            f"{ability:<28} {mrr:>6.3f} {r5:>5.1%} {r10:>5.1%} {qs:>4}  {light:>6.3f}"
        )

        overall_mrr.append(mrr)
        overall_r5.append(r5)
        overall_r10.append(r10)
        total_qs += qs

    print("-" * 70)
    if overall_mrr:
        avg_mrr = sum(overall_mrr) / len(overall_mrr)
        avg_r5 = sum(overall_r5) / len(overall_r5)
        avg_r10 = sum(overall_r10) / len(overall_r10)
        light_overall = sum(light_scores.values()) / len(light_scores)
        print(
            f"{'OVERALL':<28} {avg_mrr:>6.3f} {avg_r5:>5.1%} {avg_r10:>5.1%} {total_qs:>4}  "
            f"{light_overall:>6.3f}"
        )

    print()
    print(
        f"Total time: {total_time:.1f}s ({total_time / max(len(ds), 1):.1f}s/conversation)"
    )
    print(f"Conversations: {len(ds)}, Split: {split}")
    print()
    print("Note: LIGHT scores are full QA (LLM-as-judge), not retrieval-only.")
    print("      Cortex scores here are retrieval MRR/Recall — not directly comparable")
    print("      but show retrieval quality that feeds downstream QA.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BEAM benchmark for Cortex")
    parser.add_argument(
        "--split",
        default="100K",
        choices=["100K", "500K", "1M", "10M"],
        help="Dataset split (default: 100K for fast testing)",
    )
    parser.add_argument("--limit", type=int, help="Limit number of conversations")
    parser.add_argument("--verbose", action="store_true", help="Show detailed results")
    args = parser.parse_args()

    run_benchmark(split=args.split, limit=args.limit, verbose=args.verbose)
