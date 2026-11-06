"""Issue #722: the exact sample `record` builds and the JSONL line it publishes.

These pin what a reader of telemetry.jsonl relies on: the default counts, the
`ts` key, the 3-decimal latency, the byte size handed to log rotation, and the
two logged failure paths (unwritable log, raising exporter).
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager

import pytest

from mcp_server.core import telemetry


@pytest.fixture
def telemetry_log(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", path)
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    monkeypatch.setattr(telemetry, "_exporter", None)
    telemetry.reset()
    yield path
    telemetry.reset()


def test_record_defaults_to_zero_counts_and_stamps_ts(telemetry_log, monkeypatch):
    monkeypatch.setattr(telemetry.time, "time", lambda: 1700000000.5)
    with telemetry.capture_records() as samples:
        telemetry.record("recall", latency_ms=2.0)
    (sample,) = samples
    assert sample["ts"] == 1700000000.5
    assert sample["bytes_in"] == 0
    assert sample["bytes_out"] == 0
    assert sample["result_count"] == 0
    assert sample["stage_ms"] == {}


def test_published_line_rounds_latency_to_three_decimals(telemetry_log):
    telemetry.record("recall", latency_ms=1.23456)
    line = json.loads(telemetry_log.read_text())
    assert line["latency_ms"] == 1.235
    assert set(line) == set(telemetry.TelemetrySample.__annotations__)


def test_rotation_receives_the_utf8_size_of_the_line(telemetry_log, monkeypatch):
    seen: list[tuple] = []
    real = telemetry.open_rotating_log

    @contextmanager
    def spy(path, *args, **kwargs):
        seen.append((path, *args, *kwargs.values()))
        with real(path, *args, **kwargs) as handle:
            yield handle

    monkeypatch.setattr(telemetry, "open_rotating_log", spy)
    telemetry.record("café", latency_ms=1.0)
    written = telemetry_log.read_text(encoding="utf-8")
    assert seen == [(telemetry_log, len(written.encode("utf-8")))]


def test_unwritable_log_is_logged_with_its_path(telemetry_log, monkeypatch, caplog):
    @contextmanager
    def refuse(path, *args, **kwargs):
        raise OSError("fixture: read-only filesystem")
        yield  # pragma: no cover

    monkeypatch.setattr(telemetry, "open_rotating_log", refuse)
    with caplog.at_level(logging.WARNING, logger=telemetry.logger.name):
        telemetry.record("recall", latency_ms=1.0)
    (entry,) = [r for r in caplog.records if r.name == telemetry.logger.name]
    assert entry.levelno == logging.WARNING
    assert entry.getMessage() == f"Cannot append telemetry sample: {telemetry_log}"
    assert entry.exc_info is not None
    assert "fixture: read-only filesystem" in str(entry.exc_info[1])


def test_raising_exporter_is_logged_and_the_sample_kept(telemetry_log, caplog):
    class Failing:
        def export(self, sample):
            raise RuntimeError("fixture exporter failure")

    telemetry.set_exporter(Failing())
    try:
        with caplog.at_level(logging.DEBUG, logger=telemetry.logger.name):
            telemetry.record("recall", latency_ms=1.0)
    finally:
        telemetry.set_exporter(None)
    (entry,) = [r for r in caplog.records if r.name == telemetry.logger.name]
    assert entry.levelno == logging.DEBUG
    assert entry.getMessage() == "telemetry exporter raised; sample dropped"
    assert entry.exc_info is not None
    assert "fixture exporter failure" in str(entry.exc_info[1])
    assert json.loads(telemetry_log.read_text())["op"] == "recall"
