"""Handler-layer tests for response-budget wiring (bounded-I/O Phase 1).

Each of the four response surfaces named in docs/provenance/bounded-io-plan.md
— recall, query_methodology, unified_search, wiki_read — must ship
payloads that fit the host's tool-result cap, with truncated items
retrievable in full (recall ``memory_id``, wiki_read ``offset``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from mcp_server.core.response_budget import serialized_length
from mcp_server.handlers import query_methodology, recall, unified_search, wiki_read


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Settings:
    """Proxy real settings with per-test overrides (no env mutation)."""

    def __init__(self, base: Any, **overrides: Any) -> None:
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_overrides", overrides)

    def __getattr__(self, name: str) -> Any:
        overrides = object.__getattribute__(self, "_overrides")
        if name in overrides:
            return overrides[name]
        return getattr(object.__getattribute__(self, "_base"), name)


class _FakeStore:
    """Minimal store for the recall path: no rules, no triggers."""

    def __init__(self, memories: dict[int, dict] | None = None) -> None:
        self._memories = memories or {}

    def get_memory(self, memory_id: int) -> dict | None:
        return self._memories.get(memory_id)

    def get_all_active_rules(self) -> list:
        return []

    def get_active_prospective_memories(self) -> list:
        return []

    def update_memory_access(self, memory_id: int) -> None:
        pass

    def increment_replay_count(self, memory_id: int) -> None:
        pass


@pytest.fixture
def small_budget(monkeypatch):
    """Patch every handler's settings lookup to a 5,000-char budget."""
    from mcp_server.infrastructure.memory_config import get_memory_settings

    base = get_memory_settings()
    settings = _Settings(base, MAX_RESPONSE_CHARS=5_000, CO_ACTIVATION_ENABLED=False)
    # query_methodology joined the per-consumer loop when its lazy
    # memory_config import moved to module top (#197 family 4).
    for mod in (recall, unified_search, wiki_read, query_methodology):
        monkeypatch.setattr(mod, "get_memory_settings", lambda: settings)
    return settings


# ── recall ────────────────────────────────────────────────────────────


def _wire_recall(monkeypatch, store: _FakeStore, results: list[dict]) -> None:
    monkeypatch.setattr(recall, "_store", store)
    monkeypatch.setattr(recall, "get_embedding_engine", lambda: None)
    monkeypatch.setattr(
        recall, "pg_recall", lambda **kwargs: [dict(r) for r in results]
    )


def test_recall_response_fits_budget(monkeypatch, small_budget) -> None:
    fat = [
        {"memory_id": i, "content": "x" * 20_000, "score": 0.9, "tags": []}
        for i in range(5)
    ]
    _wire_recall(monkeypatch, _FakeStore(), fat)
    resp = _run(recall._handler_impl({"query": "anything"}))
    assert serialized_length(resp) <= 5_000
    assert resp["count"] == len(resp["memories"])
    truncated = [m for m in resp["memories"] if m.get("truncated")]
    assert truncated, "oversized contents must be marked truncated"
    for m in truncated:
        assert m["memory_id"] is not None  # retrievable by id
        assert m["content_length"] == 20_000


def test_recall_fetch_by_id_returns_full_content(monkeypatch, small_budget) -> None:
    store = _FakeStore({42: {"id": 42, "content": "full body", "heat": 0.5}})
    _wire_recall(monkeypatch, store, [])
    resp = _run(recall._handler_impl({"query": "ignored", "memory_id": 42}))
    assert resp["count"] == 1
    mem = resp["memories"][0]
    assert mem["content"] == "full body"
    assert mem["content_length"] == len("full body")
    assert "truncated" not in mem


def test_recall_fetch_by_id_pages_with_offset(monkeypatch, small_budget) -> None:
    body = "".join(str(i % 10) for i in range(20_000))
    store = _FakeStore({7: {"id": 7, "content": body}})
    _wire_recall(monkeypatch, store, [])

    first = _run(recall._handler_impl({"query": "q", "memory_id": 7}))
    assert serialized_length(first) <= 5_000
    m1 = first["memories"][0]
    assert m1["truncated"] is True
    assert m1["content_length"] == 20_000
    assert body.startswith(m1["content"])

    # Page 2: continue where the first slice ended.
    offset = len(m1["content"])
    second = _run(
        recall._handler_impl({"query": "q", "memory_id": 7, "content_offset": offset})
    )
    m2 = second["memories"][0]
    assert m2["content_offset"] == offset
    assert m2["content"] == body[offset : offset + len(m2["content"])]
    assert m2["content_length"] == 20_000


