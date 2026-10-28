"""Issue #685: dependency failures must reach the caller before a fallback acts."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from mcp_server.handlers import query_methodology, rebuild_profiles
from mcp_server.handlers.remember_helpers import try_curation
from mcp_server.observability import silent_failure


@pytest.fixture(autouse=True)
def _reset_failures():
    silent_failure.reset()
    yield
    silent_failure.reset()


def test_dedup_search_failure_is_not_permission_to_create():
    store = MagicMock()
    error = RuntimeError("dedup index unavailable")
    store.search_vectors.side_effect = error

    with pytest.raises(RuntimeError, match="dedup index unavailable") as caught:
        try_curation("memory", [1.0], False, store, MagicMock(), [], 1.0)

    assert caught.value is error


def test_dedup_merge_failure_is_not_permission_to_create(monkeypatch):
    store = MagicMock()
    store.search_vectors.return_value = [(1, 0.0)]
    candidate = {"content": "memory", "embedding": [1.0]}
    monkeypatch.setattr(
        "mcp_server.handlers.remember_helpers.MemoryRows.read",
        lambda *_args: MagicMock(get_memory=lambda _mid: candidate),
    )
    monkeypatch.setattr(
        "mcp_server.handlers.remember_helpers.curation.decide_curation_action",
        lambda *_args: "merge",
    )
    monkeypatch.setattr(
        "mcp_server.handlers.remember_helpers.curation.detect_contradictions",
        lambda *_args: False,
    )
    error = RuntimeError("merge write failed")
    store.update_memory_compression.side_effect = error

    with pytest.raises(RuntimeError, match="merge write failed") as caught:
        try_curation("memory", [1.0], False, store, MagicMock(), [], 1.0)

    assert caught.value is error


@pytest.mark.parametrize("failure", ["read", "timestamp", "naive"])
def test_freshness_failure_reaches_handler_before_scan(monkeypatch, failure):
    loader = MagicMock(return_value={"updatedAt": "invalid-timestamp"})
    if failure == "naive":
        loader.return_value = {"updatedAt": "2026-01-01T00:00:00"}
    error = OSError("profiles unreadable")
    if failure == "read":
        loader.side_effect = error
    monkeypatch.setattr(rebuild_profiles, "load_profiles", loader)
    scan = MagicMock()
    save = MagicMock()
    monkeypatch.setattr(rebuild_profiles, "discover_all_memories", scan)
    monkeypatch.setattr(rebuild_profiles, "save_profiles", save)

    with pytest.raises((OSError, ValueError)) as caught:
        asyncio.run(rebuild_profiles.handler({}))

    if failure == "read":
        assert caught.value is error
    else:
        assert "force=true" in str(caught.value)
    scan.assert_not_called()
    save.assert_not_called()


@pytest.mark.parametrize(
    ("domain", "directory", "method"),
    [
        ("cortex", "", "get_memories_for_domain"),
        ("", "/fixture", "get_memories_for_directory"),
        ("", "", "get_hot_memories"),
    ],
)
@pytest.mark.parametrize("cold_start", [False, True])
def test_hot_memory_read_failure_reaches_tool_handler(
    monkeypatch, domain, directory, method, cold_start
):
    store = MagicMock()
    error = RuntimeError("hot memory read failed")
    getattr(store, method).side_effect = error
    monkeypatch.setattr(query_methodology, "_try_get_memory_store", lambda: store)
    monkeypatch.setattr(query_methodology, "load_profiles", lambda: {"domains": {}})
    monkeypatch.setattr(
        query_methodology,
        "detect_domain",
        lambda *_args: {"domain": domain, "coldStart": cold_start},
    )

    # Cold-start injects with no domain, so it reads the directory/global path.
    if cold_start:
        store.get_memories_for_directory.side_effect = error
        store.get_hot_memories.side_effect = error
    with pytest.raises(RuntimeError, match="hot memory read failed") as caught:
        asyncio.run(query_methodology.handler({"cwd": directory}))

    assert caught.value is error
