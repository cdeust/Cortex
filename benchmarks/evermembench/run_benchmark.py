"""EverMemBench benchmark for Cortex memory system.

Tests long-horizon memory for multi-party collaborative dialogues
(Hu et al., 2026). 5 projects, 170 employees, 365 simulated days,
2,400 QA pairs across 3 evaluation dimensions.

Dimensions:
  F — Fine-grained Recall (SH: single-hop, Multi: multi-hop, Temp: temporal)
  MA — Memory Awareness (Const: constraint, Proact: proactivity, U: update)
  P — Profile Understanding (Style, Skill, Role)

Evaluation: Retrieval-based — check if correct evidence is in top-K.
Full QA requires claude -p as judge.

Dataset: HuggingFace "EverMind-AI/EverMemBench-Dynamic"

Run:
    python3 benchmarks/evermembench/run_benchmark.py [--limit N]
"""

from __future__ import annotations

import argparse
import ast
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


# Question ID taxonomy
MAJOR_MAP = {
    "F": "fine_grained_recall",
    "MA": "memory_awareness",
    "P": "profile_understanding",
}
MINOR_MAP = {
    "SH": "single_hop",
    "Multi": "multi_hop",
    "Temp": "temporal",
    "Const": "constraint",
    "Proact": "proactivity",
    "U": "update",
    "Style": "style",
    "Skill": "skill",
    "Role": "role",
}


def parse_question_id(qid: str) -> tuple[str, str]:
    """Parse question ID like 'F_SH_Top004_001' into (major, minor)."""
    parts = qid.split("_")
    if len(parts) >= 2:
        major = MAJOR_MAP.get(parts[0], parts[0])
        minor = MINOR_MAP.get(parts[1], parts[1])
        return major, minor
    return "unknown", "unknown"


# ── Data Loading ─────────────────────────────────────────────────────────


def load_evermembench():
    """Load EverMemBench from HuggingFace (dialogues + qars configs)."""
    from datasets import load_dataset

    dialogues_ds = load_dataset(
        "EverMind-AI/EverMemBench-Dynamic", "dialogues", split="train"
    )
    qars_ds = load_dataset("EverMind-AI/EverMemBench-Dynamic", "qars", split="train")
    return dialogues_ds, qars_ds


def extract_dialogues_from_ds(ds) -> list[dict]:
    """Extract dialogue messages from HuggingFace dataset rows."""
    messages = []
    for row in ds:
        speaker = row.get("speaker", "")
        dialogue = row.get("dialogue", "")
        row.get("time", "")
        date = row.get("date", "")
        group = row.get("group", "")
        msg_idx = row.get("message_index", 0)

        content = ""
        if date:
            content += f"[{date}] "
        if group:
            content += f"[{group}] "
        if speaker:
            content += f"{speaker}: "
        content += dialogue

        messages.append(
            {
                "content": content,
                "speaker": speaker,
                "date": date,
                "group": group,
                "message_index": msg_idx,
                "raw": dialogue,
            }
        )
    return messages


def chunk_dialogues(messages: list[dict], chunk_size: int = 20) -> list[dict]:
    """Group messages into chunks for memory storage."""
    chunks = []
    for i in range(0, len(messages), chunk_size):
        batch = messages[i : i + chunk_size]
        content = "\n".join(m["content"] for m in batch)
        dates = list(set(m["date"] for m in batch if m["date"]))
        chunks.append(
            {
                "content": content,
                "dates": dates,
                "message_indices": [m["message_index"] for m in batch],
            }
        )
    return chunks


# ── Retrieval ────────────────────────────────────────────────────────────


class EverMemRetriever:
    """Adapter wrapping shared BenchmarkRetriever for EverMemBench."""

    def __init__(self):
        from benchmarks.lib.retriever import BenchmarkRetriever

        self._retriever = BenchmarkRetriever()

    def clear(self):
        self._retriever.clear()

    def add_chunks(self, chunks: list[dict]):
        self._retriever.add_documents(chunks)

    def retrieve(self, query: str, top_k: int = 10) -> list[dict]:
        results = self._retriever.retrieve(query, top_k=top_k)
        return [
            {"chunk_idx": r["_idx"], "content": r["content"], "score": r["score"]}
            for r in results
        ]


# ── Evaluation ───────────────────────────────────────────────────────────


def evaluate_qa(retriever: EverMemRetriever, qa_items: list[dict]) -> dict[str, list]:
    """Evaluate QA items against retriever. Checks answer substring in retrieved context."""
    results: dict[str, list] = defaultdict(list)

    for qa in qa_items:
        qid = qa.get("id", "")
        question = qa.get("Q", "")
        answer = qa.get("A", "")
        options = qa.get("options")

        if not question:
            continue

        major, minor = parse_question_id(qid)
        category = f"{major}/{minor}"

        retrieved = retriever.retrieve(question, top_k=10)
        retrieved_text = " ".join(r["content"] for r in retrieved)

        # For MC: check if evidence supports the correct option
        # For OE: check if answer appears in retrieved context
        if options and isinstance(options, dict):
            # Multiple choice — check if correct answer's content is retrievable
            correct_option_text = options.get(answer, answer)
            hit = (
                correct_option_text.lower() in retrieved_text.lower()
                or answer.lower() in retrieved_text.lower()
            )
        else:
            # Open-ended — check substring
            hit = answer.lower()[:50] in retrieved_text.lower() if answer else False

        results[category].append(
            {
                "qid": qid,
                "question": question,
                "hit": hit,
            }
        )

    return results


