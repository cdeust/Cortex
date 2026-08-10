"""Tests for the write-class classification choke point (M-D2/M-D3, 7.1).

``classify_write_class`` is the single contract 7.4's future explicit
``write_class`` column re-sources from — these tests pin the taxonomy
table from ``scratchpad/memoire-qui-comprend-design.md`` §M-D2.
"""

from __future__ import annotations

from mcp_server.shared.write_class import (
    ALL_WRITE_CLASSES,
    AUTO,
    DELIBERATE,
    DERIVED,
    MECHANICAL,
    NON_DELIBERATE_EXACT_SOURCES,
    NON_DELIBERATE_SOURCE_PREFIXES,
    classify_write_class,
    validate_write_class,
)


class TestAutoClass:
    def test_post_tool_capture_is_auto(self):
        assert classify_write_class({"source": "post_tool_capture"}) == AUTO

    def test_bare_source_string_works(self):
        assert classify_write_class("post_tool_capture") == AUTO


class TestDerivedClass:
    def test_consolidation_is_derived(self):
        # memify_derive's exact source value (handlers/consolidation/
        # memify_derive.py:245).
        assert classify_write_class({"source": "consolidation"}) == DERIVED

    def test_cls_consolidation_is_derived(self):
        # CLS semantic promotion — measured DB source, 59 rows dev DB.
        assert classify_write_class({"source": "cls-consolidation"}) == DERIVED

    def test_cls_prefix_family_is_derived(self):
        assert classify_write_class({"source": "cls-anything-else"}) == DERIVED

    def test_sleep_compute_is_derived(self):
        # handlers/consolidation/sleep.py::_store_narration — dream-replay
        # auto-narration, added 7.4 direct-writer inventory.
        assert classify_write_class({"source": "sleep-compute"}) == DERIVED


class TestMechanicalClass:
    def test_codebase_analyze_is_mechanical(self):
        assert classify_write_class({"source": "codebase_analyze"}) == MECHANICAL

    def test_seed_project_is_mechanical(self):
        assert classify_write_class({"source": "seed_project"}) == MECHANICAL

    def test_ingest_codebase_is_mechanical(self):
        assert classify_write_class({"source": "ingest_codebase"}) == MECHANICAL

    def test_backfill_prefix_family_is_mechanical(self):
        # Measured DB source values: "backfill:-Users-cdeust-Developments-*"
        # (one per scanned directory).
        assert (
            classify_write_class({"source": "backfill:-Users-x-Developments-Cortex"})
            == MECHANICAL
        )

    def test_wiki_seed_codebase_prefix_is_mechanical(self):
        # handlers/wiki_seed_codebase.py — one memory per seeded file.
        assert classify_write_class({"source": "seed:src/main.py"}) == MECHANICAL

    def test_ingest_codebase_docs_variant_is_mechanical(self):
        # handlers/ingest_docs_content_writers.py
        assert classify_write_class({"source": "ingest_codebase:docs"}) == MECHANICAL

    def test_wiki_pointer_memory_is_mechanical(self):
        # handlers/wiki_write.py / wiki_adr.py::_store_pointer_memory —
        # protected pointer memories are structural indexing, not
        # user-authored content.
        assert classify_write_class({"source": "wiki://reference/foo.md"}) == MECHANICAL


class TestDeliberateClass:
    def test_feature_source_is_deliberate(self):
        assert classify_write_class({"source": "feature"}) == DELIBERATE

    def test_lesson_source_is_deliberate(self):
        assert classify_write_class({"source": "lesson"}) == DELIBERATE

    def test_bug_fix_source_is_deliberate(self):
        assert classify_write_class({"source": "bug-fix"}) == DELIBERATE

    def test_empty_source_defaults_deliberate_not_auto(self):
        """Safe default: unclassified content is never assumed to be
        flood/noise, so it is never subject to fold-style regulation."""
        assert classify_write_class({"source": ""}) == DELIBERATE
        assert classify_write_class({}) == DELIBERATE
        assert classify_write_class(None) == DELIBERATE

    def test_unknown_source_defaults_deliberate(self):
        assert classify_write_class({"source": "some-future-source-kind"}) == DELIBERATE


class TestExplicitColumnForwardCompat:
    def test_explicit_write_class_wins_over_source(self):
        """7.4 forward-compat: an explicit write_class value short-circuits
        source-based inference — the future explicit-column fast path."""
        memory = {"source": "post_tool_capture", "write_class": "deliberate"}
        assert classify_write_class(memory) == DELIBERATE

    def test_invalid_explicit_write_class_falls_back_to_source(self):
        memory = {"source": "post_tool_capture", "write_class": "not-a-real-class"}
        assert classify_write_class(memory) == AUTO


