"""Public story contract: scoped source rows become dated, attributable chapters."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcp_server.handlers import get_project_story as story


class FrozenClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 23, 12, tzinfo=timezone.utc)


@pytest.fixture
def store(monkeypatch):
    adapter = Mock()
    adapter.get_hot_memories.return_value = []
    adapter.get_memories_for_directory.return_value = []
    adapter.get_memories_for_domain.return_value = []
    monkeypatch.setattr(story, "datetime", FrozenClock)
    monkeypatch.setattr(story, "_store", None)
    # source: synthetic isolated adapter configuration, no embedding service used.
    monkeypatch.setattr(
        story,
        "get_memory_settings",
        lambda: SimpleNamespace(DB_PATH="isolated", EMBEDDING_DIM=3),
    )
    monkeypatch.setattr(story, "get_shared_store", Mock(return_value=adapter))
    return adapter


def memory(mid, created, content="Read the design notes", importance=0.5):
    return {
        "id": mid,
        "created_at": created,
        "content": content,
        "importance": importance,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("args", "method", "positional", "keywords"),
    [
        (
            {"directory": "/project", "domain": "ignored"},
            "get_memories_for_directory",
            ("/project",),
            {"min_heat": 0.0},
        ),
        (
            {"domain": "auth"},
            "get_memories_for_domain",
            ("auth",),
            {"min_heat": 0.0, "limit": 500},
        ),
        ({}, "get_hot_memories", (), {"min_heat": 0.05, "limit": 500}),
    ],
)
async def test_scope_selects_one_reader_and_reuses_store(
    store, args, method, positional, keywords
):
    first = await story.handler(args)
    assert first == {
        "period": "week",
        "chapters": [],
        "total_memories": 0,
        "story": "No memories found for this period.",
    }
    getattr(store, method).assert_called_once_with(*positional, **keywords)
    assert len(store.mock_calls) == 1
    assert await story.handler(args) == first
    story.get_shared_store.assert_called_once_with("isolated", 3)


@pytest.mark.asyncio
@pytest.mark.parametrize(("period", "days"), [("day", 1), ("week", 7), ("month", 30)])
async def test_time_window_includes_boundary_and_discards_invalid_dates(
    store, period, days
):
    cutoff = FrozenClock.now() - timedelta(days=days)
    store.get_hot_memories.return_value = [
        memory(11, cutoff.isoformat()),
        memory(12, (cutoff - timedelta(seconds=1)).isoformat()),
        memory(13, "bad-date"),
        memory(14, ""),
        memory(15, 17),
    ]
    result = await story.handler({"period": period})
    assert result["total_memories"] == 1
    assert result["period"] == period
    assert result["chapters"][0]["entries"][0]["memory_id"] == 11


@pytest.mark.asyncio
async def test_chapter_limit_keeps_recent_buckets_in_chronological_order(store):
    store.get_hot_memories.return_value = [
        memory(3, "2026-03-12T00:00:00", "Deployed the corrected launcher."),
        memory(1, "2026-01-12T00:00:00Z"),
        memory(2, "2026-02-12T00:00:00Z", "Reviewed the installation guide."),
    ]
    result = await story.handler({"period": "all", "max_chapters": 2})
    assert result["total_memories"] == 3
    assert [c["bucket_key"] for c in result["chapters"]] == ["202602", "202603"]
    assert [c["entries"][0]["memory_id"] for c in result["chapters"]] == [2, 3]
    assert (
        result["story"] == "February 2026: Reviewed the installation guide. "
        "March 2026: Deployed the corrected launcher."
    )


@pytest.mark.asyncio
async def test_chapter_entries_preserve_provenance_and_rank_decisions(store):
    rows = [memory(i, "2026-10-23T11:00:00Z", importance=i / 20) for i in range(11)]
    rows[-1].update(
        content="Fixed the broken installer. Follow-up detail.",
        tags=["installation"],
        heat=0.123456,
    )
    store.get_hot_memories.return_value = rows
    result = await story.handler({"period": "day"})
    chapter = result["chapters"][0]
    assert chapter["label"] == "11:00"
    assert chapter["memory_count"] == 11
    assert [entry["memory_id"] for entry in chapter["entries"]] == list(
        range(10, 0, -1)
    )
    assert chapter["entries"][0] == {
        "memory_id": 10,
        "headline": "Fixed the broken installer",
        "importance": 0.5,
        "heat": 0.123,
        "is_decision": True,
        "tags": ["installation"],
    }
    assert chapter["decision_count"] == 1
    assert chapter["highlight"] == "Fixed the broken installer"


@pytest.mark.asyncio
async def test_invalid_period_falls_back_and_distinguishes_expired_rows(store):
    store.get_hot_memories.return_value = [memory(1, "2001-01-01T00:00:00Z")]
    result = await story.handler({"period": "decade"})
    assert result == {
        "period": "week",
        "chapters": [],
        "total_memories": 0,
        "story": "No memories found within the last week.",
    }


@pytest.mark.asyncio
async def test_unavailable_store_is_not_reported_as_empty_history(store):
    store.get_hot_memories.side_effect = OSError("database unavailable")
    with pytest.raises(OSError, match="database unavailable"):
        await story.handler()
