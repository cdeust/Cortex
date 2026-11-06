"""The LongMemEval journal recomputes the published headline on its own.

Issue #708: the committed LongMemEval artifacts held aggregates only, so a
reader could not recompute Recall@10 and MRR. Each ``<stem>.queries.jsonl``
row now carries the question's gold session ids and its own scores; the mean
of the rows must equal the aggregate ``run_benchmark`` reports, and each row's
scores must follow from its retrieved sources and gold ids. The runner
imports the PostgreSQL store at module load, so this file needs the
benchmarks extra (psycopg) and is skipped without it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("psycopg")

from benchmarks.lib.query_log import QueryLog  # noqa: E402


class FakeDB:
    """Ranks the haystack sessions in a fixed order of session id."""

    def __init__(self, require_reranker: bool = True) -> None:
        self.order: list[str] = []
        self.ids: dict[str, int] = {}

    def __enter__(self) -> FakeDB:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def clear(self) -> None:
        self.ids = {}

    def load_memories(self, memories: list[dict], domain: str):
        self.ids = {m["source"]: i for i, m in enumerate(memories, 1)}
        return list(self.ids.values()), {i: s for s, i in self.ids.items()}

    def recall(self, query: str, top_k: int = 10, domain: str | None = None):
        ranked = [s for s in self.order if s in self.ids][:top_k]
        return [{"memory_id": self.ids[s], "content": s, "score": 1.0} for s in ranked]


def _question(qid: str, gold: list[str], sessions: list[str]) -> dict:
    turn = [{"role": "user", "content": f"turn of {qid}"}]
    return {
        "question_id": qid,
        "question_type": "single-session-user",
        "question": f"question {qid}",
        "answer": "answer",
        "question_date": "2023/05/30 (Tue) 23:40",
        "answer_session_ids": gold,
        "haystack_sessions": [turn for _ in sessions],
        "haystack_session_ids": sessions,
        "haystack_dates": ["2023/05/20 (Sat) 02:21" for _ in sessions],
    }


def test_journal_rows_recompute_the_reported_headline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benchmarks.longmemeval import run_benchmark as lme  # noqa: PLC0415

    db = FakeDB()
    db.order = ["s2", "s1", "s3", "s4"]
    monkeypatch.setattr(lme, "BenchmarkDB", lambda require_reranker: db)
    monkeypatch.setattr(lme, "build_repro_manifest", lambda: {})
    dataset = [
        _question("q-rank1", ["s2"], ["s1", "s2"]),  # rank 1: mrr 1, r10 1
        _question("q-rank2", ["s1"], ["s1", "s2"]),  # rank 2: mrr 0.5, r10 1
        _question("q-miss", ["s9"], ["s3", "s4"]),  # absent: mrr 0, r10 0
    ]
    data_path = tmp_path / "lme.json"
    data_path.write_text(json.dumps(dataset))
    out = tmp_path / "longmemeval-s.json"

    result = lme.run_benchmark(str(data_path), query_log=QueryLog(out))

    rows = [
        json.loads(line)
        for line in (tmp_path / "longmemeval-s.queries.jsonl").read_text().splitlines()
    ]
    assert [r["question_id"] for r in rows] == ["q-rank1", "q-rank2", "q-miss"]
    assert [r["answer_session_ids"] for r in rows] == [["s2"], ["s1"], ["s9"]]
    assert [r["mrr"] for r in rows] == [1.0, 0.5, 0.0]
    assert [r["recall10"] for r in rows] == [1.0, 1.0, 0.0]
    for row in rows:
        sources = [item["source"] for item in row["items"]]
        assert row["mrr"] == lme.compute_mrr(sources, row["answer_session_ids"])
        assert row["recall10"] == lme.recall_at_k_binary(
            sources, row["answer_session_ids"]
        )
    assert sum(r["mrr"] for r in rows) / len(rows) == result["overall_mrr"]
    assert sum(r["recall10"] for r in rows) / len(rows) == result["overall_recall10"]
