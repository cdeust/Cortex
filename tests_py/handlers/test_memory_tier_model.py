"""Tests for the letta-style two-tier memory model fixes (C1-C4).

C1 — hot-memory injection must not surface auto-captures or block replicas.
C2 — positive tag filtering (tags_any / tags_all) in recall.
C3 — block-replica upsert by vpath identity (one row per block file).
C4 — CLS promotion excludes auto-captured and memory-replica memories.

Uses in-process fakes (no PostgreSQL required).
contract: zetetic-team-subagents memory/contract.md §8b
"""

from __future__ import annotations

import json
from typing import Any


# ── C1: checkpoint _is_tier_noise / _partition_hot_memories ──────────────


def test_checkpoint_tier_noise_excludes_auto_captured():
    """A heat-1.0 auto-captured memory must not pass _partition_hot_memories."""
    from mcp_server.handlers.checkpoint import _is_tier_noise, _partition_hot_memories

    auto_cap = {
        "id": 1,
        "heat": 1.0,
        "is_protected": False,
        "tags": ["auto-captured", "tool:edit"],
    }
    curated = {"id": 2, "heat": 0.9, "is_protected": False, "tags": ["lesson"]}
    anchored_curated = {
        "id": 3,
        "heat": 0.95,
        "is_protected": True,
        "tags": ["_anchor", "decision"],
    }

    assert _is_tier_noise(auto_cap) is True
    assert _is_tier_noise(curated) is False
    assert _is_tier_noise(anchored_curated) is False

    anchored, anchor_ids, recent, recent_ids = _partition_hot_memories(
        [auto_cap, curated, anchored_curated], max_memories=10
    )

    all_returned_ids = anchor_ids | recent_ids
    assert 1 not in all_returned_ids, "auto-captured memory must be excluded"
    assert 2 in recent_ids, "curated lesson must be in recent partition"
    assert 3 in anchor_ids, "curated anchor must be in anchored partition"


def test_checkpoint_tier_noise_excludes_memory_replica():
    """A memory-replica block snapshot must not pass _partition_hot_memories."""
    from mcp_server.handlers.checkpoint import _is_tier_noise, _partition_hot_memories

    replica = {
        "id": 10,
        "heat": 0.95,
        "is_protected": False,
        "tags": [
            "memory-replica",
            "scope:engineer",
            "vpath:/memories/engineer/notes.md",
        ],
    }
    curated = {"id": 11, "heat": 0.8, "is_protected": False, "tags": ["convention"]}

    assert _is_tier_noise(replica) is True
    assert _is_tier_noise(curated) is False

    _, anchor_ids, _, recent_ids = _partition_hot_memories(
        [replica, curated], max_memories=10
    )
    all_ids = anchor_ids | recent_ids
    assert 10 not in all_ids, "memory-replica must be excluded"
    assert 11 in recent_ids


def test_checkpoint_tier_noise_handles_json_string_tags():
    """Tags stored as a JSON string are parsed correctly."""
    from mcp_server.handlers.checkpoint import _is_tier_noise

    mem = {"id": 1, "tags": json.dumps(["auto-captured", "tool:bash"])}
    assert _is_tier_noise(mem) is True


def test_checkpoint_tier_noise_handles_none_tags():
    """None tags must not raise."""
    from mcp_server.handlers.checkpoint import _is_tier_noise

    assert _is_tier_noise({"id": 1, "tags": None}) is False
    assert _is_tier_noise({"id": 1}) is False


# ── C2: recall filter_by_tags ─────────────────────────────────────────────


def _make_mem(mem_id: int, *tags: str) -> dict:
    return {"memory_id": mem_id, "content": "x", "score": 0.9, "tags": list(tags)}


def test_filter_by_tags_any_keeps_matching():
    """tags_any=[\"archival\"] keeps only archival-tagged memories."""
    from mcp_server.handlers.recall_helpers import filter_by_tags

    results = [
        _make_mem(1, "archival", "scope:engineer"),
        _make_mem(2, "lesson"),
        _make_mem(3, "archival", "decision"),
    ]
    kept = filter_by_tags(results, tags_any=["archival"], tags_all=[])
    assert [r["memory_id"] for r in kept] == [1, 3]


