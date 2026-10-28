"""Tests for inject_triggered_memories — bounded-io Phase 2 F1.

The 2026-06-10 audit (docs/provenance/bounded-io-phase2-design.md M1) found this
injection was the primary live scoring inversion: 317 garbage triggers each
prepending up to 3 FTS matches at a fabricated 0.9, unbounded, re-introducing
the auto-capture blobs filter_low_signal had just dropped. These tests pin
the contract: low-signal discipline applies, the total is capped, and
injected items are observable.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from mcp_server.handlers.recall_helpers import inject_triggered_memories


def _store(triggers, memories):
    """Mock store: every trigger FTS-matches every memory id in order."""
    store = MagicMock()
    store.get_active_prospective_memories.return_value = triggers
    store.search_fts.return_value = [(mid, 1.0) for mid in memories]
    store.get_memory.side_effect = lambda mid: memories.get(mid)
    return store


def _trigger(condition="deploy"):
    return {"trigger_type": "keyword_match", "trigger_condition": condition}


def _mem(content="standing instruction", source="", tags=None):
    return {"content": content, "source": source, "tags": tags or []}


class TestInjectionFiltering:
    def test_auto_capture_memories_not_injected(self):
        store = _store([_trigger()], {1: _mem(source="post_tool_capture")})
        out = inject_triggered_memories([], "ship the deploy", store)
        assert out == []

    def test_user_capture_tag_without_provenance_is_injected(self):
        store = _store([_trigger()], {1: _mem(tags=["auto-captured"])})
        out = inject_triggered_memories([], "ship the deploy", store)
        assert [m["memory_id"] for m in out] == [1]

    def test_clean_memory_injected_with_flag(self):
        store = _store([_trigger()], {1: _mem()})
        out = inject_triggered_memories([], "ship the deploy", store)
        assert len(out) == 1
        assert out[0]["injected"] is True
        assert out[0]["source"] == ""


class TestInjectionCap:
    def test_total_injection_capped_at_max_inject(self):
        memories = {i: _mem(f"instruction {i}") for i in range(1, 10)}
        store = _store([_trigger()] * 5, memories)
        out = inject_triggered_memories([], "ship the deploy", store, max_inject=2)
        assert len(out) == 2

    def test_no_cap_when_max_inject_none(self):
        memories = {i: _mem(f"instruction {i}") for i in range(1, 4)}
        store = _store([_trigger()], memories)
        out = inject_triggered_memories([], "ship the deploy", store)
        assert len(out) == 3

    def test_injected_prepend_existing_results(self):
        store = _store([_trigger()], {1: _mem()})
        ranked = [{"memory_id": 99, "content": "wrrf result", "score": 0.5}]
        out = inject_triggered_memories(ranked, "ship the deploy", store)
        assert [r["memory_id"] for r in out] == [1, 99]

    def test_non_matching_trigger_injects_nothing(self):
        store = _store([_trigger("kubernetes")], {1: _mem()})
        out = inject_triggered_memories([], "ship the deploy", store)
        assert out == []
