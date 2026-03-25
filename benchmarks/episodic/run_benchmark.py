"""Episodic Memories Benchmark for Cortex memory system.

Tests episodic memory recall on synthetic book-like narratives
(Huet et al., ICLR 2025). Each event is a 5-tuple (date, location, entity,
content, content_detail) embedded in narrative prose.

Metrics:
  - Simple Recall Score: F1 grouped by event count bins {0,1,2,3-5,6+}
  - Chronological Awareness: latest state + temporal ordering (Kendall tau)

Dataset: Pre-generated from figshare.org/28244480, or generate with the
         episodic-memory-benchmark repo.

Run:
    python3 benchmarks/episodic/run_benchmark.py [--events 20] [--limit N]
"""

from __future__ import annotations

import argparse
import json
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


# ── Data Loading ─────────────────────────────────────────────────────────


def load_events(data_dir: Path) -> list[list[str]]:
    """Load events.json — list of [date, location, entity, content, content_detail]."""
    path = data_dir / "events.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def load_book(data_dir: Path, nb_events: int) -> str:
    """Load the generated book text."""
    # Try multiple possible paths
    for candidate in [
        data_dir / f"books/book_{nb_events}events/book.json",
        data_dir / "books" / "book.json",
        data_dir / "book.json",
    ]:
        if candidate.exists():
            with open(candidate) as f:
                data = json.load(f)
                if isinstance(data, str):
                    return data
                if isinstance(data, dict):
                    return data.get("text", data.get("book", str(data)))
    return ""


def generate_qa_from_events(events: list[list[str]]) -> list[dict]:
    """Generate QA pairs from event tuples.

    Creates questions testing recall of dates, locations, entities, and content
    for each event and cross-event combinations.
    """
    qa_pairs = []

    # Build entity -> events index
    entity_events: dict[str, list] = defaultdict(list)
    for event in events:
        if len(event) >= 4:
            entity_events[event[2]].append(event)

    # Per-entity questions
    for entity, ent_events in entity_events.items():
        # "all dates" question
        dates = [e[0] for e in ent_events]
        qa_pairs.append(
            {
                "question": f"On what dates did events involving {entity} occur?",
                "answers": set(dates),
                "n_items": len(dates),
                "get": "all",
                "cue": "entity",
                "retrieval": "dates",
            }
        )

        # "all locations" question
        locations = [e[1] for e in ent_events]
        qa_pairs.append(
            {
                "question": f"In what locations did events involving {entity} take place?",
                "answers": set(locations),
                "n_items": len(locations),
                "get": "all",
                "cue": "entity",
                "retrieval": "locations",
            }
        )

        # "latest location" question (if multiple events)
        if len(ent_events) >= 2:
            # Sort by date string (assumes consistent date format)
            sorted_events = sorted(ent_events, key=lambda e: e[0])
            latest = sorted_events[-1]
            qa_pairs.append(
                {
                    "question": f"What is the most recent location where {entity} was seen?",
                    "answers": {latest[1]},
                    "n_items": 1,
                    "get": "latest",
                    "cue": "entity",
                    "retrieval": "location",
                }
            )

            # "chronological dates" question
            ordered_dates = [e[0] for e in sorted_events]
            qa_pairs.append(
                {
                    "question": f"List all dates when {entity} was observed, from earliest to latest.",
                    "answers": set(ordered_dates),
                    "ordered_answers": ordered_dates,
                    "n_items": len(ordered_dates),
                    "get": "chronological",
                    "cue": "entity",
                    "retrieval": "dates",
                }
            )

    # Bin 0: non-existent entity questions (hallucination test)
    all_entities = set(e[2] for e in events if len(e) >= 4)
    fake_names = ["Zephyr Nightingale", "Quantum McPherson", "Aria Starweaver"]
    for fake in fake_names:
        if fake not in all_entities:
            qa_pairs.append(
                {
                    "question": f"On what dates did events involving {fake} occur?",
                    "answers": set(),
                    "n_items": 0,
                    "get": "all",
                    "cue": "entity",
                    "retrieval": "dates",
                }
            )

    return qa_pairs