# ── Main ─────────────────────────────────────────────────────────────────


def run_benchmark(limit: int | None = None, topic_filter: str | None = None):
    print("Loading EverMemBench from HuggingFace...")
    dialogues_ds, qars_ds = load_evermembench()

    print(f"  Dialogues: {len(dialogues_ds)} rows, QA: {len(qars_ds)} pairs")

    # Group dialogues by topic
    topic_dialogues: dict[str, list] = defaultdict(list)
    for row in dialogues_ds:
        tid = row["topic_id"]
        if topic_filter and tid != topic_filter:
            continue
        raw = row.get("dialogues", "{}")
        if isinstance(raw, str):
            try:
                groups = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                try:
                    groups = json.loads(raw)
                except (ValueError, TypeError):
                    groups = {}
        else:
            groups = raw or {}

        date = row.get("date", "")
        for group_name, messages in groups.items():
            if isinstance(messages, list):
                for msg in messages:
                    if isinstance(msg, dict):
                        content = f"[{date}] [{group_name}] {msg.get('speaker', '')}: {msg.get('dialogue', '')}"
                        topic_dialogues[tid].append(content)

    # Group QA by topic
    topic_qa: dict[str, list] = defaultdict(list)
    for row in qars_ds:
        tid = row["topic_id"]
        if topic_filter and tid != topic_filter:
            continue
        topic_qa[tid].append(
            {
                "id": row["id"],
                "Q": row["Q"],
                "A": row["A"],
                "options": row.get("options"),
            }
        )

    retriever = EverMemRetriever()
    all_results: dict[str, list] = defaultdict(list)
    total_start = time.time()

    for tid in sorted(topic_dialogues.keys()):
        messages = topic_dialogues[tid]
        qa_items = topic_qa.get(tid, [])
        if limit:
            messages = messages[:limit]

        print(f"\n--- Topic {tid}: {len(messages)} messages, {len(qa_items)} QA ---")

        # Chunk and ingest
        chunks = []
        for i in range(0, len(messages), 15):
            batch = messages[i : i + 15]
            chunks.append(
                {"content": "\n".join(batch), "dates": [], "message_indices": []}
            )

        retriever.clear()
        retriever.add_chunks(chunks)

        # Evaluate QA
        results = evaluate_qa(retriever, qa_items)
        for cat, rs in results.items():
            all_results[cat].extend(rs)

        topic_total = sum(len(rs) for rs in results.values())
        topic_hits = sum(1 for rs in results.values() for r in rs if r["hit"])
        acc = topic_hits / topic_total if topic_total else 0
        print(f"  Retrieval accuracy: {acc:.1%} ({topic_hits}/{topic_total})")

    total_time = time.time() - total_start

    # Aggregate
    print()
    print("=" * 72)
    print("EverMemBench Results — Cortex (Retrieval-Only)")
    print("=" * 72)
    print()

    print(f"{'Category':<35} {'Acc':>6} {'Hits':>5} {'Total':>5}")
    print("-" * 55)

    overall_hits = 0
    overall_total = 0
    major_scores: dict[str, list] = defaultdict(list)

    for cat in sorted(all_results.keys()):
        rs = all_results[cat]
        hits = sum(1 for r in rs if r["hit"])
        total = len(rs)
        acc = hits / total if total else 0

        major = cat.split("/")[0] if "/" in cat else cat
        major_scores[major].append(acc)

        print(f"{cat:<35} {acc:>5.1%} {hits:>5} {total:>5}")
        overall_hits += hits
        overall_total += total

    print("-" * 55)
    if overall_total:
        overall_acc = overall_hits / overall_total
        print(
            f"{'OVERALL':<35} {overall_acc:>5.1%} {overall_hits:>5} {overall_total:>5}"
        )

    # Major dimension summary
    print()
    print("By dimension:")
    for major, accs in sorted(major_scores.items()):
        avg = sum(accs) / len(accs) if accs else 0
        print(f"  {major}: {avg:.1%}")

    print(f"\nTotal time: {total_time:.1f}s, QA pairs: {overall_total}")
    print("Reference: Best memory system (MemOS + GPT-4.1-mini) = 42.55% overall")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EverMemBench for Cortex")
    parser.add_argument("--limit", type=int, help="Limit messages per topic")
    parser.add_argument("--topic", help="Single topic ID to run (01-05)")
    args = parser.parse_args()

    run_benchmark(limit=args.limit, topic_filter=args.topic)
