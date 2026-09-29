"""Journalling a run does not change what the runners score.

The LoCoMo and BEAM evaluators are driven with the same fake database twice,
once without and once with a content-bearing journal; the scored output must
be identical. The runners import the PostgreSQL store at module load, so this
file needs the benchmarks extra (psycopg) and is skipped without it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("psycopg")

from benchmarks.lib.query_log import QueryLog  # noqa: E402


class FakeDB:
    """Returns a fixed ranked list for every query."""

    def __init__(self, results: list[dict]) -> None:
        self.results = results
        self.calls: list[str] = []

    def recall(self, query: str, top_k: int = 10, domain: str | None = None):
        self.calls.append(query)
        return [dict(r) for r in self.results]


def test_locomo_evaluation_is_identical_with_and_without_journal(
    tmp_path: Path,
) -> None:
    from benchmarks.locomo import run_benchmark as locomo  # noqa: PLC0415

    source_map = {1: "session_1", 2: "session_2"}
    results = [
        {"memory_id": 2, "content": "second session", "score": 0.8},
        {"memory_id": 1, "content": "first session", "score": 0.7},
    ]
    qa = [
        {"question": "q-a", "evidence": ["D1:3"], "category": 1},
        {"question": "q-b", "evidence": ["D2:1"], "category": 2},
        {"question": "skipped", "evidence": [], "category": 1},
    ]
    plain = locomo.evaluate_conversation(FakeDB(results), [], [1, 2], source_map, qa)
    log = QueryLog(tmp_path / "locomo.json", include_content=True)
    logged = locomo.evaluate_conversation(
        FakeDB(results), [], [1, 2], source_map, qa, query_log=log, conv_id="conv-1"
    )
    log.close()
    assert logged == plain
    journal = (tmp_path / "locomo.queries.jsonl").read_text().splitlines()
    assert len(journal) == 2
    assert '"question_id": "conv-1:0"' in journal[0]


def test_beam_evaluation_is_identical_with_and_without_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benchmarks.beam import run_benchmark as beam  # noqa: PLC0415

    monkeypatch.delenv("CORTEX_USE_ASSEMBLER", raising=False)
    turns = [{"id": 5, "content": "the answer lives in this turn"}]
    results = [
        {"memory_id": 9, "content": "the answer lives in this turn", "score": 0.9}
    ]
    questions = {
        "information_extraction": [
            {"question": "where?", "answer": "this turn", "source_chat_ids": [5]}
        ]
    }
    plain = beam.evaluate_retrieval(FakeDB(results), questions, turns, [9])
    log = QueryLog(tmp_path / "beam.json")
    logged = beam.evaluate_retrieval(
        FakeDB(results), questions, turns, [9], query_log=log, conv_id="c7"
    )
    log.close()
    assert logged == plain
    assert (tmp_path / "beam.phases.jsonl").read_text().count('"recall"') == 1