def test_filter_by_tags_any_empty_returns_all():
    """Empty tags_any and tags_all passes all results through."""
    from mcp_server.handlers.recall_helpers import filter_by_tags

    results = [_make_mem(1, "lesson"), _make_mem(2, "archival")]
    kept = filter_by_tags(results, tags_any=[], tags_all=[])
    assert kept == results


def test_filter_by_tags_all_requires_every_tag():
    """tags_all=[\"archival\", \"scope:engineer\"] requires both tags."""
    from mcp_server.handlers.recall_helpers import filter_by_tags

    results = [
        _make_mem(1, "archival", "scope:engineer"),
        _make_mem(2, "archival"),  # missing scope:engineer
        _make_mem(3, "scope:engineer"),  # missing archival
    ]
    kept = filter_by_tags(results, tags_any=[], tags_all=["archival", "scope:engineer"])
    assert [r["memory_id"] for r in kept] == [1]


def test_filter_by_tags_combined_any_and_all():
    """tags_any and tags_all both applied: memory must satisfy both."""
    from mcp_server.handlers.recall_helpers import filter_by_tags

    results = [
        _make_mem(1, "archival", "agent:engineer"),  # passes both
        _make_mem(2, "archival"),  # passes any, fails all (missing agent:engineer)
        _make_mem(3, "lesson", "agent:engineer"),  # fails any (not archival)
    ]
    kept = filter_by_tags(results, tags_any=["archival"], tags_all=["agent:engineer"])
    assert [r["memory_id"] for r in kept] == [1]


# ── C3: try_block_replica_upsert ──────────────────────────────────────────


