"""Tests for the shared silent-failure instrumentation (audit 2026-07-11).

Covers the module's own contract (Move 2): first-failure logging,
anti-spam on repeats, unconditional counter increment, and status()
introspection. Call-site wiring is spot-checked per critical family in
sibling test files (test_pg_recall_silent_failures.py,
test_write_gate_silent_failures.py, etc.) rather than re-derived here.
"""

from __future__ import annotations

import logging

import pytest

from mcp_server.observability import metrics, silent_failure


@pytest.fixture(autouse=True)
def _reset_state():
    silent_failure.reset()
    metrics.reset()
    yield
    silent_failure.reset()
    metrics.reset()


class TestNote:
    def test_first_failure_logs_warning_with_component_and_exception(self, caplog):
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.observability.silent_failure"
        ):
            silent_failure.note("demo.component", ValueError("boom"))

        assert any(
            "demo.component" in rec.message and "boom" in rec.message
            for rec in caplog.records
        )

    def test_second_failure_of_same_component_does_not_log_again(self, caplog):
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.observability.silent_failure"
        ):
            silent_failure.note("demo.component", ValueError("first"))
            first_count = len(caplog.records)
            silent_failure.note("demo.component", ValueError("second"))
            second_count = len(caplog.records)

        assert second_count == first_count

    def test_failure_of_different_component_logs_independently(self, caplog):
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.observability.silent_failure"
        ):
            silent_failure.note("component.a", ValueError("a-broke"))
            silent_failure.note("component.b", ValueError("b-broke"))

        messages = [rec.message for rec in caplog.records]
        assert any("component.a" in m for m in messages)
        assert any("component.b" in m for m in messages)

    def test_note_never_raises_even_on_internal_error(self):
        # A non-string-coercible exception must not turn instrumentation
        # itself into a new failure mode (Move 3: instrumentation must
        # never break the caller).
        class ExplodesError(Exception):
            def __str__(self):
                raise RuntimeError("cannot stringify")

        silent_failure.note("demo.component", ExplodesError())  # must not raise


class TestStatus:
    def test_empty_before_any_failure(self):
        assert silent_failure.status() == {}

    def test_reflects_last_error_and_count(self):
        silent_failure.note("demo.component", ValueError("first"))
        silent_failure.note("demo.component", ValueError("second"))

        status = silent_failure.status()
        assert "demo.component" in status
        assert status["demo.component"]["count"] == 2
        assert "second" in status["demo.component"]["last_error"]

    def test_repeat_failures_still_bump_the_counter_after_log_suppression(self):
        # Anti-spam suppresses the LOG on repeats but must not suppress
        # the metric -- operators need failure RATE, not just first-seen.
        for _ in range(5):
            silent_failure.note("demo.component", ValueError("x"))
        assert silent_failure.status()["demo.component"]["count"] == 5


class TestMetricsIntegration:
    def test_note_increments_prometheus_counter_every_call(self):
        silent_failure.note("demo.metric_component", ValueError("x"))
        silent_failure.note("demo.metric_component", ValueError("y"))

        rendered = metrics.render()
        assert "cortex_silent_failures_total" in rendered
        assert 'component="demo.metric_component"' in rendered
