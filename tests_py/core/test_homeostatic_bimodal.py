"""Tests for Fix 2 of issue #14 P1 — bimodality-aware homeostatic cycle.

Covers:
- detect_hot_cohort unit behavior.
- apply_cohort_correction unit behavior (non-order-preserving, mode-merging).
- Integration with _maybe_apply_scaling: bimodal → cohort_correction,
  unimodal-off-target → multiplicative (backward compat).
"""

from __future__ import annotations

import math
import random

from mcp_server.core.homeostatic_health import compute_distribution_health
from mcp_server.core.homeostatic_plasticity import (
    apply_cohort_correction,
    apply_synaptic_scaling,
    detect_hot_cohort,
)
from mcp_server.handlers.consolidation.homeostatic import (
    _maybe_apply_scaling,
    run_homeostatic_cycle,
)


def _moments(values: list[float]) -> tuple[float, float]:
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / max(n - 1, 1)
    return mean, math.sqrt(var)


def _jittered_bimodal(n_hot: int, n_cold: int, seed: int = 42) -> list[float]:
    """Realistic bimodal heat distribution with ±0.03 jitter per peak.

    Pure point-mass peaks hit a mathematical artifact in the Pfister
    bimodality formula (kurtosis_excess = -2 ⇒ b = 1.0 regardless of
    peak separation). Real-world heat distributions have jitter from
    surprise boost + access history, so tests use ±3% noise to reproduce
    the kurtosis behaviour that lets cohort correction demonstrate
    bimodality reduction over multiple cycles.
    """
    rng = random.Random(seed)
    hot = [min(1.0, 0.98 + rng.uniform(-0.03, 0.03)) for _ in range(n_hot)]
    cold = [max(0.0, 0.25 + rng.uniform(-0.03, 0.03)) for _ in range(n_cold)]
    return hot + cold


class TestDetectHotCohort:
    def test_bimodal_isolates_hot_peak(self):
        # Use default sigma=0.5 — sigma=1.0 lands exactly between peaks
        # for symmetric bimodal distributions and catches nothing.
        heats = [0.98] * 100 + [0.25] * 100
        mean, std = _moments(heats)
        idx = detect_hot_cohort(heats, mean, std)
        assert len(idx) == 100
        assert all(i < 100 for i in idx)

    def test_unimodal_returns_few(self):
        # Tight unimodal distribution: few outliers past sigma=0.5.
        heats = [0.4 + 0.05 * (i % 3 - 1) for i in range(100)]
        mean, std = _moments(heats)
        idx = detect_hot_cohort(heats, mean, std)
        # mod-3 pattern creates 3 equal-mass clusters; about ~33% above
        # mean+0.5*std. Assert < 50% so unimodal cohort is bounded.
        assert len(idx) < 50

    def test_empty_returns_empty(self):
        assert detect_hot_cohort([], 0.0, 0.0) == []

    def test_zero_std_returns_empty(self):
        assert detect_hot_cohort([0.5, 0.5, 0.5], 0.5, 0.0) == []


class TestApplyCohortCorrection:
    def test_cohort_members_move_toward_target(self):
        heats = [0.95, 0.9, 0.85, 0.3, 0.25]
        result = apply_cohort_correction(
            heats,
            cohort_indices=[0, 1, 2],
            target_mean=0.4,
            correction_strength=0.3,
        )
        assert result[0] < heats[0]
        assert result[1] < heats[1]
        assert result[2] < heats[2]
        # non-cohort untouched
        assert result[3] == heats[3]
        assert result[4] == heats[4]

    def test_clamped_to_unit_interval(self):
        heats = [2.0, -1.0, 0.5]
        out = apply_cohort_correction(
            heats,
            cohort_indices=[0, 1, 2],
            target_mean=0.4,
            correction_strength=0.3,
        )
        assert all(0.0 <= h <= 1.0 for h in out)

    def test_std_decreases_after_one_cycle(self):
        # Cohort correction pulls the hot peak toward target, narrowing
        # the overall spread. Std is the clean primary metric; Pfister
        # bimodality is scale-invariant for symmetric bimodal and only
        # decreases once the peaks start to overlap.
        heats = _jittered_bimodal(100, 100)
        before = compute_distribution_health(heats, target_mean=0.4)
        mean, std = _moments(heats)
        cohort = detect_hot_cohort(heats, mean, std)
        scaled = apply_cohort_correction(heats, cohort, target_mean=0.4)
        after = compute_distribution_health(scaled, target_mean=0.4)
        assert after["std"] < before["std"]
        assert (
            after["bimodality_coefficient"] <= before["bimodality_coefficient"] + 1e-6
        )

    def test_five_cycles_flatten_peak(self):
        heats = _jittered_bimodal(100, 100)
        before_std = compute_distribution_health(heats, target_mean=0.4)["std"]
        for _ in range(5):
            mean, std = _moments(heats)
            cohort = detect_hot_cohort(heats, mean, std)
            if not cohort:
                break
            heats = apply_cohort_correction(heats, cohort, target_mean=0.4)
        health = compute_distribution_health(heats, target_mean=0.4)
        assert health["std"] < before_std * 0.6

    def test_unlike_multiplicative_breaks_global_order(self):
        # Multiplicative: factor applied to all, relative order preserved.
        heats = [0.9, 0.5, 0.1]
        mult = apply_synaptic_scaling(heats, 0.8)
        assert mult[0] > mult[1] > mult[2]
        # Cohort correction: only index 0 is in the cohort; the others
        # stay put, so relative order 0 > 1 > 2 can be compressed.
        coh = apply_cohort_correction(
            heats,
            cohort_indices=[0],
            target_mean=0.4,
            correction_strength=0.8,
        )
        assert coh[0] < heats[0]
        assert coh[1] == heats[1]
        assert coh[2] == heats[2]


