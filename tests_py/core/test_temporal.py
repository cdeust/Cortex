"""Tests for mcp_server.core.temporal — date parsing, distance, recency."""

from datetime import datetime, timedelta, timezone

from mcp_server.core.temporal import (
    parse_date,
    compute_date_distance_score,
    compute_temporal_proximity,
    compute_recency_boost,
    extract_date_hints,
    is_temporal_query,
)


class TestParseDate:
    def test_iso(self):
        dt = parse_date("2024-03-15")
        assert dt == datetime(2024, 3, 15)

    def test_dd_month_yyyy(self):
        dt = parse_date("15 March 2024")
        assert dt == datetime(2024, 3, 15)

    def test_month_dd_yyyy(self):
        dt = parse_date("March 15, 2024")
        assert dt == datetime(2024, 3, 15)

    def test_empty(self):
        assert parse_date("") is None
        assert parse_date(None) is None

    def test_invalid(self):
        assert parse_date("not a date") is None

    def test_embedded_iso(self):
        dt = parse_date("Created on 2024-06-01 at noon")
        assert dt == datetime(2024, 6, 1)


class TestDateDistanceScore:
    def test_same_date(self):
        score = compute_date_distance_score("2024-03-15", ["2024-03-15"])
        assert score > 0.99

    def test_close_date(self):
        score = compute_date_distance_score("2024-03-15", ["2024-03-10"])
        assert 0.5 < score < 1.0

    def test_far_date(self):
        score = compute_date_distance_score("2024-03-15", ["2023-03-15"])
        assert score < 0.01

    def test_no_hints(self):
        assert compute_date_distance_score("2024-03-15", []) == 0.0

    def test_no_doc_date(self):
        assert compute_date_distance_score("", ["2024-03-15"]) == 0.0


class TestTemporalProximity:
    def test_exact_match(self):
        score = compute_temporal_proximity("Meeting on 2024-03-15", ["2024-03-15"])
        assert score == 1.0

    def test_partial_match(self):
        score = compute_temporal_proximity("Meeting in March 2024", ["march"])
        assert score > 0.0

    def test_no_match(self):
        score = compute_temporal_proximity("Hello world", ["2024-03-15"])
        assert score == 0.0


class TestRecencyBoost:
    def test_recent(self):
        now = datetime.now(timezone.utc).isoformat()
        boost = compute_recency_boost(now)
        assert boost > 0.1

    def test_old(self):
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        boost = compute_recency_boost(old, cutoff_days=90.0)
        assert boost == 0.0

    def test_invalid(self):
        assert compute_recency_boost("not-a-date") == 0.0
        assert compute_recency_boost(None) == 0.0


class TestIsTemporalQuery:
    def test_temporal(self):
        assert is_temporal_query("When did we last meet?")
        assert is_temporal_query("What happened yesterday?")

    def test_not_temporal(self):
        assert not is_temporal_query("What is my favorite color?")


class TestExtractDateHints:
    def test_iso(self):
        hints = extract_date_hints("Meeting on 2024-03-15")
        assert any("2024-03-15" in h for h in hints)

    def test_month(self):
        hints = extract_date_hints("Started in January")
        assert any("january" in h.lower() for h in hints)
