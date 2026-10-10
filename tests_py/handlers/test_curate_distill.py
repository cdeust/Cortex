"""Tests for handlers.curate_distill (INC7.8/M-D8).

Read-only composition root: assembles dossiers from a fake store (no PG —
this handler introduces zero new SQL; every store method it calls
(get_memories_by_tag, get_temporal_co_access, get_memory,
get_recently_accessed_memories) is pre-existing and already PG-tested at
the pg_store layer). Covers: dossier surfacing per kind, idempotence
(marker-based skip), graceful degradation when the store lacks
tag/co-access support, and that the handler never calls a mutating store
method.
"""

from __future__ import annotations

import asyncio

from mcp_server.core.distillation import dossier_marker_tag
from mcp_server.handlers import curate_distill


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mem(
    id_,
    content,
    tags=None,
    created_at="2026-07-01T00:00:00+00:00",
    domain="cortex",
    **extra,
):
    m = {
        "id": id_,
        "content": content,
        "tags": tags or [],
        "created_at": created_at,
        "domain": domain,
    }
    m.update(extra)
    return m


class _FakeStore:
    """Minimal MemoryStore stand-in.

    Deliberately does NOT use the `del type(self).method` pattern some
    other fakes in this test suite use for "missing method" simulation —
    that mutates the shared CLASS object, which leaks across every test
    in the process once one test sets `no_tag_query=True` (order-
    dependent pollution). `_FakeStoreNoTagQuery` /
    `_FakeStoreNoCoAccess` below use real subclassing instead, so each
    test's "missing method" is scoped to that test's instance only.
    """

    def __init__(
        self,
        by_tag: dict[str, list[dict]] | None = None,
        co_access_pairs: list[tuple[int, int, float]] | None = None,
        recent: list[dict] | None = None,
        raise_on_tag: bool = False,
    ) -> None:
        self._by_tag = by_tag or {}
        self._co_access_pairs = co_access_pairs or []
        self._recent = recent or []
        self._raise_on_tag = raise_on_tag
        self._all_by_id = {m["id"]: m for mems in self._by_tag.values() for m in mems}
        self._all_by_id.update({m["id"]: m for m in self._recent})

    def get_memories_by_tag(
        self, tag: str, limit: int = 20, heads_only: bool = True
    ) -> list[dict]:
        if self._raise_on_tag:
            raise RuntimeError("PG unreachable")
        return list(self._by_tag.get(tag, []))

    def get_temporal_co_access(self, window_hours, min_access, limit):
        return list(self._co_access_pairs)

    def get_memory(self, memory_id: int):
        return self._all_by_id.get(memory_id)

    def get_recently_accessed_memories(self, limit=500, heads_only=True):
        return list(self._recent)

    def get_recent_memories(self, limit=500):
        return list(self._recent)


class _FakeStoreNoTagQuery(_FakeStore):
    """Simulates a backend without `get_memories_by_tag` (SQLite
    fallback) via a property that raises `AttributeError` — the
    standard idiom for `hasattr(...) is False` on a specific instance
    type, scoped to this subclass only (never mutates `_FakeStore`)."""

    @property
    def get_memories_by_tag(self):  # type: ignore[override]
        raise AttributeError("get_memories_by_tag")


class _FakeStoreNoCoAccess(_FakeStore):
    """Simulates a backend without `get_temporal_co_access`."""

    @property
    def get_temporal_co_access(self):  # type: ignore[override]
        raise AttributeError("get_temporal_co_access")


