"""LoCoMo agent-topic benchmark — validates agent-scoped memory retrieval.

Same as run_benchmark.py but assigns agent_topics to memories based on
content classification, then uses scoped recall. Compares scoped vs
unscoped retrieval to measure whether agent_topic improves precision.

NOT an official benchmark — validates the agent_topic architecture.

Run:
    python3 benchmarks/locomo/run_benchmark_agents.py [--limit N]
"""

from __future__ import annotations

import argparse
import os
import re
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


# ── Topic classification ─────────────────────────────────────────────────

_TOPIC_PATTERNS: dict[str, re.Pattern] = {
    "relationships": re.compile(
        r"\b(friend|family|sister|brother|parent|partner|dating|"
        r"relationship|married|wedding|love|girlfriend|boyfriend|"
        r"adopted|adoption|support group|LGBTQ|identity)\b",
        re.IGNORECASE,
    ),
    "career": re.compile(
        r"\b(job|career|work|intern|graduate|degree|school|university|"
        r"research|study|profession|office|meeting|project|mentor|"
        r"counseling|therapy|workshop|education)\b",
        re.IGNORECASE,
    ),
    "hobbies": re.compile(
        r"\b(paint|art|craft|music|dance|yoga|hike|travel|book|read|"
        r"movie|game|sport|run|race|marathon|charity|garden|cook|"
        r"pottery|photography|tattoo)\b",
        re.IGNORECASE,
    ),
    "health": re.compile(
        r"\b(health|fitness|diet|exercise|sleep|stress|anxiety|"
        r"meditation|wellbeing|self.care|mental health|therapy|"
        r"hospital|doctor|sick|recover)\b",
        re.IGNORECASE,
    ),
}


def classify_topic(text: str) -> str:
    """Classify text into the best-matching topic."""
    scores: dict[str, int] = {}
    for topic, pattern in _TOPIC_PATTERNS.items():
        scores[topic] = len(pattern.findall(text))
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def classify_query_topic(question: str) -> str | None:
    """Classify a query into a topic. Returns None if ambiguous."""
    topic = classify_topic(question)
    return topic if topic != "general" else None


# ── Evaluation ───────────────────────────────────────────────────────────


def evaluate_conversation(
    db: BenchmarkDB,
    mem_ids: list[int],
    source_map: dict[int, str],
    topic_map: dict[int, str],
    qa_pairs: list[dict],
) -> dict[str, dict]:
    """Evaluate scoped vs unscoped retrieval."""
    mid_to_sidx: dict[int, int] = {}
    for mid, src in source_map.items():
        if src.startswith("session_"):
            try:
                mid_to_sidx[mid] = int(src.split("_", 1)[1])
            except (ValueError, IndexError):
                pass

    results = {"scoped": defaultdict(list), "unscoped": defaultdict(list)}

    for qa in qa_pairs:
        question = qa["question"]
        evidence = qa.get("evidence", [])
        category = qa.get("category", 0)
        cat_name = CATEGORY_NAMES.get(category, f"unknown_{category}")

        refs = parse_evidence_refs(evidence)
        target_sessions = {ref[0] for ref in refs}
        if not target_sessions:
            continue

        # Classify query topic for scoped recall
        query_topic = classify_query_topic(question)

        # Unscoped recall (baseline)
        retrieved_unscoped = db.recall(question, top_k=10, domain="locomo-agents")
        hit_unscoped = _find_hit(retrieved_unscoped, mid_to_sidx, target_sessions)

        # Scoped recall (agent topic)
        if query_topic:
            retrieved_scoped = db.recall(
                question, top_k=10, domain="locomo-agents", agent_topic=query_topic
            )
        else:
            retrieved_scoped = retrieved_unscoped  # No topic → same as unscoped
        hit_scoped = _find_hit(retrieved_scoped, mid_to_sidx, target_sessions)

        results["unscoped"][cat_name].append(hit_unscoped)
        results["scoped"][cat_name].append(hit_scoped)

    return results