class _FakeStore:
    """Minimal stand-in for MemoryStore (no DB; in-memory list)."""

    def __init__(self, heats: list[float]) -> None:
        self._heats = list(heats)
        self.updates: list[tuple[int, float]] = []

    def get_all_memories_for_decay(self) -> list[dict]:
        return [{"id": i, "heat": h} for i, h in enumerate(self._heats)]

    def update_memory_heat(self, memory_id: int, heat: float) -> None:
        self.updates.append((memory_id, heat))
        self._heats[memory_id] = heat


class TestMaybeApplyScalingBranching:
    def test_bimodal_triggers_cohort_correction(self):
        heats = _jittered_bimodal(100, 100)
        store = _FakeStore(heats)
        memories = store.get_all_memories_for_decay()
        health = compute_distribution_health(heats, target_mean=0.4)
        # Sanity: synthetic distribution triggers the 0.7 bimodality gate.
        assert health["bimodality_coefficient"] > 0.7
        outcome = _maybe_apply_scaling(store, memories, heats, health)
        assert outcome["scaling_kind"] == "cohort_correction"
        assert outcome["scaling_applied"] is True
        assert outcome["bimodality_after"] is not None
        # bimodality non-increasing (see std-based test for strict metric).
        assert outcome["bimodality_after"] <= outcome["bimodality_before"] + 1e-6
        assert outcome["cohort_size"] == 100
        # Only cohort members were written back.
        assert all(mid < 100 for mid, _ in store.updates)

    def test_unimodal_off_target_triggers_multiplicative(self):
        # Narrow peak centered at 0.75 — unhealthy (off target=0.4) but
        # bimodality stays below trigger=0.7 (measured ~0.6 for mod-5).
        heats = [0.75 + 0.02 * ((i % 5) - 2) for i in range(100)]
        store = _FakeStore(heats)
        memories = store.get_all_memories_for_decay()
        health = compute_distribution_health(heats, target_mean=0.4)
        assert health["bimodality_coefficient"] <= 0.7
        outcome = _maybe_apply_scaling(store, memories, heats, health)
        assert outcome["scaling_kind"] == "multiplicative"
        assert outcome["scaling_applied"] is True

    def test_healthy_distribution_is_noop(self):
        heats = [0.35, 0.38, 0.40, 0.42, 0.45, 0.40, 0.39, 0.41]
        store = _FakeStore(heats)
        memories = store.get_all_memories_for_decay()
        health = compute_distribution_health(heats, target_mean=0.4)
        outcome = _maybe_apply_scaling(store, memories, heats, health)
        assert outcome["scaling_kind"] == "none"
        assert outcome["scaling_applied"] is False
        assert store.updates == []


class TestRunHomeostaticCycleReturn:
    def test_empty_store_backward_compat(self):
        class Empty:
            def get_all_memories_for_decay(self) -> list[dict]:
                return []

        result = run_homeostatic_cycle(Empty())
        assert result["scaling_applied"] is False
        assert result["scaling_kind"] == "none"
        assert result["health_score"] is None
        assert result["reason"] == "no_memories"

    def test_bimodal_end_to_end(self):
        heats = _jittered_bimodal(50, 50, seed=17)
        store = _FakeStore(heats)
        result = run_homeostatic_cycle(store)
        assert result["scaling_kind"] == "cohort_correction"
        assert result["scaling_applied"] is True
        assert "bimodality_after" in result
        # std_heat reported at the top level after the cycle. Cohort
        # correction provably narrows the distribution even when the
        # Pfister ratio is scale-invariant.
        assert result["std_heat"] > 0
        assert result["bimodality_after"] <= result["bimodality_before"] + 1e-6
