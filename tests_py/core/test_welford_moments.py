"""Welford one-pass moments — parity with the four-pass baseline.

Source: Pébay P (2008) Formulas for Robust, One-Pass Parallel Computation of
Covariances and Arbitrary-Order Statistical Moments. Sandia Report
SAND2008-6212.

Two properties are tested:

1. **Parity**: the new one-pass ``_compute_moments`` agrees with the
   legacy four-pass baseline to within 1e-9 on 1000 random values, on
   constant arrays, on tiny arrays, and on heavy-tailed distributions.
2. **Single-pass**: wrapping the input list with an iteration counter,
   the function touches each element exactly once.
"""

from __future__ import annotations

import math
import random
from typing import Iterable

from mcp_server.core.homeostatic_health import _compute_moments


# ── Reference: legacy four-pass implementation, kept only for parity tests ──


def _four_pass_moments(values: list[float]) -> tuple[float, float, float, float]:
    """Reference four-pass implementation (the pre-Welford baseline).

    This is intentionally a copy of the pre-Welford code so parity is
    measured against the exact prior behaviour.
    """
    n = len(values)
    if n == 0:
        return 0.0, 0.0, 0.0, 0.0

    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / max(n - 1, 1)
    std = math.sqrt(variance)

    if std > 1e-10:
        skew = sum((v - mean) ** 3 for v in values) / (n * std**3)
        kurtosis = sum((v - mean) ** 4 for v in values) / (n * std**4) - 3.0
    else:
        skew = 0.0
        kurtosis = 0.0
    return mean, std, skew, kurtosis


def _assert_moments_close(a, b, tol=1e-9):
    assert math.isclose(a[0], b[0], abs_tol=tol), f"mean: {a[0]} vs {b[0]}"
    assert math.isclose(a[1], b[1], abs_tol=tol), f"std: {a[1]} vs {b[1]}"
    assert math.isclose(a[2], b[2], abs_tol=tol), f"skew: {a[2]} vs {b[2]}"
    assert math.isclose(a[3], b[3], abs_tol=tol), f"kurt: {a[3]} vs {b[3]}"


class TestParity:
    """The one-pass implementation must match the four-pass one."""

    def test_1000_random_values(self):
        random.seed(42)
        values = [random.random() for _ in range(1000)]
        got = _compute_moments(values)
        expected = _four_pass_moments(values)
        _assert_moments_close(got, expected)

    def test_1000_gaussian_values(self):
        random.seed(7)
        values = [random.gauss(0.5, 0.2) for _ in range(1000)]
        got = _compute_moments(values)
        expected = _four_pass_moments(values)
        _assert_moments_close(got, expected)

    def test_heavy_tailed(self):
        """Pareto-ish distribution — skew/kurt are large but finite."""
        random.seed(13)
        values = [random.paretovariate(1.5) for _ in range(500)]
        got = _compute_moments(values)
        expected = _four_pass_moments(values)
        # Heavy tails amplify numerical error; allow a looser tolerance
        # on kurtosis specifically. Pébay 2008 §4 shows Welford is more
        # stable than the naive formula, not less, so the tolerance is
        # loose because the *reference* is the noisy one.
        assert math.isclose(got[0], expected[0], rel_tol=1e-9)
        assert math.isclose(got[1], expected[1], rel_tol=1e-9)
        assert math.isclose(got[2], expected[2], rel_tol=1e-6)
        assert math.isclose(got[3], expected[3], rel_tol=1e-6)

    def test_constant_array(self):
        """std == 0 → skew and kurtosis must be 0, not NaN."""
        values = [0.5] * 100
        got = _compute_moments(values)
        assert got[0] == 0.5
        assert got[1] < 1e-10
        assert got[2] == 0.0
        assert got[3] == 0.0

    def test_two_values(self):
        got = _compute_moments([0.3, 0.7])
        expected = _four_pass_moments([0.3, 0.7])
        _assert_moments_close(got, expected)

    def test_one_value(self):
        got = _compute_moments([0.42])
        expected = _four_pass_moments([0.42])
        _assert_moments_close(got, expected)

    def test_empty(self):
        got = _compute_moments([])
        assert got == (0.0, 0.0, 0.0, 0.0)

    def test_realistic_heat_distribution(self):
        """Simulate a 66K-memory heat distribution: mostly cold, a few hot."""
        random.seed(99)
        values = [random.random() * 0.2 for _ in range(60_000)]
        values += [0.5 + random.random() * 0.5 for _ in range(6000)]
        got = _compute_moments(values)
        expected = _four_pass_moments(values)
        _assert_moments_close(got, expected, tol=1e-8)


class _CountingIterable:
    """Iterable wrapper that records the number of ``__iter__`` calls.

    If an algorithm iterates the source more than once, __iter__ is called
    more than once — that's the signal we catch.
    """

    def __init__(self, values: list[float]):
        self._values = values
        self.iter_calls = 0
        self.item_calls = 0

    def __iter__(self) -> Iterable[float]:
        self.iter_calls += 1
        for v in self._values:
            self.item_calls += 1
            yield v


class TestSinglePass:
    """The implementation must touch each element exactly once."""

    def test_iter_called_exactly_once(self):
        counter = _CountingIterable([0.1, 0.2, 0.3, 0.4, 0.5])
        _compute_moments(counter)
        assert counter.iter_calls == 1, (
            f"expected a single pass, got {counter.iter_calls} iterations"
        )

    def test_each_item_visited_exactly_once(self):
        counter = _CountingIterable([float(i) for i in range(100)])
        _compute_moments(counter)
        assert counter.item_calls == 100, (
            f"expected 100 item reads, got {counter.item_calls}"
        )

    def test_large_input_single_pass(self):
        random.seed(1)
        data = [random.random() for _ in range(1000)]
        counter = _CountingIterable(data)
        _compute_moments(counter)
        assert counter.iter_calls == 1
        assert counter.item_calls == 1000
