"""Offline token counting over a query journal, with a simulated client."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.tokens import count_tokens as ct
from benchmarks.tokens.payload import MissingContentError, render_payload

# source: arbitrary fixture value; any positive envelope exercises the subtraction.
ENVELOPE = 7


class FakeMessages:
    """``input_tokens`` = envelope + one token per 4 characters (at least 1)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def count_tokens(self, *, model: str, messages: list[dict]) -> SimpleNamespace:
        text = messages[0]["content"]
        self.calls.append((model, text))
        return SimpleNamespace(input_tokens=ENVELOPE + max(1, len(text) // 4))


class FakeClient:
    def __init__(self) -> None:
        self.messages = FakeMessages()


QUERY = {
    "question_id": "conv-1:0",
    "retrieved_bytes": 40,
    "items": [
        {"memory_id": 1, "score": 0.9, "content": "a" * 20},
        {"memory_id": 2, "score": 0.5, "content": "b" * 20},
    ],
}


def test_counter_removes_the_envelope_and_caches_by_content() -> None:
    client = FakeClient()
    counter = ct.TokenCounter(client, "claude-opus-5")
    assert counter.envelope == ENVELOPE  # count("x") = 8, minus the one letter
    assert counter.count("a" * 40) == 10
    assert counter.count("a" * 40) == 10
    assert counter.count("") == 0
    assert [call[1] for call in client.messages.calls] == ["x", "a" * 40]
    assert {call[0] for call in client.messages.calls} == {"claude-opus-5"}


def test_query_row_counts_items_and_both_payload_formats() -> None:
    counter = ct.TokenCounter(FakeClient(), "claude-opus-5")
    row = ct.query_row(counter, QUERY)
    assert row["t_retrieved"] == 5 + 5
    for fmt in ("json", "tabular"):
        rendered = render_payload(QUERY, fmt)
        assert json.loads(rendered)["format"] == fmt
        assert row[f"t_response_{fmt}"] == max(1, len(rendered) // 4)


def test_journal_without_content_is_refused() -> None:
    bare = {**QUERY, "items": [{"memory_id": 1, "score": 0.1}]}
    with pytest.raises(MissingContentError, match="--query-log-content"):
        ct.query_row(ct.TokenCounter(FakeClient(), "m"), bare)


def test_main_writes_model_envelope_summary_and_history_ratio(tmp_path: Path) -> None:
    journal = tmp_path / "leg.queries.jsonl"
    journal.write_text(json.dumps(QUERY) + "\n" + json.dumps(QUERY) + "\n")
    out = tmp_path / "leg.tokens.json"
    ct.main(
        ["--queries", str(journal), "--out", str(out), "--limit", "1"], FakeClient()
    )
    report = json.loads(out.read_text())
    assert report["model"] == ct.DEFAULT_MODEL
    assert report["envelope_tokens"] == ENVELOPE
    assert len(report["rows"]) == 1
    assert report["summary"]["t_retrieved"]["mean"] == 10

    rows = ct.count_journal(
        ct.TokenCounter(FakeClient(), "m"), [QUERY], {"conv-1:0": "z" * 400}
    )["rows"]
    assert rows[0]["t_full_history"] == 100
    assert rows[0]["retrieved_over_full_history"] == pytest.approx(0.1)