def _find_hit(
    retrieved: list[dict], mid_to_sidx: dict[int, int], target_sessions: set[int]
) -> int | None:
    """Find rank of first hit in retrieved results."""
    for rank, r in enumerate(retrieved):
        sidx = mid_to_sidx.get(r["memory_id"])
        if sidx in target_sessions:
            return rank + 1
    return None


# ── Main ─────────────────────────────────────────────────────────────────


def run_benchmark(data_path: str, limit: int | None = None):
    data = load_locomo(data_path)
    if limit:
        data = data[:limit]

    print(f"Running agent-topic benchmark on {len(data)} conversations...")
    print(f"Topics: {list(_TOPIC_PATTERNS.keys())} + general\n")

    all_results = {"scoped": defaultdict(list), "unscoped": defaultdict(list)}
    total_start = time.time()

    with BenchmarkDB() as db:
        for conv_idx, conv in enumerate(data):
            sessions = extract_sessions(conv["conversation"])
            db.clear()

            # Classify each session by topic and assign as agent_context
            memories = []
            for s in sessions:
                topic = classify_topic(s["content"])
                memories.append(
                    {
                        "content": s["content"],
                        "user_content": s.get("user_content", ""),
                        "created_at": s.get("date", ""),
                        "source": f"session_{s['session_idx']}",
                        "tags": ["locomo-agents"],
                        "agent_context": topic,
                    }
                )

            mem_ids, source_map = db.load_memories(memories, domain="locomo-agents")

            # Build topic map for debugging
            topic_map = {
                mid: memories[i].get("agent_context", "")
                for i, mid in enumerate(mem_ids)
                if i < len(memories)
            }

            conv_results = evaluate_conversation(
                db, mem_ids, source_map, topic_map, conv["qa"]
            )

            for mode in ["scoped", "unscoped"]:
                for cat, hits in conv_results[mode].items():
                    all_results[mode][cat].extend(hits)

            elapsed = time.time() - total_start
            print(f"  [{conv_idx + 1}/{len(data)}] ({elapsed:.1f}s)")

    # Report
    print()
    print("=" * 80)
    print("LoCoMo Agent-Topic Benchmark — Scoped vs Unscoped Retrieval")
    print("=" * 80)
    print()
    print(f"{'Category':<20} {'Unscoped MRR':>14} {'Scoped MRR':>14} {'Delta':>10}")
    print("-" * 62)

    for cat in ["single_hop", "multi_hop", "temporal", "open_domain", "adversarial"]:
        unscoped = all_results["unscoped"].get(cat, [])
        scoped = all_results["scoped"].get(cat, [])
        if not unscoped:
            continue
        mrr_u = sum(1.0 / r for r in unscoped if r) / len(unscoped)
        mrr_s = sum(1.0 / r for r in scoped if r) / len(scoped)
        delta = mrr_s - mrr_u
        sign = "+" if delta >= 0 else ""
        print(f"{cat:<20} {mrr_u:>13.3f} {mrr_s:>13.3f} {sign}{delta:>9.3f}")

    # Overall
    all_u = [h for hits in all_results["unscoped"].values() for h in hits]
    all_s = [h for hits in all_results["scoped"].values() for h in hits]
    mrr_u = sum(1.0 / r for r in all_u if r) / len(all_u) if all_u else 0
    mrr_s = sum(1.0 / r for r in all_s if r) / len(all_s) if all_s else 0
    delta = mrr_s - mrr_u
    sign = "+" if delta >= 0 else ""
    print("-" * 62)
    print(f"{'OVERALL':<20} {mrr_u:>13.3f} {mrr_s:>13.3f} {sign}{delta:>9.3f}")
    print(f"\nTotal: {len(all_u)} questions, {time.time() - total_start:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LoCoMo agent-topic benchmark")
    parser.add_argument("--limit", type=int, help="Limit conversations")
    args = parser.parse_args()

    data_dir = Path(__file__).parent
    data_path = data_dir / "locomo10.json"
    if not data_path.exists():
        print(f"Dataset not found at {data_path}")
        sys.exit(1)

    run_benchmark(str(data_path), limit=args.limit)
