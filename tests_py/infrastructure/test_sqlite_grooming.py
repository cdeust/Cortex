"""Tests for grooming-staleness reads on the SQLite backend.

Repro context: ``get_grooming_ages`` existed only on ``PgStatsMixin``,
so on the SQLite backend (the plugin default) ``memory_stats`` and
``get_grooming_health`` raised ``AttributeError`` — observed on a real
30k-memory setup run, 2026-07-22. These tests pin the SQLite mirror:
``SqliteGroomingMixin.get_grooming_ages`` and
``sqlite_store_lesson_promotion.count_lesson_promotion_candidates``.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.infrastructure.sqlite_store_lesson_promotion import (
    count_lesson_promotion_candidates,
)


@pytest.fixture()
def store():
    s = SqliteMemoryStore(db_path=":memory:")
    yield s
    s.close()


def _set_useful(store: SqliteMemoryStore, memory_id: int) -> None:
    """Give a memory the usage evidence the eligibility WHERE requires."""
    store._conn.execute(
        "UPDATE memories SET useful_count = 1 WHERE id = ?", (memory_id,)
    )
    store._conn.commit()


class TestGetGroomingAges:
    def test_returns_the_three_expected_kinds(self, store):
        ages = store.get_grooming_ages()
        assert set(ages.keys()) == {"wiki", "distillation", "promotion"}
        for v in ages.values():
            assert v is None or isinstance(v, str)

    def test_empty_store_has_no_recorded_ages(self, store):
        assert store.get_grooming_ages() == {
            "wiki": None,
            "distillation": None,
            "promotion": None,
        }

    def test_wiki_is_always_none_on_sqlite(self, store):
        # Documented degradation: the tended index (wiki.pages) is
        # PG-only; SQLite has no wiki table to record tend timestamps.
        store.insert_memory({"content": "any", "tags": ["lesson"]})
        assert store.get_grooming_ages()["wiki"] is None

    def test_distillation_age_advances_after_distill_of_tag(self, store):
        store.insert_memory(
            {
                "content": "root cause: missing transaction boundary.",
                "tags": ["lesson", "distill-of:cluster-42"],
            }
        )
        ages = store.get_grooming_ages()
        assert ages["distillation"] is not None
        # Contract: parseable timestamp (days_since uses fromisoformat).
        datetime.fromisoformat(ages["distillation"])
        assert ages["promotion"] is None

    def test_promotion_age_advances_after_promoted_tag(self, store):
        store.insert_memory(
            {
                "content": "always verify provenance before merge.",
                "tags": ["lesson", "promoted:rule-7"],
            }
        )
        ages = store.get_grooming_ages()
        assert ages["promotion"] is not None
        assert ages["distillation"] is None

    def test_prefix_tag_without_lesson_tag_does_not_count(self, store):
        # The 'lesson' prefilter is semantically required (see the PG
        # twin's docstring): a distill-of: tag alone is not a
        # distillation action.
        store.insert_memory({"content": "x", "tags": ["distill-of:y"]})
        assert store.get_grooming_ages()["distillation"] is None


class TestCountLessonPromotionCandidates:
    def test_zero_on_empty_store(self, store):
        assert count_lesson_promotion_candidates(store._conn) == 0

    def test_counts_lesson_with_usage_evidence(self, store):
        mem_id = store.insert_memory({"content": "a lesson", "tags": ["lesson"]})
        assert count_lesson_promotion_candidates(store._conn) == 0  # no usage yet
        _set_useful(store, mem_id)
        assert count_lesson_promotion_candidates(store._conn) == 1

    def test_already_promoted_is_excluded(self, store):
        mem_id = store.insert_memory(
            {"content": "promoted lesson", "tags": ["lesson", "promoted:rule-1"]}
        )
        _set_useful(store, mem_id)
        assert count_lesson_promotion_candidates(store._conn) == 0

    def test_lesson_candidate_tag_qualifies(self, store):
        mem_id = store.insert_memory(
            {"content": "candidate", "tags": ["lesson-candidate"]}
        )
        _set_useful(store, mem_id)
        assert count_lesson_promotion_candidates(store._conn) == 1


class TestGroomingHealthHandlerDispatch:
    def test_promotion_count_dispatches_to_sqlite(self, store):
        # Pre-fix, the handler unconditionally ran the PG jsonb count
        # against the SQLite compat connection and raised.
        from mcp_server.handlers.get_grooming_health import (
            _count_promotion_candidates,
        )

        mem_id = store.insert_memory({"content": "a lesson", "tags": ["lesson"]})
        _set_useful(store, mem_id)
        assert _count_promotion_candidates(store) == 1
