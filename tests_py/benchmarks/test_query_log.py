"""The per-query journal records what was retrieved and never changes it."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.lib.query_log import QueryLog, sidecar_paths, text_stats

RESULTS = [
    {"memory_id": 7, "content": "héllo wörld", "score": 0.9},
    {"memory_id": 3, "content": "", "score": None},
]


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_sidecars_sit_beside_the_results_file(tmp_path: Path) -> None:
    queries, phases = sidecar_paths(tmp_path / "locomo.json")
    assert queries == tmp_path / "locomo.queries.jsonl"
    assert phases == tmp_path / "locomo.phases.jsonl"


def test_text_stats_counts_bytes_codepoints_and_hash() -> None:
    stats = text_stats("héllo")
    assert stats == {
        "bytes": 6,
        "codepoints": 5,
        "sha256": hashlib.sha256("héllo".encode()).hexdigest(),
    }


def test_disabled_log_writes_nothing_and_accepts_every_call(tmp_path: Path) -> None:
    log = QueryLog(None)
    with log.phase("recall", "q1"):
        pass
    log.record("q1", copy.deepcopy(RESULTS))
    log.close()
    assert not log.enabled
    assert list(tmp_path.iterdir()) == []


def test_record_without_content_keeps_sizes_and_ids_only(tmp_path: Path) -> None:
    with QueryLog(tmp_path / "leg.json") as log:
        log.record(
            "q1",
            copy.deepcopy(RESULTS),
            source_map={7: "session_2"},
            extra={"run": 0},
        )
    (line,) = _lines(tmp_path / "leg.queries.jsonl")
    assert line["question_id"] == "q1"
    assert line["run"] == 0
    assert line["retrieved_bytes"] == len("héllo wörld".encode())
    first, second = line["items"]
    assert first["memory_id"] == 7 and first["source"] == "session_2"
    assert first["codepoints"] == len("héllo wörld")
    assert "content" not in first
    assert second["bytes"] == 0 and second["source"] is None


def test_record_with_content_stores_the_text(tmp_path: Path) -> None:
    with QueryLog(tmp_path / "leg.json", include_content=True) as log:
        log.record("q1", copy.deepcopy(RESULTS))
    (line,) = _lines(tmp_path / "leg.queries.jsonl")
    assert [i["content"] for i in line["items"]] == ["héllo wörld", ""]


def test_record_and_phase_leave_the_results_untouched(tmp_path: Path) -> None:
    results = copy.deepcopy(RESULTS)
    with QueryLog(tmp_path / "leg.json", include_content=True) as log:
        with log.phase("recall", "q1"):
            pass
        log.record("q1", results, source_map={7: "s"})
    assert results == RESULTS


def test_phase_records_wall_clock_window_even_when_the_block_raises(
    tmp_path: Path,
) -> None:
    with QueryLog(tmp_path / "leg.json") as log:
        with log.phase("ingest", "conv-1"):
            pass
        with pytest.raises(RuntimeError), log.phase("recall", "conv-1:0"):
            raise RuntimeError("boom")
    ingest, recall = _lines(tmp_path / "leg.phases.jsonl")
    assert (ingest["phase"], ingest["unit"]) == ("ingest", "conv-1")
    assert recall["unit"] == "conv-1:0"
    for row in (ingest, recall):
        assert row["wall_start"] <= row["wall_end"]
