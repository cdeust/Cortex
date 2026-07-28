"""Tests for memify fact derivation (INC6.1b): wiring
`identify_derivable_facts` into the memify cycle via the real write gate.

Covers: derivation + explicit provenance, idempotence (SQL marker check),
the per-run bound, and gate-rejection as a valid, non-overridden outcome.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from mcp_server.handlers.consolidation import memify_derive
from mcp_server.handlers.consolidation.memify_derive import (
    run_memify_derivation_cycle,
)


# ─── Fakes ─────────────────────────────────────────────────────────────────


class _FakeCursor:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def fetchall(self) -> list[dict]:
        return self._rows


class _FakeConn:
    def __init__(self, relationships: list[dict]):
        self._relationships = relationships

    def execute(self, sql: str, params: Any = None):
        return _FakeCursor(list(self._relationships))

    def commit(self) -> None:
        pass


class _FakeStore:
    """Minimal MemoryStore stand-in for the derivation cycle.

    `derived_memories` seeds `get_memories_by_tag("derived", ...)` so tests
    can assert the idempotence path without a real DB. Pass
    `no_tag_query=True` to simulate the SQLite fallback (no
    `get_memories_by_tag` attribute at all).
    """

    def __init__(
        self,
        relationships: list[dict] | None = None,
        entities: list[dict] | None = None,
        memories_by_entity: dict[int, list[dict]] | None = None,
        derived_memories: list[dict] | None = None,
        no_tag_query: bool = False,
    ) -> None:
        self._relationships = relationships or []
        self._entities = entities or []
        self._memories_by_entity = memories_by_entity or {}
        self._derived_memories = derived_memories or []
        if no_tag_query:
            # Simulate a backend without get_memories_by_tag by not
            # defining the method at all (hasattr must return False).
            self.get_memories_by_tag = None
            del self.get_memories_by_tag

    @contextmanager
    def acquire_batch(self):
        yield _FakeConn(self._relationships)

    def get_all_entities(self, min_heat: float = 0.0) -> list[dict]:
        return self._entities

    def get_memories_for_entity(self, entity_id: int) -> list[dict]:
        return self._memories_by_entity.get(entity_id, [])

    def get_memories_by_tag(self, tag: str, limit: int = 20) -> list[dict]:
        return self._derived_memories


def _rel(src=1, tgt=2, rel_type="co_occurrence", weight=15.0, rid=1) -> dict:
    return {
        "id": rid,
        "source_entity_id": src,
        "target_entity_id": tgt,
        "relationship_type": rel_type,
        "weight": weight,
    }


def _entities() -> list[dict]:
    return [{"id": 1, "name": "foo.py"}, {"id": 2, "name": "bar.py"}]


def _make_remember(outcome: dict, calls: list[dict]):
    async def _fake_remember(args: dict) -> dict:
        calls.append(args)
        return outcome

    return _fake_remember


# ─── Tests ───────────────────────────────────────────────────────────────


class TestDerivationCreatesProvenance:
    @pytest.mark.asyncio
    async def test_stored_fact_carries_relationship_and_source_tags(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(
            "mcp_server.handlers.consolidation.memify_derive.remember_handler",
            _make_remember(
                {"stored": True, "action": "stored", "memory_id": 99}, calls
            ),
        )
        store = _FakeStore(
            relationships=[_rel()],
            entities=_entities(),
            memories_by_entity={
                1: [{"id": 10}, {"id": 11}],
                2: [{"id": 20}],
            },
        )

        stats = await run_memify_derivation_cycle(store)

        assert stats["candidates_scanned"] == 1
        assert stats["derived_created"] == 1
        assert stats["derived_rejected"] == 0
        assert stats["already_derived"] == 0
        assert len(calls) == 1
        tags = calls[0]["tags"]
        assert "derived" in tags
        assert "derived-rel:1-2-co_occurrence" in tags
        # Explicit provenance: real source memory ids, not just the
        # relationship pointer.
        assert "derived-src:10" in tags
        assert "derived-src:20" in tags
        assert calls[0]["source"] == "consolidation"
        assert calls[0]["force"] is False

    @pytest.mark.asyncio
    async def test_low_weight_relationship_produces_no_candidate(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(
            "mcp_server.handlers.consolidation.memify_derive.remember_handler",
            _make_remember({"stored": True, "action": "stored"}, calls),
        )
        store = _FakeStore(
            relationships=[_rel(weight=2.0)],  # below identify_derivable_facts' gate
            entities=_entities(),
        )

        stats = await run_memify_derivation_cycle(store)

        # The relationship was scanned but never met the fact threshold —
        # note it fails the _WEIGHT_THRESHOLD candidacy filter used for the
        # SQL fetch too, so it wouldn't even be scanned in production; here
        # we bypass the SQL filter via the fake to exercise the
        # identify_derivable_facts guard specifically.
        assert stats["derived_created"] == 0
        assert calls == []


class TestIdempotence:
    @pytest.mark.asyncio
    async def test_existing_marker_skips_without_calling_gate(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(
            "mcp_server.handlers.consolidation.memify_derive.remember_handler",
            _make_remember({"stored": True, "action": "stored"}, calls),
        )
        store = _FakeStore(
            relationships=[_rel()],
            entities=_entities(),
            derived_memories=[
                {"id": 5, "tags": ["derived", "derived-rel:1-2-co_occurrence"]}
            ],
        )

        stats = await run_memify_derivation_cycle(store)

        assert stats["already_derived"] == 1
        assert stats["derived_created"] == 0
        assert calls == []  # gate never called for an already-derived pair

    @pytest.mark.asyncio
    async def test_rerun_after_success_is_a_noop(self, monkeypatch):
        """Simulates re-running memify: the first run's stored memory now
        appears in get_memories_by_tag, so the second run must not re-derive."""
        calls: list[dict] = []
        monkeypatch.setattr(
            "mcp_server.handlers.consolidation.memify_derive.remember_handler",
            _make_remember({"stored": True, "action": "stored"}, calls),
        )
        rel = _rel()
        store = _FakeStore(relationships=[rel], entities=_entities())
        first = await run_memify_derivation_cycle(store)
        assert first["derived_created"] == 1
        assert len(calls) == 1

        # Second run: the store now reports the memory just created.
        store._derived_memories = [
            {
                "id": 99,
                "tags": calls[0]["tags"],
            }
        ]
        second = await run_memify_derivation_cycle(store)

        assert second["already_derived"] == 1
        assert second["derived_created"] == 0
        assert len(calls) == 1  # no additional gate call

    @pytest.mark.asyncio
    async def test_no_tag_query_backend_degrades_to_no_dedup(self, monkeypatch):
        """SQLite fallback (no get_memories_by_tag) must not error — it
        just can't dedupe against history within this call."""
        calls: list[dict] = []
        monkeypatch.setattr(
            "mcp_server.handlers.consolidation.memify_derive.remember_handler",
            _make_remember({"stored": True, "action": "stored"}, calls),
        )
        store = _FakeStore(
            relationships=[_rel()], entities=_entities(), no_tag_query=True
        )

        stats = await run_memify_derivation_cycle(store)

        assert stats["already_derived"] == 0
        assert stats["derived_created"] == 1


