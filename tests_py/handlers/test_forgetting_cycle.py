"""Handler tests for the active-forgetting consolidation cycle.

The chronic-interference aggregator and the leaky integrator are pure core
(``mcp_server.core.active_forgetting``) and are tested there; this file checks
the WIRING — that the handler reads raw newer-neighbour similarities, advances
and persists the per-memory accumulator every cycle, and routes the two circuits
to the right reversible effect. No database (fake duck-typed store).
"""

from __future__ import annotations

import pytest

from mcp_server.core.active_forgetting import (
    ACUTE_OVERLAP_THRESHOLD,
    ACUTE_RECENCY_WINDOW_HOURS,
    PERMANENT_ACCUM_THRESHOLD,
)
from mcp_server.handlers.consolidation.forgetting import (
    _evaluate_memory,
    run_forgetting_cycle,
)


# ── Effect wiring (fake store, no database) ───────────────────────────────


class _FakeStore:
    """Minimal duck-typed store: records the reversible effect applied."""

    def __init__(self, neighbors):
        self._neighbors = neighbors
        self.staled: list[int] = []
        self.heat_writes: dict[int, float] = {}
        self.accum_writes: dict[int, float] = {}

    def search_newer_neighbors(self, embedding, after, exclude_id, top_k=10):
        return self._neighbors

    def mark_memory_stale(self, memory_id, stale=True):
        self.staled.append(memory_id)

    def update_memory_heat(self, memory_id, heat):
        self.heat_writes[memory_id] = heat

    def update_forgetting_pressure_accum(self, memory_id, accum):
        self.accum_writes[memory_id] = accum


def _memory(**over):
    base = {
        "id": 1,
        "embedding": b"\x00\x00\x80?",  # non-empty; fake store ignores content
        "created_at": "2026-01-01T00:00:00+00:00",
        "consolidation_stage": "labile",
        "heat": 0.5,
        "is_protected": False,
        "forgetting_pressure_accum": 0.0,
    }
    base.update(over)
    return base


def test_transient_effect_scales_heat_by_interferer_overlap():
    """DAMB block: heat × (1 - acute_overlap), magnitude from measured salience.

    Uses a ``consolidated`` stage so the permanent accumulator stays far below
    Θ and the transient circuit is isolated (disjoint signals).
    """
    overlap = 0.8  # ≥ ACUTE_OVERLAP_THRESHOLD, recent → transient fires
    assert overlap >= ACUTE_OVERLAP_THRESHOLD
    store = _FakeStore([(overlap, 1.0)])  # 1.0h ago ≤ window
    effect = _evaluate_memory(
        store, _memory(consolidation_stage="consolidated", heat=0.5), set()
    )
    assert effect == "transient"
    assert store.heat_writes[1] == pytest.approx(0.5 * (1 - overlap))
    assert store.staled == []


def test_permanent_requires_sustained_pressure_not_a_single_cycle():
    """A single strong cycle from zero accumulator does NOT fire permanent —
    the leaky integrator demands sustained interference (the saturation fix)."""
    store = _FakeStore([(0.9, 100.0)] * 5)  # strong genuine near-dups, old enough
    effect = _evaluate_memory(store, _memory(consolidation_stage="labile"), set())
    assert effect == "retain"
    assert store.staled == []
    assert 0.0 < store.accum_writes[1] < PERMANENT_ACCUM_THRESHOLD


def test_permanent_fires_once_accumulator_crosses_threshold():
    """With prior accumulated pressure, one more strong cycle crosses Θ → stale."""
    store = _FakeStore([(0.9, 100.0)] * 5)  # old enough that transient won't fire
    mem = _memory(consolidation_stage="labile", forgetting_pressure_accum=1.0)
    effect = _evaluate_memory(store, mem, set())
    assert effect == "permanent"
    assert store.staled == [1]
    assert store.accum_writes[1] >= PERMANENT_ACCUM_THRESHOLD


def test_accumulator_persisted_every_cycle_including_leak():
    """Even a retain cycle writes back the (possibly leaked) accumulator."""
    store = _FakeStore([(0.5, 100.0)] * 5)  # background band → chronic 0
    mem = _memory(consolidation_stage="labile", forgetting_pressure_accum=0.4)
    effect = _evaluate_memory(store, mem, set())
    assert effect == "retain"
    # chronic 0 → accum = λ·0.4 = 0.34 (leaked, not reset)
    assert store.accum_writes[1] == pytest.approx(0.85 * 0.4)


def test_background_neighbours_never_accumulate_pressure():
    """A full field of background (~0.5) neighbours yields chronic 0 → no growth."""
    store = _FakeStore([(0.52, 100.0), (0.61, 100.0), (0.48, 100.0), (0.55, 100.0)])
    effect = _evaluate_memory(store, _memory(consolidation_stage="labile"), set())
    assert effect == "retain"
    assert store.accum_writes[1] == 0.0


def test_pinned_memory_is_exempt_from_both_circuits():
    """is_protected (or heat≥1.0) exempts the memory entirely."""
    store = _FakeStore([(0.95, 1.0)])  # would otherwise fire transient
    mem = _memory(is_protected=True, forgetting_pressure_accum=10.0)
    effect = _evaluate_memory(store, mem, set())
    assert effect == "retain"
    assert store.staled == [] and store.heat_writes == {}


def test_recently_active_memory_is_sleep_protected():
    """A memory replayed this cycle is exempt; its accumulator leaks (pressure 0)."""
    store = _FakeStore([(0.95, 1.0)])
    mem = _memory(id=7, forgetting_pressure_accum=1.0)
    effect = _evaluate_memory(store, mem, recently_active_ids={7})
    assert effect == "retain"
    assert store.accum_writes[7] == pytest.approx(0.85 * 1.0)  # leaked, no new pressure


def test_old_acute_interferer_does_not_trigger_transient():
    """Beyond the recovery window the transient block has lapsed."""
    store = _FakeStore([(0.95, ACUTE_RECENCY_WINDOW_HOURS + 5.0)])
    effect = _evaluate_memory(
        store, _memory(consolidation_stage="consolidated"), set()
    )
    # consolidated → near-zero permanent pressure; stale acute → no transient.
    assert effect == "retain"


def test_cycle_skips_when_store_lacks_newer_neighbor_query():
    """SQLite/cowork fallback degrades gracefully, never raises."""

    class _Bare:
        def iter_memories_for_decay(self):
            return [[_memory()]]

    out = run_forgetting_cycle(_Bare(), set())
    assert out["skipped"] == "unsupported_store"
    assert out["scanned"] == 0


def test_cycle_counts_scanned_and_effects():
    """End-to-end count rollup over a streamed chunk."""

    class _Streaming(_FakeStore):
        def iter_memories_for_decay(self):
            yield [
                _memory(id=1, consolidation_stage="consolidated", heat=0.5),
                _memory(id=2, consolidation_stage="consolidated", heat=0.5),
            ]

    store = _Streaming([(0.8, 1.0)])  # consolidated → permanent quiet; both transient
    out = run_forgetting_cycle(store, set())
    assert out["scanned"] == 2
    assert out["transient"] == 2
    assert out["permanent"] == 0


def test_ablation_short_circuits_cycle(monkeypatch):
    """CORTEX_ABLATE_ACTIVE_FORGETTING=1 → no-op pass."""
    monkeypatch.setenv("CORTEX_ABLATE_ACTIVE_FORGETTING", "1")
    out = run_forgetting_cycle(_FakeStore([(0.9, 1.0)]), set())
    assert out["ablated"] is True
    assert out["scanned"] == 0