def test_recall_fetch_by_id_missing_memory(monkeypatch, small_budget) -> None:
    _wire_recall(monkeypatch, _FakeStore(), [])
    resp = _run(recall._handler_impl({"query": "q", "memory_id": 999}))
    assert resp["memories"] == []
    assert resp["count"] == 0


# ── unified_search ────────────────────────────────────────────────────


def test_unified_search_response_fits_budget(monkeypatch, small_budget) -> None:
    async def fake_recall(args):
        return {
            "memories": [
                {"memory_id": i, "content": "y" * 20_000, "score": 0.8}
                for i in range(4)
            ]
        }

    monkeypatch.setattr(unified_search, "recall_handler", fake_recall)
    monkeypatch.setattr(unified_search, "is_enabled", lambda: False)
    resp = _run(unified_search.handler({"query": "anything"}))
    assert serialized_length(resp) <= 5_000
    assert resp["counts"]["fused"] == len(resp["results"])
    assert any(r.get("truncated") for r in resp["results"])
    for r in resp["results"]:
        assert r["id"].startswith("memory:")  # fusion id survives


# ── wiki_read ─────────────────────────────────────────────────────────


def test_wiki_read_pages_large_page_via_offset(
    monkeypatch, tmp_path: Path, small_budget
) -> None:
    monkeypatch.setattr(wiki_read, "WIKI_ROOT", str(tmp_path))
    body = "".join(str(i % 10) for i in range(20_000))
    page = tmp_path / "notes" / "big.md"
    page.parent.mkdir(parents=True)
    page.write_text(body, encoding="utf-8")

    first = _run(wiki_read.handler({"path": "notes/big.md"}))
    assert serialized_length(first) <= 5_000
    assert first["content_truncated"] is True
    assert first["content_length"] == 20_000
    assert first["offset"] == 0
    assert body.startswith(first["content"])

    offset = len(first["content"])
    second = _run(wiki_read.handler({"path": "notes/big.md", "offset": offset}))
    assert second["content"] == body[offset : offset + len(second["content"])]
    assert second["content_length"] == 20_000
    assert second["offset"] == offset


def test_wiki_read_small_page_untruncated(
    monkeypatch, tmp_path: Path, small_budget
) -> None:
    monkeypatch.setattr(wiki_read, "WIKI_ROOT", str(tmp_path))
    page = tmp_path / "small.md"
    page.write_text("tiny", encoding="utf-8")
    resp = _run(wiki_read.handler({"path": "small.md"}))
    assert resp["content"] == "tiny"
    assert resp["content_length"] == 4
    assert "content_truncated" not in resp


# ── query_methodology ─────────────────────────────────────────────────


def test_query_methodology_response_fits_budget(monkeypatch, small_budget) -> None:
    monkeypatch.setattr(query_methodology, "load_profiles", lambda: {})
    monkeypatch.setattr(
        query_methodology,
        "detect_domain",
        lambda args, profiles: {"coldStart": True, "context": "cold"},
    )
    fat_mems = [
        {"id": i, "content": "z" * 20_000, "heat": 0.9, "domain": "d", "tags": []}
        for i in range(3)
    ]
    monkeypatch.setattr(
        query_methodology, "_get_hot_memories", lambda *a, **k: fat_mems
    )
    monkeypatch.setattr(
        query_methodology,
        "_get_fired_triggers",
        lambda *a, **k: [{"id": 1, "content": "t" * 20_000}],
    )
    resp = _run(query_methodology.handler({"cwd": "/tmp/x"}))
    assert serialized_length(resp) <= 5_000
    truncated = [m for m in resp["hotMemories"] if m.get("truncated")]
    assert truncated
    for m in truncated:
        assert m["id"] is not None  # retrievable via recall(memory_id)
