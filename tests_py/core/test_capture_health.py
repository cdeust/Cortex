"""``assess``: the verdict on auto-capture, from the evidence handed in (issue #660).

Contract: ok is False iff (a) the latest skip is inside WINDOW_SECONDS and either no
capture was ever processed or FAILURE_RUN skips follow the last processed one, or
(b) the oldest pending spool file is older than the stall limit.
"""

from __future__ import annotations

from mcp_server.core.capture_health import (
    CAPTURE_PROCESSED,
    CAPTURE_SKIPPED,
    FAILURE_RUN,
    WINDOW_SECONDS,
    assess,
)

# source: arbitrary fixture clock (the verdict depends only on differences)
NOW = 1_000_000.0
# source: arbitrary fixture stall limit passed to assess as a parameter
STALL = 600.0


def _verdict(events, age=None, rejected=0):
    return assess(
        events, oldest_pending_age=age, stall_seconds=STALL, rejected=rejected, now=NOW
    )


def _skips(n, start=NOW - 100):
    return [(start + i, CAPTURE_SKIPPED) for i in range(n)]


def test_no_attempts_is_ok_and_says_so() -> None:
    v = _verdict([])
    assert v.ok and "0 processed" in v.detail and "0 skipped" in v.detail


def test_never_processed_with_attempts_fails_even_for_one_skip() -> None:
    v = _verdict(_skips(1))
    assert not v.ok
    assert "1 captures skipped and none ever processed" in v.detail
    assert "telemetry.jsonl" in v.fix and "drain.log" in v.fix


def test_the_reporters_outage_1730_skips_no_success_fails_with_counts() -> None:
    v = _verdict(_skips(1730))
    assert not v.ok and "1730 captures skipped" in v.detail


def test_failure_run_after_a_success_fails_at_the_threshold_not_below() -> None:
    ok_then = [(NOW - 500, CAPTURE_PROCESSED)]
    assert _verdict(ok_then + _skips(FAILURE_RUN - 1)).ok
    v = _verdict(ok_then + _skips(FAILURE_RUN))
    assert not v.ok and f"{FAILURE_RUN} captures skipped since the last" in v.detail


def test_a_success_after_the_skips_clears_the_run() -> None:
    events = _skips(50) + [(NOW - 10, CAPTURE_PROCESSED)]
    assert _verdict(events).ok


def test_skips_before_the_last_success_do_not_count_toward_the_run() -> None:
    events = _skips(50, start=NOW - 300) + [(NOW - 200, CAPTURE_PROCESSED)]
    events += _skips(FAILURE_RUN - 1, start=NOW - 100)
    assert _verdict(events).ok


def test_a_run_whose_latest_skip_is_older_than_the_window_is_history() -> None:
    old = NOW - WINDOW_SECONDS - 1
    v = _verdict(_skips(100, start=old - 100))
    assert v.ok and "100 skipped" in v.detail


def test_the_window_boundary_is_inclusive() -> None:
    assert not _verdict([(NOW - WINDOW_SECONDS, CAPTURE_SKIPPED)]).ok


def test_events_are_ordered_by_timestamp_not_by_position() -> None:
    events = [(NOW - 10, CAPTURE_PROCESSED)] + _skips(10, start=NOW - 400)
    assert _verdict(events).ok


def test_other_operations_are_ignored() -> None:
    assert _verdict([(NOW - 1, "remember"), (NOW - 1, "capture_spool_stalled")]).ok


def test_stalled_spool_fails_alone_and_names_the_age() -> None:
    v = _verdict([(NOW - 5, CAPTURE_PROCESSED)], age=STALL + 1)
    assert not v.ok and "not being drained" in v.detail and "601s" in v.detail


def test_spool_at_the_stall_limit_is_not_stalled() -> None:
    assert _verdict([], age=STALL).ok


def test_both_problems_are_both_reported() -> None:
    v = _verdict(_skips(9), age=STALL + 1, rejected=3)
    assert not v.ok
    assert "auto-capture is failing" in v.detail and "not being drained" in v.detail
    assert "3 rejected" in v.detail
