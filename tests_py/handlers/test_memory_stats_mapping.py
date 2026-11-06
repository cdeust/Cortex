"""memory_stats maps each store reading to its field, value for value.

The store is a stub with a distinct value per reading, so a swapped key, a
changed default or a changed rounding shows in the response. The grooming
helpers are stubbed so the ages do not depend on the clock. Written for the
ADR-1122 mutation gate when issue #728 (slice 2) changed ``handler``.
"""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.handlers import abandoned_work, memory_stats

_COUNTS = {
    "total": 11,
    "episodic": 3,
    "semantic": 5,
    "active": 7,
    "archived": 2,
    "stale": 1,
    "protected": 4,
}
_AGES = {"wiki": "2026-11-01T00:00:00+00:00", "distillation": None}


class _Store:
    has_vec = True

    def __init__(self, counts: dict[str, int]) -> None:
        self._counts = counts

    def count_memories(self):
        return self._counts

    def get_avg_heat(self):
        return 0.123456

    def count_entities(self):
        return 13

    def count_relationships(self):
        return 17

    def count_active_triggers(self):
        return 19

    def get_last_consolidation(self):
        return "2026-11-02T00:00:00+00:00"

    def get_grooming_ages(self):
        return _AGES


@pytest.fixture
def stats(monkeypatch):
    abandoned_work.reset()
    monkeypatch.setattr(
        memory_stats, "days_since", lambda iso: 1.23456 if iso else None
    )
    monkeypatch.setattr(memory_stats, "is_stale", lambda iso: iso is None)

    def run(counts):
        monkeypatch.setattr(memory_stats, "_store", _Store(counts))
        return asyncio.run(memory_stats.handler())

    yield run
    abandoned_work.reset()


def test_each_reading_reaches_its_field(stats):
    for _ in range(2):
        abandoned_work.record_abandoned("remember")
    abandoned_work.record_ended("remember", "completed")
    result = stats(_COUNTS)
    assert result == {
        "total_memories": 11,
        "episodic_count": 3,
        "semantic_count": 5,
        "active_count": 7,
        "archived_count": 2,
        "stale_count": 1,
        "protected_count": 4,
        "avg_heat": 0.1235,
        "total_entities": 13,
        "total_relationships": 17,
        "active_triggers": 19,
        "last_consolidation": "2026-11-02T00:00:00+00:00",
        "has_vector_search": True,
        "grooming_staleness": {
            "wiki": {
                "last_run_at": _AGES["wiki"],
                "days_since_last_run": 1.23,
                "stale": False,
            },
            "distillation": {
                "last_run_at": None,
                "days_since_last_run": None,
                "stale": True,
            },
        },
        "grooming_staleness_threshold_days": (
            memory_stats.GROOMING_STALENESS_THRESHOLD_DAYS
        ),
        "abandoned_workers": {
            "in_flight": {"remember": 1},
            "ended": {"remember": {"completed": 1, "raised": 0, "cancelled": 0}},
        },
    }


def test_a_count_the_store_omits_is_zero(stats):
    result = stats({})
    for field in (
        "total_memories",
        "episodic_count",
        "semantic_count",
        "active_count",
        "archived_count",
        "stale_count",
        "protected_count",
    ):
        assert result[field] == 0, field