class _FakeExecuteResult:
    """Minimal cursor-like result for _execute mock."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict]:
        return self._rows


class _FakeStoreForReplica:
    """Fake store that records UPDATE calls and returns configurable query results."""

    def __init__(self, existing_id: int | None = None) -> None:
        self._existing_id = existing_id
        self.updates: list[tuple] = []

    def _execute(self, query: str, params: Any = None) -> _FakeExecuteResult:
        if "SELECT id FROM memories" in query:
            if self._existing_id is not None:
                return _FakeExecuteResult([{"id": self._existing_id}])
            return _FakeExecuteResult([])
        if "UPDATE memories" in query:
            self.updates.append((query, params))
            return _FakeExecuteResult([])
        return _FakeExecuteResult([])


def test_block_replica_upsert_updates_existing_row():
    """Second write with same vpath: tag updates rather than inserts — row
    count stable."""
    from mcp_server.handlers.remember_helpers import try_block_replica_upsert

    store = _FakeStoreForReplica(existing_id=42)
    tags = ["memory-replica", "scope:engineer", "vpath:/memories/engineer/notes.md"]

    upserted, uid = try_block_replica_upsert(
        content="updated block content",
        embedding=None,
        tags=tags,
        source="post_tool_capture",
        store=store,
    )

    assert upserted is True
    assert uid == 42
    assert len(store.updates) == 1, "exactly one UPDATE executed"


def test_block_replica_upsert_inserts_when_no_existing():
    """No existing row → returns (False, None) so caller proceeds normally."""
    from mcp_server.handlers.remember_helpers import try_block_replica_upsert

    store = _FakeStoreForReplica(existing_id=None)
    tags = ["memory-replica", "vpath:/memories/engineer/new.md"]

    upserted, uid = try_block_replica_upsert(
        content="new block",
        embedding=None,
        tags=tags,
        source="post_tool_capture",
        store=store,
    )

    assert upserted is False
    assert uid is None
    assert len(store.updates) == 0


def test_block_replica_upsert_ignores_non_replica():
    """Non-replica writes (no memory-replica tag) must pass through untouched."""
    from mcp_server.handlers.remember_helpers import try_block_replica_upsert

    store = _FakeStoreForReplica(existing_id=99)
    tags = ["lesson", "decision"]

    upserted, uid = try_block_replica_upsert(
        content="curated lesson",
        embedding=None,
        tags=tags,
        source="user",
        store=store,
    )

    assert upserted is False
    assert uid is None
    assert len(store.updates) == 0, "normal writes must never reach upsert path"


def test_block_replica_upsert_ignores_replica_without_vpath():
    """memory-replica tag alone (no vpath:) must not trigger upsert."""
    from mcp_server.handlers.remember_helpers import try_block_replica_upsert

    store = _FakeStoreForReplica(existing_id=99)
    tags = ["memory-replica", "scope:engineer"]  # missing vpath:

    upserted, uid = try_block_replica_upsert(
        content="replica without vpath",
        embedding=None,
        tags=tags,
        source="post_tool_capture",
        store=store,
    )

    assert upserted is False
    assert uid is None


# ── C4: CLS promotion exclusion ───────────────────────────────────────────


class _FakeEmbeddings:
    def similarity(self, a: Any, b: Any) -> float:
        return 1.0 if a == b else 0.0

    def encode(self, text: str) -> bytes:
        return text.encode("utf-8")


class _FakeStoreForCls:
    def __init__(
        self, episodic: list[dict], semantic: list[dict] | None = None
    ) -> None:
        self._episodic = episodic
        self._semantic = semantic or []
        self.inserted_memories: list[dict] = []
        self.inserted_relationships: list[dict] = []

    def get_episodic_memories(self, limit: int = 2000) -> list[dict]:
        return self._episodic[:limit]

    def get_semantic_memories(self, limit: int = 2000) -> list[dict]:
        return self._semantic[:limit]

    def get_all_entities(self, min_heat: float = 0.0) -> list[dict]:
        return []

    def insert_memory(self, mem: dict) -> int:
        self.inserted_memories.append(mem)
        return len(self.inserted_memories)

    def insert_relationship(self, rel: dict) -> None:
        self.inserted_relationships.append(rel)


def _make_episodic(mid: int, content: str, *, tags: list[str] | None = None) -> dict:
    emb = content.encode("utf-8")
    return {"id": mid, "embedding": emb, "content": content, "tags": tags or []}


def test_cls_excludes_auto_captured_from_promotion():
    """auto-captured memories must not appear in episodic scan passed to plan."""
    import os

    from mcp_server.handlers.consolidation.cls import run_cls_cycle

    # Two memories with identical embeddings form a pattern; the auto-captured
    # one must be excluded so it never contributes to semantic pattern creation.
    curated_a = _make_episodic(1, "same content", tags=[])
    curated_b = _make_episodic(2, "same content", tags=["lesson"])
    auto_cap = _make_episodic(3, "same content", tags=["auto-captured", "tool:edit"])

    store = _FakeStoreForCls(episodic=[curated_a, curated_b, auto_cap])

    # Run with consolidation enabled (env var default = not set)
    os.environ.pop("CORTEX_CONSOLIDATION_DISABLED", None)
    result = run_cls_cycle(store, settings=None, embeddings=_FakeEmbeddings())

    assert "episodic_scanned" in result
    # Only the 2 curated memories should have been scanned (auto-captured excluded).
    assert result["episodic_scanned"] == 2, (
        f"expected 2 curated memories scanned, got {result['episodic_scanned']}"
    )


def test_cls_excludes_memory_replica_from_promotion():
    """memory-replica block snapshots must not be promoted to semantic patterns."""
    import os

    from mcp_server.handlers.consolidation.cls import run_cls_cycle

    replica = _make_episodic(
        10,
        "block content",
        tags=["memory-replica", "vpath:/memories/engineer/notes.md"],
    )
    store = _FakeStoreForCls(episodic=[replica])

    os.environ.pop("CORTEX_CONSOLIDATION_DISABLED", None)
    result = run_cls_cycle(store, settings=None, embeddings=_FakeEmbeddings())

    # After excluding the replica, episodic is empty → reason = empty_episodic_scan
    assert result.get("reason_for_zero") == "empty_episodic_scan"
    assert result["episodic_scanned"] == 0


def test_cls_is_promotion_noise_helper():
    """_is_promotion_noise correctly identifies tier noise."""
    from mcp_server.handlers.consolidation.cls import _is_promotion_noise

    assert _is_promotion_noise({"tags": ["auto-captured"]}) is True
    assert _is_promotion_noise({"tags": ["memory-replica", "scope:x"]}) is True
    assert _is_promotion_noise({"tags": ["lesson", "decision"]}) is False
    assert _is_promotion_noise({"tags": None}) is False
    assert _is_promotion_noise({"tags": json.dumps(["auto-captured"])}) is True
