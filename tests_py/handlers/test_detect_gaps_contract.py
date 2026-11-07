"""Gap API tests using dated store rows and an isolated profile boundary."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcp_server.handlers import detect_gaps as gaps


class FrozenClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 23, tzinfo=timezone.utc)


@pytest.fixture
def store(monkeypatch):
    adapter = Mock()
    adapter.get_isolated_entities.return_value = []
    adapter.count_memories.return_value = {"total": 0}
    adapter.get_domain_entity_counts.return_value = []
    monkeypatch.setattr(gaps, "datetime", FrozenClock)
    monkeypatch.setattr(gaps, "_store", None)
    # source: synthetic isolated adapter configuration, no embedding service used.
    settings = SimpleNamespace(DB_PATH="isolated", EMBEDDING_DIM=3)
    monkeypatch.setattr(gaps, "get_memory_settings", lambda: settings)
    monkeypatch.setattr(gaps, "get_shared_store", Mock(return_value=adapter))
    monkeypatch.setattr(gaps, "load_profiles", lambda: {})
    return adapter


@pytest.mark.asyncio
async def test_empty_store_is_empty_and_store_factory_is_reused(store):
    expected = {"total_gaps": 0, "gaps": [], "by_type": {}, "domain_filter": "global"}
    assert await gaps.handler() == expected
    assert await gaps.handler() == expected
    gaps.get_shared_store.assert_called_once_with("isolated", 3)


@pytest.mark.asyncio
async def test_entity_gap_preserves_identity_excludes_connected_and_caps_results(store):
    store.get_isolated_entities.return_value = [
        {"id": 0, "name": "connected", "type": "file", "relationship_count": 1},
        *[
            {
                "id": i,
                "name": f"orphan-{i}",
                "type": "function",
                "domain": "auth",
                "heat": 0.123456,
            }
            for i in range(1, 13)
        ],
    ]
    result = await gaps.handler(
        {"include_domain_gaps": False, "include_temporal_gaps": False}
    )
    assert result["total_gaps"] == 10
    assert result["by_type"] == {"isolated_entity": 10}
    assert [g["entity_id"] for g in result["gaps"]] == list(range(1, 11))
    assert result["gaps"][0] == {
        "entity_id": 1,
        "entity_name": "orphan-1",
        "entity_type": "function",
        "domain": "auth",
        "relationship_count": 0,
        "heat": 0.1235,
        "gap_type": "isolated_entity",
    }
    store.get_isolated_entities.assert_called_once_with(limit=20)
    store.count_memories.assert_not_called()


@pytest.mark.asyncio
async def test_sparse_domain_uses_cross_domain_average_and_strict_half_boundary(store):
    store.count_memories.return_value = {"total": 80}
    store.get_domain_entity_counts.return_value = [
        {"domain": "", "count": 0},
        {"domain": "sparse", "count": 5},
        {"domain": "boundary", "count": 10},
        {"domain": "rich", "count": 65},
    ]
    result = await gaps.handler(
        {"include_entity_gaps": False, "include_temporal_gaps": False}
    )
    assert result["gaps"] == [
        {
            "domain": "sparse",
            "entity_count": 5,
            "avg_entity_count": 20.0,
            "coverage_ratio": 0.25,
            "gap_type": "sparse_domain",
        }
    ]
    assert result["total_gaps"] == 1
    assert result["by_type"] == {"sparse_domain": 1}


@pytest.mark.asyncio
async def test_nonempty_memory_store_without_domain_entities_has_no_sparse_gap(store):
    store.count_memories.return_value = {"total": 10}
    result = await gaps.handler(
        {"include_entity_gaps": False, "include_temporal_gaps": False}
    )
    assert result["gaps"] == []


@pytest.mark.asyncio
async def test_temporal_drift_uses_latest_access_ignores_invalid_and_honors_boundary(
    store,
):
    records = {
        "fresh": [{"last_accessed": "2020-01-01"}, {"last_accessed": "2026-10-22"}],
        "old": [{"last_accessed": "2026-09-01"}],
        "boundary": [{"last_accessed": "2026-09-23T00:00:00Z"}],
        "empty": [],
        "missing": [{}],
        "invalid": [{"last_accessed": "not-a-date"}],
    }
    store.get_domain_entity_counts.return_value = [
        {"domain": d} for d in ["", *records]
    ]
    store.get_memories_for_domain.side_effect = lambda domain, **kwargs: records[domain]
    result = await gaps.handler(
        {
            "include_entity_gaps": False,
            "include_domain_gaps": False,
            "stale_threshold_days": 30,
        }
    )
    assert result["gaps"] == [
        {
            "domain": "old",
            "days_since_access": 52,
            "memory_count": 1,
            "gap_type": "temporal_drift",
        }
    ]
    assert result["by_type"] == {"temporal_drift": 1}
    assert store.get_memories_for_domain.call_count == len(records)
    assert all(
        call.kwargs == {"min_heat": 0.0, "limit": 10}
        for call in store.get_memories_for_domain.call_args_list
    )


@pytest.mark.asyncio
async def test_disabled_store_axes_still_return_scoped_cognitive_provenance(
    store, monkeypatch
):
    profiles = {"domains": {"auth": {}, "docs": {}}, "sessions": [{"id": "session-a"}]}
    monkeypatch.setattr(gaps, "load_profiles", lambda: profiles)
    detector = Mock(return_value=[{"type": "tool", "evidence": "no read"}])
    monkeypatch.setattr(gaps, "detect_blind_spots", detector)
    result = await gaps.handler(
        {
            "domain": "auth",
            "include_entity_gaps": False,
            "include_domain_gaps": False,
            "include_temporal_gaps": False,
        }
    )
    assert result == {
        "total_gaps": 1,
        "domain_filter": "auth",
        "by_type": {"cognitive_blind_spot": 1},
        "gaps": [
            {
                "type": "tool",
                "evidence": "no read",
                "domain": "auth",
                "gap_type": "cognitive_blind_spot",
            }
        ],
    }
    detector.assert_called_once_with(
        domain_id="auth",
        domain_conversations=profiles["sessions"],
        all_conversations=profiles["sessions"],
        profiles=profiles,
    )
    assert store.mock_calls == []


@pytest.mark.asyncio
async def test_cognitive_global_scan_caps_domains_and_spots(store, monkeypatch):
    profiles = {"domains": {f"d{i}": {} for i in range(6)}, "sessions": []}
    monkeypatch.setattr(gaps, "load_profiles", lambda: profiles)
    detector = Mock(
        side_effect=lambda **kwargs: [{"evidence": f"spot-{i}"} for i in range(4)]
    )
    monkeypatch.setattr(gaps, "detect_blind_spots", detector)
    result = await gaps.handler(
        {
            "include_entity_gaps": False,
            "include_domain_gaps": False,
            "include_temporal_gaps": False,
        }
    )
    assert result["total_gaps"] == 10
    assert [call.kwargs["domain_id"] for call in detector.call_args_list] == [
        "d0",
        "d1",
        "d2",
        "d3",
        "d4",
    ]
    assert [g["domain"] for g in result["gaps"]] == ["d0"] * 3 + ["d1"] * 3 + [
        "d2"
    ] * 3 + ["d3"]
    assert all(g["evidence"] != "spot-3" for g in result["gaps"])
