"""A skipped operation is its own telemetry outcome, apart from errors (issue #660)."""

from __future__ import annotations

import json

import pytest

from mcp_server.core import telemetry


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    monkeypatch.setattr(telemetry, "_LOG_PATH", tmp_path / "telemetry.jsonl")
    telemetry.reset()
    yield tmp_path / "telemetry.jsonl"
    telemetry.reset()


def test_skipped_counts_in_its_own_bucket_not_as_a_failure(_isolated) -> None:
    telemetry.record("capture_skipped", latency_ms=1.0, ok=False, skipped=True)
    counters = telemetry.snapshot()["capture_skipped"]
    assert (counters["ok"], counters["fail"], counters["skipped"]) == (0, 0, 1)


def test_an_error_stays_a_failure_and_a_success_stays_ok(_isolated) -> None:
    telemetry.record("op", latency_ms=1.0, ok=False)
    telemetry.record("op", latency_ms=1.0)
    counters = telemetry.snapshot()["op"]
    assert (counters["ok"], counters["fail"], counters["skipped"]) == (1, 1, 0)


def test_jsonl_line_carries_the_distinguishing_field(_isolated) -> None:
    telemetry.record("capture_skipped", latency_ms=1.0, ok=False, skipped=True)
    telemetry.record("op", latency_ms=1.0, ok=False)
    first, second = (json.loads(x) for x in _isolated.read_text().splitlines())
    assert (first["ok"], first["skipped"]) == (False, True)
    assert (second["ok"], second["skipped"]) == (False, False)


def test_ok_and_skipped_together_is_refused_and_records_nothing(_isolated) -> None:
    with pytest.raises(ValueError, match="both ok and skipped"):
        telemetry.record("capture_skipped", latency_ms=1.0, ok=True, skipped=True)
    assert telemetry.snapshot() == {}
    assert not _isolated.exists()
