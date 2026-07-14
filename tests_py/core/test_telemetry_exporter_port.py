"""Tests for the optional TelemetryExporter port (issue #122).

Covers:
  - default (no exporter set): record() behaves exactly as before -- no
    export attempted, in-memory counters + JSONL write unaffected.
  - set_exporter(x): record() invokes x.export(sample) with the same
    shape written to the JSONL log.
  - a raising exporter never breaks record() (telemetry must never break
    the calling tool).
  - set_exporter(None) clears a previously registered exporter.
"""

from __future__ import annotations

import pytest

from mcp_server.core import telemetry


class _RecordingExporter:
    def __init__(self) -> None:
        self.samples: list[dict] = []

    def export(self, sample: dict) -> None:
        self.samples.append(sample)


class _RaisingExporter:
    def export(self, sample: dict) -> None:
        raise RuntimeError("boom in exporter")


@pytest.fixture(autouse=True)
def _clean_exporter_and_counters():
    """Every test starts and ends with no exporter registered."""
    telemetry.set_exporter(None)
    telemetry.reset()
    yield
    telemetry.set_exporter(None)
    telemetry.reset()


class TestNoExporterRegistered:
    """Default behavior (no #122 wiring) must be unchanged."""

    def test_record_succeeds_with_no_exporter(self):
        telemetry.record("recall", latency_ms=1.5, ok=True)
        snap = telemetry.snapshot()
        assert snap["recall"]["count"] == 1


class TestExporterInvoked:
    """set_exporter(x) makes record() mirror the sample to x.export()."""

    def test_export_receives_matching_sample(self):
        exporter = _RecordingExporter()
        telemetry.set_exporter(exporter)

        telemetry.record(
            "remember", latency_ms=12.0, bytes_in=100, result_count=3, ok=True
        )

        assert len(exporter.samples) == 1
        sample = exporter.samples[0]
        assert sample["op"] == "remember"
        assert sample["latency_ms"] == 12.0
        assert sample["bytes_in"] == 100
        assert sample["result_count"] == 3
        assert sample["ok"] is True

    def test_export_called_once_per_record_call(self):
        exporter = _RecordingExporter()
        telemetry.set_exporter(exporter)

        telemetry.record("recall", latency_ms=1.0, ok=True)
        telemetry.record("recall", latency_ms=2.0, ok=False)

        assert len(exporter.samples) == 2
        assert exporter.samples[0]["ok"] is True
        assert exporter.samples[1]["ok"] is False

    def test_set_exporter_none_clears_registration(self):
        exporter = _RecordingExporter()
        telemetry.set_exporter(exporter)
        telemetry.record("recall", latency_ms=1.0, ok=True)
        assert len(exporter.samples) == 1

        telemetry.set_exporter(None)
        telemetry.record("recall", latency_ms=1.0, ok=True)
        # exporter no longer registered -- no new sample delivered to it
        assert len(exporter.samples) == 1


class TestExporterFailureIsolated:
    """A raising exporter must never break the caller of record()."""

    def test_raising_exporter_does_not_propagate(self):
        telemetry.set_exporter(_RaisingExporter())

        # Must not raise.
        telemetry.record("recall", latency_ms=1.0, ok=True)

        # In-memory counters were still updated -- the failure is isolated
        # to the exporter call, which happens after the counters section.
        snap = telemetry.snapshot()
        assert snap["recall"]["count"] == 1

    def test_disabled_telemetry_skips_exporter_too(self, monkeypatch):
        monkeypatch.setenv("CORTEX_TELEMETRY_DISABLED", "1")
        exporter = _RecordingExporter()
        telemetry.set_exporter(exporter)

        telemetry.record("recall", latency_ms=1.0, ok=True)

        assert exporter.samples == []