class TestBound:
    @pytest.mark.asyncio
    async def test_attempts_capped_at_max_derivations_per_run(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(
            "mcp_server.handlers.consolidation.memify_derive.remember_handler",
            _make_remember({"stored": True, "action": "stored"}, calls),
        )
        monkeypatch.setattr(memify_derive, "_MAX_DERIVATIONS_PER_RUN", 2)
        relationships = [
            _rel(src=1, tgt=2, rel_type=f"type_{i}", weight=15.0, rid=i)
            for i in range(5)
        ]
        store = _FakeStore(relationships=relationships, entities=_entities())

        stats = await run_memify_derivation_cycle(store)

        assert stats["candidates_scanned"] == 5
        assert stats["derived_created"] == 2
        assert len(calls) == 2


class TestGateRejectionIsValid:
    @pytest.mark.asyncio
    async def test_gate_rejection_counted_never_forced(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(
            "mcp_server.handlers.consolidation.memify_derive.remember_handler",
            _make_remember(
                {"stored": False, "action": "rejected", "reason": "low_novelty"},
                calls,
            ),
        )
        store = _FakeStore(relationships=[_rel()], entities=_entities())

        stats = await run_memify_derivation_cycle(store)

        assert stats["derived_rejected"] == 1
        assert stats["derived_created"] == 0
        assert calls[0]["force"] is False  # never bypassed to force a write

    @pytest.mark.asyncio
    async def test_remember_exception_counted_as_error_not_raised(self, monkeypatch):
        async def _raising(args: dict) -> dict:
            raise RuntimeError("boom")

        monkeypatch.setattr(memify_derive, "remember_handler", _raising)
        store = _FakeStore(relationships=[_rel()], entities=_entities())

        stats = await run_memify_derivation_cycle(store)

        assert stats["derived_error"] == 1
        assert stats["derived_created"] == 0


class TestEmptyAndFailureModes:
    @pytest.mark.asyncio
    async def test_no_relationships_returns_zero_stats(self):
        store = _FakeStore(relationships=[], entities=[])

        stats = await run_memify_derivation_cycle(store)

        assert stats == {
            "candidates_scanned": 0,
            "already_derived": 0,
            "derived_created": 0,
            "derived_rejected": 0,
            "derived_error": 0,
        }

    @pytest.mark.asyncio
    async def test_relationship_fetch_failure_degrades_to_zero_stats(self):
        class _BrokenStore(_FakeStore):
            @contextmanager
            def acquire_batch(self):
                raise RuntimeError("db down")
                yield  # pragma: no cover

        store = _BrokenStore(relationships=[_rel()], entities=_entities())

        stats = await run_memify_derivation_cycle(store)

        assert stats["candidates_scanned"] == 0
        assert stats["derived_created"] == 0
