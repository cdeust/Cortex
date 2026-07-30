"""Tests for mcp_server.core.temporal — date parsing, distance, recency."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from mcp_server.core.temporal import (
    parse_date,
    compute_date_distance_score,
    compute_temporal_proximity,
    compute_recency_boost,
    extract_date_hints,
    is_temporal_query,
)


class TestParseDate:
    """noqa DTZ001 throughout this class: parse_date is naive-by-design
    (see core/temporal.py's _try_parse_named_date docstring) — these
    literal ``datetime(...)`` values are expected outputs compared against
    it, so they must stay naive too."""

    def test_iso(self):
        dt = parse_date("2024-03-15")
        assert dt == datetime(2024, 3, 15)  # noqa: DTZ001

    def test_dd_month_yyyy(self):
        dt = parse_date("15 March 2024")
        assert dt == datetime(2024, 3, 15)  # noqa: DTZ001

    def test_month_dd_yyyy(self):
        dt = parse_date("March 15, 2024")
        assert dt == datetime(2024, 3, 15)  # noqa: DTZ001

    def test_empty(self):
        assert parse_date("") is None
        assert parse_date(None) is None

    def test_invalid(self):
        assert parse_date("not a date") is None

    def test_embedded_iso(self):
        dt = parse_date("Created on 2024-06-01 at noon")
        assert dt == datetime(2024, 6, 1)  # noqa: DTZ001

    def test_iso_datetime_is_truncated_to_its_date(self):
        """The 'T' split is what makes this a DATE parser: the time is cut,
        not carried, so hint distances compare days against days."""
        assert parse_date("2024-03-15T10:30:00Z") == datetime(2024, 3, 15)  # noqa: DTZ001

    def test_space_separated_utc_designator(self):
        """No 'T' to split on, so the 'Z' → '+00:00' rewrite is what makes
        this parseable on Python 3.10, where fromisoformat rejects 'Z'."""
        assert parse_date("2024-03-15 10:30:00Z") == datetime(
            2024, 3, 15, 10, 30, tzinfo=timezone.utc
        )


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

    def test_unparseable_doc_date(self):
        assert compute_date_distance_score("whenever", ["2024-03-15"]) == 0.0

    def test_decay_matches_the_documented_formula(self):
        """exp(-delta_days / scale_days), delta in whole days, default scale."""
        score = compute_date_distance_score("2024-03-20", ["2024-03-15"])
        assert score == pytest.approx(math.exp(-5.0 / 14.0), rel=1e-9)

    def test_scale_days_is_honoured(self):
        score = compute_date_distance_score("2024-03-20", ["2024-03-15"], 7.0)
        assert score == pytest.approx(math.exp(-5.0 / 7.0), rel=1e-9)

    def test_best_hint_wins(self):
        score = compute_date_distance_score("2024-03-20", ["2023-01-01", "2024-03-19"])
        assert score == pytest.approx(math.exp(-1.0 / 14.0), rel=1e-9)


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

    def test_no_hints_scores_zero(self):
        assert compute_temporal_proximity("Meeting on 2024-03-15", []) == 0.0

    def test_partial_match_scores_exactly_half(self):
        score = compute_temporal_proximity("Meeting in March 2024", ["15 March 2024"])
        assert score == 0.5

    def test_exact_match_beats_a_partial_one(self):
        score = compute_temporal_proximity(
            "Meeting in March 2024", ["15 March 2024", "March 2024"]
        )
        assert score == 1.0

    def test_token_at_the_minimum_length_is_too_generic(self):
        """The threshold is `> 3`: a 3-character token ('may') is a month
        abbreviation-sized coincidence, not evidence of the same date."""
        score = compute_temporal_proximity("we met in may that year", ["may 1999"])
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

    def test_unsupported_type_scores_zero(self):
        assert compute_recency_boost(1712345678) == 0.0

    def test_boost_halves_after_one_halflife(self):
        """boost = boost_max * exp(-age * ln2 / halflife): at age = halflife
        the default 0.15 must read exactly 0.075."""
        aged = datetime.now(timezone.utc) - timedelta(days=30)
        assert compute_recency_boost(aged.isoformat()) == pytest.approx(0.075, rel=1e-6)

    def test_datetime_input_is_accepted(self):
        aged = datetime.now(timezone.utc) - timedelta(days=30)
        assert compute_recency_boost(aged) == pytest.approx(0.075, rel=1e-6)

    def test_naive_timestamp_is_read_as_utc(self):
        aged = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        assert compute_recency_boost(aged.isoformat()) == pytest.approx(0.075, rel=1e-6)

    def test_utc_designator_is_accepted(self):
        """'Z' → '+00:00' before fromisoformat, which rejects 'Z' on 3.10."""
        aged = datetime.now(timezone.utc) - timedelta(days=30)
        stamped = aged.isoformat().replace("+00:00", "Z")
        assert compute_recency_boost(stamped) == pytest.approx(0.075, rel=1e-6)

    def test_default_cutoff_is_ninety_days(self):
        aged = datetime.now(timezone.utc) - timedelta(days=90.5)
        assert compute_recency_boost(aged.isoformat()) == 0.0


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

    def test_named_date_hint_is_the_whole_match(self):
        """The hint must be the full date, not the pattern's first group
        (the day number), which no document would match on."""
        assert "15 March 2024" in extract_date_hints("Met on 15 March 2024")
