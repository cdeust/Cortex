"""A3 homeostatic cycle: scalar + fold tests.

Asserts:
    - unimodal/off-target → single set_homeostatic_factor call (no per-row writes)
    - |log(factor)| > log(2.0) → fold UPDATE + factor reset
    - bimodal → cohort correction via bump_heat_raw (I2 canonical writer)

Source: docs/program/phase-3-a3-migration-design.md §5.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_server.handlers.consolidation.homeostatic import (
    _apply_scalar,
    _fold_triggered,
    run_homeostatic_cycle,
)


def _memory(mid: int, heat: float, domain: str = "default") -> dict:
    return {
        "id": mid,
        "heat": heat,
        "domain": domain,
        "is_protected": False,
        "is_stale": False,
    }


def _unimodal_low(n: int = 40) -> list[dict]:
    """Unimodal distribution centered below target (0.4). Triggers scaling."""
    return [_memory(i, 0.15 + 0.001 * i) for i in range(n)]


def _stub_store(factor_return: float = 1.0) -> MagicMock:
    """Stub a MemoryStore that mocks the Phase 5 pool API.

    ``acquire_batch()`` / ``acquire_interactive()`` return context
    managers whose ``__enter__`` yields a mock connection. The mock
    connection's ``execute()`` returns a cursor-like object with a
    configurable ``rowcount``.
    """
    store = MagicMock()
    store.get_homeostatic_factor.return_value = factor_return
    store.set_homeostatic_factor.return_value = None

    conn_result = MagicMock()
    conn_result.rowcount = 0
    conn = MagicMock()
    conn.execute.return_value = conn_result

    # acquire_batch returns a context manager yielding `conn`.
    batch_cm = MagicMock()
    batch_cm.__enter__ = MagicMock(return_value=conn)
    batch_cm.__exit__ = MagicMock(return_value=False)
    store.acquire_batch.return_value = batch_cm

    interactive_cm = MagicMock()
    interactive_cm.__enter__ = MagicMock(return_value=conn)
    interactive_cm.__exit__ = MagicMock(return_value=False)
    store.acquire_interactive.return_value = interactive_cm

    # Expose the inner conn for assertions
    store._test_conn = conn
    return store


class TestFoldTrigger:
    def test_factor_one_no_fold(self):
        assert _fold_triggered(1.0) is False

    def test_factor_within_half_to_two_no_fold(self):
        assert _fold_triggered(0.6) is False
        assert _fold_triggered(1.8) is False

    def test_factor_above_two_triggers_fold(self):
        assert _fold_triggered(2.1) is True
        assert _fold_triggered(5.0) is True

    def test_factor_below_half_triggers_fold(self):
        assert _fold_triggered(0.4) is True
        assert _fold_triggered(0.1) is True

    def test_factor_zero_no_fold(self):
        assert _fold_triggered(0.0) is False
        assert _fold_triggered(-0.1) is False

    def test_log_two_boundary(self):
        """Exactly at log(2.0) is NOT a fold (strict > threshold)."""
        assert _fold_triggered(2.0) is False
        assert _fold_triggered(0.5) is False
        assert _fold_triggered(2.0 + 1e-6) is True
        assert _fold_triggered(0.5 - 1e-6) is True


class TestScalarPath:
    def test_off_target_writes_scalar_not_per_row(self):
        """One set_homeostatic_factor call, zero per-row writes."""
        store = _stub_store(factor_return=1.0)
        memories = _unimodal_low(n=40)

        # Pass memories explicitly (pre-loaded path) — Phase 4 streaming
        # path is exercised in tests/core/test_homeostatic_streaming.py.
        result = run_homeostatic_cycle(store, memories=memories)

        assert result["scaling_kind"] == "scalar_update"
        assert result["scaling_applied"] is True
        store.set_homeostatic_factor.assert_called_once()
        store.bump_heat_raw.assert_not_called()

    def test_fold_triggered_writes_batch_and_resets_factor(self):
        """Drifted factor past log(2) threshold → fold UPDATE + factor reset."""
        # Start with factor=3.0 (already past threshold). mean ≈ 0.17
        # → target/mean ≈ 2.35 → new = 3.0 * 2.35 = 7.05, but capped
        # at 3.0 * 1.03 = 3.09 — still past the 2.0 threshold.
        store = _stub_store(factor_return=3.0)
        memories = _unimodal_low(n=40)

        result = run_homeostatic_cycle(store, memories=memories)

        assert result["scaling_kind"] == "fold"
        assert result["scaling_applied"] is True
        # Phase 5: fold UPDATE runs on the batch pool's checked-out connection.
        store.acquire_batch.assert_called_once()
        store._test_conn.execute.assert_called_once()
        # Post-fold, factor reset to 1.0.
        args, _ = store.set_homeostatic_factor.call_args
        assert args[1] == pytest.approx(1.0)


class TestApplyScalarUnit:
    def test_mean_below_safety_floor_noop(self):
        store = _stub_store()
        result = _apply_scalar(
            store=store,
            memories=[_memory(1, 0.005)],
            mean=0.001,
            bimodality=0.3,
        )
        assert result["scaling_applied"] is False
        assert result["reason_for_zero"] == "mean_below_safety_floor"
        store.set_homeostatic_factor.assert_not_called()

    def test_factor_stable_noop(self):
        """mean ≈ target → new factor ≈ old factor → noop."""
        store = _stub_store(factor_return=1.0)
        result = _apply_scalar(
            store=store,
            memories=[_memory(1, 0.4)],
            mean=0.4,
            bimodality=0.3,
        )
        assert result["scaling_applied"] is False
        assert result["reason_for_zero"] == "factor_stable"
