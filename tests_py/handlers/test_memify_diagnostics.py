"""Tests for memify cycle `reason_for_zero` / `reason_for_inaction` (issue #14 P2).

The `memify` consolidate stage returns a diagnostic field when its
three counters (`pruned`, `strengthened`, `reweighted`) collectively
indicate that nothing was mutated OR that only the reweight step fired:

  * All three counters zero → `reason_for_zero`.
  * `pruned == 0 AND strengthened == 0 AND reweighted > 0`
    → `reason_for_inaction`.
  * Otherwise: diagnostic absent.

Each reason value must be reachable via a realistic fake-store setup.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from mcp_server.handlers.consolidation.memify import run_memify_cycle


# ─── Fake store ──────────────────────────────────────────────────────────


class _FakeStore:
    """Minimal MemoryStore stand-in driven by injected fixtures.

    Phase 5: the reweight path uses ``acquire_batch()`` — a context
    manager yielding a mock connection. Reweight is the only path that
    needs a connection; everything else runs through public methods we
    stub directly.
    """

    def __init__(
        self,
        memories: list[dict] | None = None,
        entities: list[dict] | None = None,
        relationships: list[dict] | None = None,
    ) -> None:
        self._memories = memories or []
        self._entities = entities or []
        self._relationships = relationships or []
        self.deleted_ids: list[int] = []
        self.updated_importance: list[tuple[int, float]] = []
        self._conn = _FakeConn(self._relationships)

    def get_all_memories_for_decay(self) -> list[dict]:
        return self._memories

    def get_all_entities(self, min_heat: float = 0.0) -> list[dict]:
        return self._entities

    def delete_memory(self, mid: int) -> None:
        self.deleted_ids.append(mid)

    def update_memory_importance(self, mid: int, new_importance: float) -> None:
        self.updated_importance.append((mid, new_importance))

    @contextmanager
    def acquire_batch(self):
        """Phase 5 context manager: yields the fake connection."""
        yield self._conn

    @contextmanager
    def acquire_interactive(self):
        yield self._conn


class _FakeConn:
    """Fake psycopg connection supporting the minimal API used by
    `_reweight_relationships`: `execute(sql, params)` returning either
    a rows-yielding cursor or None, plus `commit()`.
    """

    def __init__(self, relationships: list[dict]):
        self._relationships = relationships
        self.updates: list[tuple[int, float]] = []

    def execute(self, sql: str, params: Any = None):
        sql_lower = sql.lower().strip()
        if sql_lower.startswith("select"):
            return _FakeCursor(self._relationships)
        if sql_lower.startswith("update"):
            new_weight, rid = params
            self.updates.append((rid, new_weight))
            return None
        return None

    def commit(self) -> None:
        pass


class _FakeCursor:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def fetchall(self) -> list[dict]:
        return self._rows


# ─── Tests ───────────────────────────────────────────────────────────────


class TestMemifyReasonForZero:
    """All three counters zero → `reason_for_zero` is emitted."""

    def test_empty_store_triggers_passed_through(self):
        """No memories and no relationships → reason = passed_through.

        Spec priority: when `memories` is empty there is nothing to
        inspect, so the classifier falls through to `passed_through`.
        """
        store = _FakeStore(memories=[], entities=[], relationships=[])

        result = run_memify_cycle(store)

        assert result["pruned"] == 0
        assert result["strengthened"] == 0
        assert result["reweighted"] == 0
        assert result["reason_for_zero"] == "passed_through"
        # Existing keys still present unchanged.
        assert set(result) == {
            "pruned",
            "strengthened",
            "reweighted",
            "reason_for_zero",
        }

    def test_below_access_threshold_triggers_reason(self):
        """Candidates exist but all below strengthen access threshold.

        Memories have some access (>0) but none reach min_access=5.
        No prune candidates (heat and confidence are high). No
        relationships → reweighted==0. Reason must identify the
        strengthen gate as the bottleneck.
        """
        memories = [
            {
                "id": i,
                "heat": 0.8,
                "confidence": 0.9,
                "access_count": 2,  # < 5 (min_access)
                "importance": 0.5,
            }
            for i in range(5)
        ]
        store = _FakeStore(memories=memories, entities=[], relationships=[])

        result = run_memify_cycle(store, memories=memories)

        assert result["pruned"] == 0
        assert result["strengthened"] == 0
        assert result["reweighted"] == 0
        assert result["reason_for_zero"] == "below_access_threshold"

    def test_below_stale_threshold_triggers_reason(self):
        """Warm-but-not-prunable memories exist; no strengthen access
        signal. Prune gate is the bottleneck.

        Memories have low-ish heat (<0.5) but not below the prune
        heat threshold (0.01). None have access > 0. No relationships.
        """
        memories = [
            {
                "id": i,
                "heat": 0.2,  # below 0.5 but above 0.01
                "confidence": 0.5,
                "access_count": 0,
                "importance": 0.5,
            }
            for i in range(5)
        ]
        store = _FakeStore(memories=memories, entities=[], relationships=[])

        result = run_memify_cycle(store, memories=memories)

        assert result["pruned"] == 0
        assert result["strengthened"] == 0
        assert result["reweighted"] == 0
        assert result["reason_for_zero"] == "below_stale_threshold"


class TestMemifyReasonForInaction:
    """`pruned == 0 AND strengthened == 0 AND reweighted > 0` → `reason_for_inaction`."""

    def test_reweight_only_gate_emits_inaction(self):
        """Reweight fires (entity heats cross thresholds) but no prune/
        strengthen candidates → reason_for_inaction = reweight_only_gate.

        Spec: intentional gating — the reweight pass did its job, but
        the store has no strengthen/prune candidates.
        """
        memories = [
            {
                "id": 1,
                "heat": 0.7,  # above prune threshold (0.01)
                "confidence": 0.95,  # above prune threshold (0.3)
                "access_count": 1,  # below strengthen min (5)
                "importance": 0.5,
            }
        ]
        # Two hot entities (heat > 0.7 boosts weight); one relationship
        # between them so the reweight pass emits an UPDATE.
        entities = [
            {"id": 10, "heat": 0.9},
            {"id": 11, "heat": 0.9},
        ]
        relationships = [
            {
                "id": 100,
                "source_entity_id": 10,
                "target_entity_id": 11,
                "weight": 1.0,
            }
        ]
        store = _FakeStore(
            memories=memories, entities=entities, relationships=relationships
        )

        result = run_memify_cycle(store, memories=memories)

        assert result["pruned"] == 0
        assert result["strengthened"] == 0
        assert result["reweighted"] >= 1
        assert result["reason_for_inaction"] == "reweight_only_gate"
        # `reason_for_zero` must be absent on the inaction shape.
        assert "reason_for_zero" not in result


class TestMemifyDiagnosticAbsence:
    """When any mutational counter is non-zero, both diagnostic fields are absent."""

    def test_prune_nonzero_omits_both_reason_fields(self):
        """A single prunable memory → pruned > 0 → no diagnostic field."""
        # Prune criteria: heat < 0.01 AND confidence < 0.3 AND access_count == 0.
        memories = [
            {
                "id": 1,
                "heat": 0.001,
                "confidence": 0.1,
                "access_count": 0,
                "importance": 0.5,
            }
        ]
        store = _FakeStore(memories=memories, entities=[], relationships=[])

        result = run_memify_cycle(store, memories=memories)

        assert result["pruned"] == 1
        assert "reason_for_zero" not in result
        assert "reason_for_inaction" not in result

    def test_strengthen_nonzero_omits_both_reason_fields(self):
        """A single strengthenable memory → strengthened > 0 → no field."""
        # Strengthen criteria: access_count >= 5 AND confidence >= 0.8.
        memories = [
            {
                "id": 1,
                "heat": 0.8,
                "confidence": 0.9,
                "access_count": 10,
                "importance": 0.5,
            }
        ]
        store = _FakeStore(memories=memories, entities=[], relationships=[])

        result = run_memify_cycle(store, memories=memories)

        assert result["strengthened"] == 1
        assert "reason_for_zero" not in result
        assert "reason_for_inaction" not in result