class TestCurateDistillHandler:
    def test_error_success_dossier_surfaced(self, monkeypatch):
        errors = [_mem(1, "write_gate.py raised ValueError", tags=["error"])]
        successes = [
            _mem(
                2,
                "write_gate.py fixed ValueError",
                tags=["success"],
                created_at="2026-07-01T02:00:00+00:00",
            )
        ]
        store = _FakeStore(by_tag={"error": errors, "success": successes})
        monkeypatch.setattr(curate_distill, "get_shared_store", lambda: store)

        result = _run(
            curate_distill.handler(
                {"include_co_access": False, "include_entity_family": False}
            )
        )

        assert result["counts_by_kind"]["error_success"] == 1
        assert len(result["jobs"]) == 1
        job = result["jobs"][0]
        assert job["job_type"] == "distill"
        assert job["dossier_kind"] == "error_success"
        assert job["memory_ids"] == [1, 2]
        assert "write_class='deliberate'" in job["prompt"]

    def test_idempotence_skips_already_distilled_dossier(self, monkeypatch):
        errors = [_mem(1, "write_gate.py raised ValueError", tags=["error"])]
        successes = [
            _mem(
                2,
                "write_gate.py fixed ValueError",
                tags=["success"],
                created_at="2026-07-01T02:00:00+00:00",
            )
        ]
        marker = dossier_marker_tag([1, 2])
        existing_lesson = _mem(99, "already distilled", tags=["lesson", marker])
        store = _FakeStore(
            by_tag={
                "error": errors,
                "success": successes,
                "lesson": [existing_lesson],
            }
        )
        monkeypatch.setattr(curate_distill, "get_shared_store", lambda: store)

        result = _run(
            curate_distill.handler(
                {"include_co_access": False, "include_entity_family": False}
            )
        )

        assert result["jobs"] == []
        assert result["already_distilled_skipped"] == 1

    def test_co_access_dossier_surfaced(self, monkeypatch):
        pairs = [(1, 2, 0.9), (2, 3, 0.8)]
        recent = [
            _mem(i, f"content {i}", created_at=f"2026-07-01T0{i}:00:00+00:00")
            for i in (1, 2, 3)
        ]
        store = _FakeStore(co_access_pairs=pairs, recent=recent)
        monkeypatch.setattr(curate_distill, "get_shared_store", lambda: store)

        result = _run(
            curate_distill.handler(
                {"include_error_success": False, "include_entity_family": False}
            )
        )

        assert result["counts_by_kind"]["co_access_family"] == 1
        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["dossier_kind"] == "co_access_family"

    def test_entity_family_dossier_surfaced(self, monkeypatch):
        recent = [
            _mem(i, "write_gate.py write_gate write_gate handles the gate decision")
            for i in range(1, 6)
        ]
        store = _FakeStore(recent=recent)
        monkeypatch.setattr(curate_distill, "get_shared_store", lambda: store)

        result = _run(
            curate_distill.handler(
                {
                    "include_error_success": False,
                    "include_co_access": False,
                    "min_memories": 4,
                    "min_avg_heat": 0.0,
                }
            )
        )

        assert result["counts_by_kind"]["entity_family"] >= 1
        assert any(j["dossier_kind"] == "entity_family" for j in result["jobs"])

    def test_degrades_gracefully_without_tag_query_support(self, monkeypatch):
        store = _FakeStoreNoTagQuery()
        assert not hasattr(store, "get_memories_by_tag")
        monkeypatch.setattr(curate_distill, "get_shared_store", lambda: store)

        result = _run(curate_distill.handler({"include_entity_family": False}))

        assert result["jobs"] == []
        assert result["memify_derive_usage"]["count"] == 0

    def test_degrades_gracefully_without_co_access_support(self, monkeypatch):
        store = _FakeStoreNoCoAccess()
        assert not hasattr(store, "get_temporal_co_access")
        monkeypatch.setattr(curate_distill, "get_shared_store", lambda: store)

        result = _run(
            curate_distill.handler(
                {"include_error_success": False, "include_entity_family": False}
            )
        )

        assert result["jobs"] == []
        assert result["counts_by_kind"].get("co_access_family", 0) == 0

    def test_degrades_gracefully_on_tag_query_exception(self, monkeypatch):
        store = _FakeStore(raise_on_tag=True)
        monkeypatch.setattr(curate_distill, "get_shared_store", lambda: store)

        result = _run(
            curate_distill.handler(
                {"include_co_access": False, "include_entity_family": False}
            )
        )

        assert result["jobs"] == []

    def test_never_calls_a_mutating_method(self, monkeypatch):
        """Read-only contract: the handler must not touch remember/insert/
        update/delete on the store — it delegates all writes to the
        in-session LLM's own subsequent `remember` call."""

        class _AssertingStore(_FakeStore):
            def __getattr__(self, name):
                if name.startswith(("insert_", "update_", "delete_", "remember")):
                    raise AssertionError(f"curate_distill must not call {name}")
                raise AttributeError(name)

        store = _AssertingStore()
        monkeypatch.setattr(curate_distill, "get_shared_store", lambda: store)

        result = _run(curate_distill.handler({}))
        assert result["jobs"] == []

    def test_memify_derive_usage_reported(self, monkeypatch):
        derived = [
            {"id": 1, "access_count": 3, "useful_count": 1},
            {"id": 2, "access_count": 2, "useful_count": 2},
        ]
        store = _FakeStore(by_tag={"derived": derived})
        monkeypatch.setattr(curate_distill, "get_shared_store", lambda: store)

        result = _run(
            curate_distill.handler(
                {
                    "include_error_success": False,
                    "include_co_access": False,
                    "include_entity_family": False,
                }
            )
        )

        assert result["memify_derive_usage"]["count"] == 2
        assert result["memify_derive_usage"]["total_access_count"] == 5
        assert result["memify_derive_usage"]["total_useful_count"] == 3

    def test_instructions_mention_marker_and_derived_src(self, monkeypatch):
        errors = [_mem(1, "write_gate.py raised ValueError", tags=["error"])]
        successes = [
            _mem(
                2,
                "write_gate.py fixed ValueError",
                tags=["success"],
                created_at="2026-07-01T02:00:00+00:00",
            )
        ]
        store = _FakeStore(by_tag={"error": errors, "success": successes})
        monkeypatch.setattr(curate_distill, "get_shared_store", lambda: store)

        result = _run(
            curate_distill.handler(
                {"include_co_access": False, "include_entity_family": False}
            )
        )
        assert "marker" in result["instructions"]
        assert "derived-src" in result["instructions"]

    def test_zero_eligible_dossiers_instructions(self, monkeypatch):
        store = _FakeStore()
        monkeypatch.setattr(curate_distill, "get_shared_store", lambda: store)

        result = _run(curate_distill.handler({}))
        assert result["jobs"] == []
        assert "No distillation jobs" in result["instructions"]