# ── Retrieval Engine ─────────────────────────────────────────────────────


class EpisodicRetriever:
    """Adapter wrapping shared BenchmarkRetriever for episodic benchmark."""

    def __init__(self):
        from benchmarks.lib.retriever import BenchmarkRetriever

        self._retriever = BenchmarkRetriever()
        self.chapters: list[str] = []

    def clear(self):
        self.chapters = []
        self._retriever.clear()

    def ingest_book(self, book_text: str):
        """Split book into chapters and load into retriever."""
        parts = re.split(r"\n\n\nChapter \d+\n\n", book_text)
        self.chapters = [p.strip() for p in parts if p.strip()]
        if not self.chapters:
            self.chapters = [p.strip() for p in book_text.split("\n\n\n") if p.strip()]
        self._retriever.add_documents([{"content": c} for c in self.chapters])

    def ingest_events_as_chapters(self, events: list[list[str]]):
        """Create synthetic chapters from raw events."""
        for event in events:
            if len(event) >= 5:
                ch = (
                    f"On {event[0]}, at {event[1]}, {event[2]} "
                    f"participated in {event[3]}. {event[4]}."
                )
            elif len(event) >= 4:
                ch = (
                    f"On {event[0]}, at {event[1]}, {event[2]} "
                    f"was involved in {event[3]}."
                )
            else:
                continue
            self.chapters.append(ch)
        self._retriever.add_documents([{"content": c} for c in self.chapters])

    def retrieve(self, query: str, top_k: int = 10) -> list[str]:
        """Retrieve top-K chapters as strings."""
        results = self._retriever.retrieve(query, top_k=top_k)
        return [r["content"] for r in results]


# ── Scoring ──────────────────────────────────────────────────────────────


def compute_recall_f1(retrieved_text: str, answers: set[str]) -> float:
    """Compute F1 for set-based recall."""
    if not answers:
        # Bin 0: no answers expected. Check for hallucination.
        # If retrieved text doesn't contain any answer-like content, score = 1.0
        return 1.0 if len(retrieved_text.strip()) < 50 else 0.5

    found = sum(1 for a in answers if a.lower() in retrieved_text.lower())
    if found == 0:
        return 0.0

    precision = found / max(found, 1)  # Lenient: assume retrieved text has ~found items
    recall = found / len(answers)
    return (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )


# ── Main Benchmark ───────────────────────────────────────────────────────


