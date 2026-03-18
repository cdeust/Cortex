"""MemoryAgentBench benchmark for JARVIS memory system.

Tests 4 core memory competencies (Hu et al., ICLR 2026):
  1. Accurate Retrieval — recall facts from injected context
  2. Test-Time Learning — few-shot classification from examples in memory
  3. Long-Range Understanding — summarize/reason over large contexts
  4. Conflict Resolution — handle contradictory information

Evaluation: F1, Exact Match, Substring Match per split.
Dataset: HuggingFace "ai-hyz/MemoryAgentBench" (146 rows)

Run:
    python3 benchmarks/memoryagentbench/run_benchmark.py [--split Accurate_Retrieval] [--limit N]
"""

from __future__ import annotations

import argparse
import os
import re
import string
import sys
import time
from pathlib import Path

os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

SPLITS = [
    "Accurate_Retrieval",
    "Test_Time_Learning",
    "Long_Range_Understanding",
    "Conflict_Resolution",
]


# ── Metrics ──────────────────────────────────────────────────────────────


def normalize_answer(s: str) -> str:
    """Lower text and remove punctuation, articles and extra whitespace."""
    s = s.lower()
    # Remove articles
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    # Remove punctuation
    s = s.translate(str.maketrans("", "", string.punctuation))
    # Collapse whitespace
    s = " ".join(s.split())
    return s.strip()


def compute_f1(prediction: str, ground_truth: str) -> float:
    pred_tokens = normalize_answer(prediction).split()
    gt_tokens = normalize_answer(ground_truth).split()
    if not pred_tokens or not gt_tokens:
        return float(normalize_answer(prediction) == normalize_answer(ground_truth))
    common = set(pred_tokens) & set(gt_tokens)
    if not common:
        return 0.0
    precision = len(common) / len(pred_tokens)
    recall = len(common) / len(gt_tokens)
    return 2 * precision * recall / (precision + recall)


def compute_em(prediction: str, ground_truth: str) -> float:
    return float(normalize_answer(prediction) == normalize_answer(ground_truth))


def compute_substring_em(prediction: str, ground_truth: str) -> float:
    return float(normalize_answer(ground_truth) in normalize_answer(prediction))


def best_score(prediction: str, answer_list: list[str], metric_fn) -> float:
    """Best score across multiple valid answers."""
    if not answer_list:
        return 0.0
    return max(metric_fn(prediction, a) for a in answer_list)


# ── Retrieval Engine ─────────────────────────────────────────────────────


class MABRetriever:
    """Chunk-and-retrieve adapter wrapping shared BenchmarkRetriever."""

    def __init__(self, chunk_size: int = 500):
        from benchmarks.lib.retriever import BenchmarkRetriever

        self._retriever = BenchmarkRetriever()
        self.chunk_size = chunk_size

    def clear(self):
        self._retriever.clear()

    def ingest(self, context: str):
        """Chunk context into memory units and load into retriever."""
        words = context.split()
        docs = []
        for i in range(0, len(words), self.chunk_size):
            chunk = " ".join(words[i : i + self.chunk_size])
            if chunk.strip():
                docs.append({"content": chunk})
        self._retriever.add_documents(docs)

    def retrieve(self, query: str, top_k: int = 5) -> str:
        """Retrieve and concatenate top-K chunks as context string."""
        results = self._retriever.retrieve(query, top_k=top_k)
        return "\n\n".join(r["content"] for r in results)


# ── Main Benchmark ───────────────────────────────────────────────────────


def run_benchmark(splits: list[str] | None = None, limit: int | None = None):
    """Run MemoryAgentBench retrieval benchmark."""
    from datasets import load_dataset

    splits = splits or SPLITS
    retriever = MABRetriever(chunk_size=500)

    print("Loading MemoryAgentBench from HuggingFace...")
    total_start = time.time()

    all_results: dict[str, dict] = {}

    for split_name in splits:
        print(f"\n--- {split_name} ---")
        try:
            ds = load_dataset("ai-hyz/MemoryAgentBench", split=split_name)
        except Exception as e:
            print(f"  Error loading split: {e}")
            continue

        if limit:
            ds = ds.select(range(min(limit, len(ds))))

        split_f1 = []
        split_em = []
        split_sub_em = []
        total_questions = 0

        for row_idx, row in enumerate(ds):
            context = row.get("context", "")
            questions = row.get("questions", [])
            answers = row.get("answers", [])

            if not context or not questions:
                continue

            # Ingest context
            retriever.clear()
            retriever.ingest(context)

            (row.get("metadata", {}).get("source", "") if row.get("metadata") else "")

            for q_idx, (question, answer_list) in enumerate(zip(questions, answers)):
                if not question or not answer_list:
                    continue

                # Flatten answer list
                flat_answers = []
                for a in answer_list:
                    if isinstance(a, list):
                        flat_answers.extend(a)
                    else:
                        flat_answers.append(str(a))
                flat_answers = [a for a in flat_answers if a.strip()]

                if not flat_answers:
                    continue

                # Retrieve relevant chunks
                retrieved_context = retriever.retrieve(question, top_k=5)

                # For retrieval-only evaluation, we check if the answer appears in retrieved context
                # This tests retrieval quality without requiring an LLM reader
                prediction = retrieved_context

                f1 = best_score(prediction, flat_answers, compute_f1)
                em = best_score(prediction, flat_answers, compute_em)
                sub_em = best_score(prediction, flat_answers, compute_substring_em)

                split_f1.append(f1)
                split_em.append(em)
                split_sub_em.append(sub_em)
                total_questions += 1

            if (row_idx + 1) % 5 == 0 or row_idx == 0:
                avg_f1 = sum(split_f1) / len(split_f1) if split_f1 else 0
                print(
                    f"  [{row_idx + 1}/{len(ds)}] questions={total_questions} "
                    f"avg_F1={avg_f1:.3f}"
                )

        if split_f1:
            all_results[split_name] = {
                "f1": sum(split_f1) / len(split_f1),
                "em": sum(split_em) / len(split_em),
                "substring_em": sum(split_sub_em) / len(split_sub_em),
                "total_questions": total_questions,
            }

    total_time = time.time() - total_start

    # Print results
    print()
    print("=" * 72)
    print("MemoryAgentBench Results — JARVIS (Retrieval-Only)")
    print("=" * 72)
    print()
    print(f"{'Split':<28} {'F1':>6} {'EM':>6} {'Sub_EM':>6} {'Qs':>5}")
    print("-" * 55)

    overall_f1 = []
    overall_total = 0
    for split_name, metrics in all_results.items():
        print(
            f"{split_name:<28} {metrics['f1']:>6.3f} {metrics['em']:>6.3f} "
            f"{metrics['substring_em']:>6.3f} {metrics['total_questions']:>5}"
        )
        overall_f1.append(metrics["f1"])
        overall_total += metrics["total_questions"]

    if overall_f1:
        print("-" * 55)
        avg = sum(overall_f1) / len(overall_f1)
        print(f"{'OVERALL':<28} {avg:>6.3f}                  {overall_total:>5}")

    print(f"\nTotal time: {total_time:.1f}s, Questions: {overall_total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MemoryAgentBench for JARVIS")
    parser.add_argument("--split", choices=SPLITS, help="Single split to run")
    parser.add_argument("--limit", type=int, help="Limit rows per split")
    args = parser.parse_args()

    target_splits = [args.split] if args.split else None
    run_benchmark(splits=target_splits, limit=args.limit)
