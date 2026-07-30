"""Tests for mcp_server.core.context_assembly.stage_detector (#196).

stage_detector.py has 6 live importers (pg_recall.assemble_context,
tests exercising StageAwareContextAssembler via mocked detectors) but
sat at 0% coverage — the importing paths never exercised its own
branches directly. These tests cover ExplicitStageDetector,
TemporalStageDetector, and CompositeStageDetector directly.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from mcp_server.core.context_assembly.stage_detector import (
    CompositeStageDetector,
    ExplicitStageDetector,
    TemporalStageDetector,
)


class TestExplicitStageDetector:
    def test_stage_of_returns_field_value(self):
        det = ExplicitStageDetector(field="plan_id")
        assert det.stage_of({"plan_id": "p1"}) == "p1"

    def test_stage_of_missing_field_returns_fallback(self):
        det = ExplicitStageDetector(field="plan_id", fallback="none")
        assert det.stage_of({}) == "none"

    def test_stage_of_empty_string_returns_fallback(self):
        det = ExplicitStageDetector(field="plan_id", fallback="none")
        assert det.stage_of({"plan_id": ""}) == "none"

    def test_stage_of_coerces_non_string_to_string(self):
        det = ExplicitStageDetector(field="plan_id")
        assert det.stage_of({"plan_id": 42}) == "42"

    def test_default_field_and_fallback(self):
        det = ExplicitStageDetector()
        assert det.stage_of({}) == "default"

    def test_all_stages_deduplicates_preserving_first_seen_order(self):
        det = ExplicitStageDetector(field="plan_id")
        corpus = [
            {"plan_id": "a"},
            {"plan_id": "b"},
            {"plan_id": "a"},
            {"plan_id": "c"},
        ]
        assert det.all_stages(corpus) == ["a", "b", "c"]

    def test_all_stages_empty_corpus_returns_empty_list(self):
        det = ExplicitStageDetector()
        assert det.all_stages([]) == []


class TestTemporalStageDetectorParsing:
    """noqa DTZ001 throughout this class: `_parse_ts` is naive-by-design
    (see its docstring in stage_detector.py) — these literal
    ``datetime(...)`` values are expected outputs compared against it, or
    inputs fed straight back through, so they stay naive too."""

    def test_parse_iso_date_string(self):
        det = TemporalStageDetector()
        ts = det._parse_ts("2024-03-15")
        assert ts == datetime(2024, 3, 15)  # noqa: DTZ001

    def test_parse_iso_datetime_with_z_suffix(self):
        det = TemporalStageDetector()
        ts = det._parse_ts("2024-03-15T10:00:00Z")
        assert ts is not None
        assert ts.year == 2024 and ts.month == 3 and ts.day == 15

    def test_parse_beam_month_name_format(self):
        det = TemporalStageDetector()
        ts = det._parse_ts("March-15-2024")
        assert ts == datetime(2024, 3, 15)  # noqa: DTZ001

    def test_parse_beam_format_case_insensitive(self):
        det = TemporalStageDetector()
        ts = det._parse_ts("march-15-2024")
        assert ts == datetime(2024, 3, 15)  # noqa: DTZ001

    def test_parse_datetime_object_passthrough(self):
        det = TemporalStageDetector()
        dt = datetime(2024, 1, 1)  # noqa: DTZ001
        assert det._parse_ts(dt) is dt

    def test_parse_none_returns_none(self):
        det = TemporalStageDetector()
        assert det._parse_ts(None) is None

    def test_parse_empty_string_returns_none(self):
        det = TemporalStageDetector()
        assert det._parse_ts("") is None

    def test_parse_unparseable_string_returns_none(self):
        det = TemporalStageDetector()
        assert det._parse_ts("not a date at all") is None

    def test_parse_malformed_beam_format_returns_none(self):
        det = TemporalStageDetector()
        assert det._parse_ts("NotAMonth-99-abcd") is None

    def test_parse_two_part_dash_string_returns_none(self):
        det = TemporalStageDetector()
        assert det._parse_ts("only-two") is None


class TestTemporalStageDetectorAllStages:
    def test_groups_by_gap_threshold(self):
        det = TemporalStageDetector(gap_hours=1.0)
        corpus = [
            {"id": 1, "created_at": "2024-01-01T00:00:00"},
            {"id": 2, "created_at": "2024-01-01T00:30:00"},  # within gap
            {"id": 3, "created_at": "2024-01-01T05:00:00"},  # exceeds gap
        ]
        stages = det.all_stages(corpus)
        assert stages == ["stage-1", "stage-2"]

    def test_memories_without_timestamp_excluded(self):
        det = TemporalStageDetector()
        corpus = [
            {"id": 1, "created_at": "2024-01-01T00:00:00"},
            {"id": 2},  # no timestamp — skipped
        ]
        stages = det.all_stages(corpus)
        assert stages == ["stage-1"]

    def test_empty_corpus_returns_empty_list(self):
        det = TemporalStageDetector()
        assert det.all_stages([]) == []

    def test_stage_of_uses_cache_after_all_stages(self):
        det = TemporalStageDetector(gap_hours=1.0)
        corpus = [
            {"id": 1, "created_at": "2024-01-01T00:00:00"},
            {"id": 2, "created_at": "2024-01-01T05:00:00"},
        ]
        det.all_stages(corpus)
        assert det.stage_of({"id": 1}) == "stage-1"
        assert det.stage_of({"id": 2}) == "stage-2"

    def test_stage_of_falls_back_to_day_bucket_without_precomputation(self):
        det = TemporalStageDetector()
        stage = det.stage_of({"id": 99, "created_at": "2024-03-15T10:00:00"})
        assert stage == "day-2024-03-15"

    def test_stage_of_no_timestamp_returns_default(self):
        det = TemporalStageDetector()
        assert det.stage_of({"id": 99}) == "default"

    def test_stage_of_uses_id_field_fallback_for_cache_key(self):
        det = TemporalStageDetector(gap_hours=1.0)
        corpus = [{"memory_id": 1, "created_at": "2024-01-01T00:00:00"}]
        det.all_stages(corpus)
        assert det.stage_of({"memory_id": 1}) == "stage-1"


class TestCompositeStageDetector:
    def test_requires_at_least_one_detector(self):
        with pytest.raises(ValueError):
            CompositeStageDetector([])

    def test_uses_first_detector_that_returns_non_fallback_stage(self):
        primary = ExplicitStageDetector(field="plan_id", fallback="default")
        secondary = ExplicitStageDetector(field="agent_topic", fallback="default")
        composite = CompositeStageDetector([primary, secondary])
        assert composite.stage_of({"plan_id": "p1"}) == "p1"

    def test_falls_through_to_next_detector_on_fallback(self):
        primary = ExplicitStageDetector(field="plan_id", fallback="default")
        secondary = ExplicitStageDetector(field="agent_topic", fallback="default")
        composite = CompositeStageDetector([primary, secondary])
        assert composite.stage_of({"agent_topic": "t1"}) == "t1"

    def test_skips_temporal_day_bucket_stages(self):
        primary = TemporalStageDetector()
        secondary = ExplicitStageDetector(field="agent_topic", fallback="default")
        composite = CompositeStageDetector([primary, secondary])
        memory = {"created_at": "2024-01-01T00:00:00", "agent_topic": "t1"}
        assert composite.stage_of(memory) == "t1"

    def test_all_fallback_returns_first_detectors_output(self):
        primary = ExplicitStageDetector(field="plan_id", fallback="default")
        secondary = ExplicitStageDetector(field="agent_topic", fallback="default")
        composite = CompositeStageDetector([primary, secondary])
        assert composite.stage_of({}) == "default"

    def test_all_stages_unions_and_dedupes_across_detectors(self):
        primary = ExplicitStageDetector(field="plan_id")
        secondary = ExplicitStageDetector(field="agent_topic")
        composite = CompositeStageDetector([primary, secondary])
        corpus = [{"plan_id": "a", "agent_topic": "a"}, {"plan_id": "b"}]
        stages = composite.all_stages(corpus)
        # primary (plan_id) contributes ["a", "b"]; secondary (agent_topic)
        # contributes ["a", "default"] (second item lacks agent_topic) —
        # union, de-duped, in first-seen order across detectors in turn.
        assert stages == ["a", "b", "default"]