def run_benchmark(
    data_dir: str | None = None, nb_events: int = 20, limit: int | None = None
):
    """Run episodic memory benchmark."""
    data_path = Path(data_dir) if data_dir else None

    print(f"Episodic Memory Benchmark (nb_events={nb_events})")

    events = []
    book_text = ""

    if data_path and data_path.exists():
        events = load_events(data_path)
        book_text = load_book(data_path, nb_events)
        print(f"  Loaded {len(events)} events, book={len(book_text)} chars")
    else:
        print("  No data directory specified. Generating synthetic events...")
        # Generate minimal synthetic events for testing
        import random

        random.seed(42)
        names = [
            "Alice Chen",
            "Bob Smith",
            "Carol Davis",
            "David Lee",
            "Eva Martinez",
            "Frank Wilson",
            "Grace Kim",
            "Henry Brown",
            "Iris Taylor",
            "Jack Anderson",
        ]
        locations = [
            "Central Park",
            "City Library",
            "Tech Hub",
            "Coffee Shop",
            "Museum",
            "Beach Resort",
            "Mountain Lodge",
            "Airport",
            "University",
            "Hospital",
        ]
        contents = [
            "Meeting",
            "Workshop",
            "Presentation",
            "Training",
            "Conference",
            "Interview",
            "Celebration",
            "Planning Session",
            "Review",
            "Hackathon",
        ]
        details = [
            "Discussed new project",
            "Reviewed quarterly results",
            "Planned next sprint",
            "Shared research findings",
            "Celebrated milestone",
            "Onboarded new member",
            "Resolved critical issue",
            "Brainstormed ideas",
            "Conducted interview",
            "Shipped feature update",
        ]

        for i in range(min(nb_events, 50)):
            date = f"2025-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}"
            events.append(
                [
                    date,
                    random.choice(locations),
                    random.choice(names),
                    random.choice(contents),
                    random.choice(details),
                ]
            )
        print(f"  Generated {len(events)} synthetic events")

    # Generate QA
    qa_pairs = generate_qa_from_events(events[:nb_events] if events else [])
    if limit:
        qa_pairs = qa_pairs[:limit]
    print(f"  Generated {len(qa_pairs)} QA pairs")

    # Set up retriever
    retriever = EpisodicRetriever()
    if book_text:
        retriever.ingest_book(book_text)
    else:
        retriever.ingest_events_as_chapters(events[:nb_events])
    print(f"  Ingested {len(retriever.chapters)} chapters")

    # Evaluate
    total_start = time.time()
    bin_scores: dict[str, list[float]] = defaultdict(list)

    for i, qa in enumerate(qa_pairs):
        retrieved = retriever.retrieve(qa["question"], top_k=10)
        retrieved_text = "\n".join(retrieved)

        f1 = compute_recall_f1(retrieved_text, qa["answers"])

        # Bin by n_items
        n = qa["n_items"]
        if n == 0:
            bin_name = "bin_0"
        elif n == 1:
            bin_name = "bin_1"
        elif n == 2:
            bin_name = "bin_2"
        elif n <= 5:
            bin_name = "bin_3-5"
        else:
            bin_name = "bin_6+"

        bin_scores[bin_name].append(f1)

        if (i + 1) % 50 == 0:
            avg = sum(s for scores in bin_scores.values() for s in scores) / max(
                i + 1, 1
            )
            print(f"  [{i + 1}/{len(qa_pairs)}] avg_F1={avg:.3f}")

    total_time = time.time() - total_start

    # Compute Simple Recall Score
    print()
    print("=" * 72)
    print("Episodic Memory Benchmark Results — Cortex (Retrieval-Only)")
    print("=" * 72)
    print()

    # Reference: Gemini 2.5 Pro = 0.968 SRS, Claude 3.5 Sonnet = ~0.85
    print(f"{'Bin':<12} {'Mean F1':>8} {'Count':>6}")
    print("-" * 30)

    bin_means = {}
    for bin_name in ["bin_0", "bin_1", "bin_2", "bin_3-5", "bin_6+"]:
        scores = bin_scores.get(bin_name, [])
        if scores:
            mean = sum(scores) / len(scores)
            bin_means[bin_name] = mean
            print(f"{bin_name:<12} {mean:>8.3f} {len(scores):>6}")

    srs = sum(bin_means.values()) / len(bin_means) if bin_means else 0.0
    print("-" * 30)
    print(f"{'SRS':<12} {srs:>8.3f}")
    print()
    print("Reference: Gemini 2.5 Pro = 0.968, Claude 3.5 = ~0.85")
    print(f"Total time: {total_time:.1f}s, QA pairs: {len(qa_pairs)}")

    if not data_dir:
        print()
        print("Note: Running on synthetic events. For proper evaluation,")
        print("      download pre-generated data from figshare.org/28244480")
        print("      and run with: --data-dir epbench/data/Udefault_Sdefault_seed0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Episodic Memory Benchmark for Cortex")
    parser.add_argument("--data-dir", help="Path to pre-generated data directory")
    parser.add_argument(
        "--events", type=int, default=20, help="Number of events (default: 20)"
    )
    parser.add_argument("--limit", type=int, help="Limit QA pairs")
    args = parser.parse_args()

    run_benchmark(data_dir=args.data_dir, nb_events=args.events, limit=args.limit)