class TestNonDeliberateSqlMirror:
    """NON_DELIBERATE_EXACT_SOURCES / NON_DELIBERATE_SOURCE_PREFIXES
    (INC7.2) -- the SQL-side mirror consumed by
    pg_store_memory_reheat.py::list_deliberate_below_target. Every real
    measured DB source that should be excluded from the deliberate
    reheat scan must appear in one of these two exports.
    """

    def test_seed_project_is_in_exact_sources(self):
        assert "seed_project" in NON_DELIBERATE_EXACT_SOURCES

    def test_ingest_codebase_is_in_exact_sources(self):
        assert "ingest_codebase" in NON_DELIBERATE_EXACT_SOURCES

    def test_codebase_analyze_is_in_exact_sources(self):
        assert "codebase_analyze" in NON_DELIBERATE_EXACT_SOURCES

    def test_post_tool_capture_is_in_exact_sources(self):
        assert "post_tool_capture" in NON_DELIBERATE_EXACT_SOURCES

    def test_cls_prefix_is_in_prefixes(self):
        assert "cls" in NON_DELIBERATE_SOURCE_PREFIXES

    def test_backfill_prefix_is_in_prefixes(self):
        assert "backfill:" in NON_DELIBERATE_SOURCE_PREFIXES

    def test_bare_cls_is_a_prefix_not_an_exact_string(self):
        # The bug: pg_store_memory_reheat.py's OWN hardcoded tuple compared
        # "cls" as an EXACT string, but the real DB value is
        # "cls-consolidation" (a prefix family). "cls" must be a prefix
        # entry, not an exact-match entry, or a real "cls-*" row would
        # slip through an exact-match-only filter again.
        assert "cls" in NON_DELIBERATE_SOURCE_PREFIXES
        assert "cls" not in NON_DELIBERATE_EXACT_SOURCES

    def test_mirror_agrees_with_classify_write_class_on_every_class(self):
        non_deliberate_sources = (
            "post_tool_capture",
            "seed_project",
            "ingest_codebase",
            "codebase_analyze",
            "cls-consolidation",
            "consolidation",
            "backfill:-Users-x",
        )
        deliberate_sources = ("feature", "lesson")

        for source in non_deliberate_sources:
            is_excluded = source in NON_DELIBERATE_EXACT_SOURCES or source.startswith(
                NON_DELIBERATE_SOURCE_PREFIXES
            )
            assert classify_write_class(source) != DELIBERATE, source
            assert is_excluded, source

        for source in deliberate_sources:
            is_excluded = source in NON_DELIBERATE_EXACT_SOURCES or source.startswith(
                NON_DELIBERATE_SOURCE_PREFIXES
            )
            assert classify_write_class(source) == DELIBERATE, source
            assert not is_excluded, source


class TestTaxonomyInvariants:
    def test_all_classes_enumerated(self):
        assert set(ALL_WRITE_CLASSES) == {AUTO, DELIBERATE, DERIVED, MECHANICAL}

    def test_every_class_reachable(self):
        """Sanity: at least one real source value maps to each class."""
        seen = {
            classify_write_class({"source": s})
            for s in (
                "post_tool_capture",
                "feature",
                "consolidation",
                "codebase_analyze",
            )
        }
        assert seen == {AUTO, DELIBERATE, DERIVED, MECHANICAL}


class TestValidateWriteClass:
    """7.4: the strict write-time contract — distinct from the permissive
    ``classify_write_class`` fallback tested above."""

    def test_none_is_accepted_no_raise(self):
        validate_write_class(None)  # no exception

    def test_each_known_class_is_accepted(self):
        for cls in ALL_WRITE_CLASSES:
            validate_write_class(cls)  # no exception

    def test_unknown_value_raises_value_error(self):
        import pytest

        with pytest.raises(ValueError, match="not-a-real-class"):
            validate_write_class("not-a-real-class")

    def test_error_message_names_all_valid_classes(self):
        import pytest

        with pytest.raises(ValueError) as exc_info:
            validate_write_class("bogus")
        message = str(exc_info.value)
        for cls in ALL_WRITE_CLASSES:
            assert cls in message

    def test_empty_string_is_invalid(self):
        """Empty string is not None — it's an explicit (wrong) value."""
        import pytest

        with pytest.raises(ValueError):
            validate_write_class("")
