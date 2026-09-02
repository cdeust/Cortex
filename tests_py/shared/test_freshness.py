"""Unit tests for shared.freshness (fleet-watch #110).

Pure functions, fixed clock — no DB, no network. The behavior under test is
the one the harness-comparison rev.2 flagged as missing: a recalled memory must
carry its age, provenance grade, and stale flag so a months-old fact is
distinguishable from a fresh one in context.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mcp_server.shared.freshness import humanize_age, provenance_suffix

_NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)


def _ago(**kw) -> datetime:
    return _NOW - timedelta(**kw)


def test_humanize_age_buckets() -> None:
    assert humanize_age(_ago(seconds=30), _NOW) == "just now"
    assert humanize_age(_ago(minutes=5), _NOW) == "5m ago"
    assert humanize_age(_ago(hours=3), _NOW) == "3h ago"
    assert humanize_age(_ago(days=5), _NOW) == "5d ago"
    assert humanize_age(_ago(days=45), _NOW) == "1mo ago"
    assert humanize_age(_ago(days=400), _NOW) == "1y ago"


def test_humanize_age_unknown_inputs() -> None:
    assert humanize_age(None, _NOW) == ""
    assert humanize_age("", _NOW) == ""
    assert humanize_age("not-a-date", _NOW) == ""


def test_humanize_age_iso_string_and_naive() -> None:
    # ISO string with Z, and a naive datetime, are both treated as UTC.
    naive = datetime(2026, 8, 21, 12, 0, 0)  # noqa: DTZ001 — coercion under test
    assert humanize_age("2026-08-21T12:00:00Z", _NOW) == "3d ago"
    assert humanize_age(naive, _NOW) == "3d ago"


def test_provenance_suffix_full() -> None:
    mem = {
        "created_at": _ago(days=90),
        "source_attribution": "verified",
        "is_stale": True,
    }
    suffix = provenance_suffix(mem, _NOW)
    assert "3mo ago" in suffix
    assert "src=verified" in suffix
    assert "⚠stale" in suffix


def test_provenance_suffix_omits_unknown_and_absent() -> None:
    # "unknown" grade and missing timestamp/stale -> nothing to show.
    assert provenance_suffix({"source_attribution": "unknown"}, _NOW) == ""
    assert provenance_suffix({}, _NOW) == ""


def test_provenance_suffix_partial() -> None:
    # Only a grade present: no age, no stale marker.
    mem = {"source_attribution": "verifiable"}
    assert provenance_suffix(mem, _NOW) == "src=verifiable"
