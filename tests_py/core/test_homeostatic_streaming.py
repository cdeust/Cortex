"""Phase 4: streaming distribution health parity tests.

Asserts that ``compute_distribution_health_streaming`` computes moments
identical (within float tolerance) to ``compute_distribution_health``
over arbitrary chunking.

The streaming path uses Pébay 2008 §3.1 pairwise merge; the list-based
path uses Welford single-pass. They must agree on:
  mean, std, skew, kurtosis_excess, bimodality_coefficient, health_score

Source: docs/program/phase-5-pool-admission-design.md (Phase 4 design);
Pébay (2008) §3.1.
"""

from __future__ import annotations

import math
import random

import pytest

from mcp_server.core.homeostatic_health import (
    compute_distribution_health,
    compute_distribution_health_streaming,
)


def _rnd_heats(n: int, seed: int = 42) -> list[float]:
    rng = random.Random(seed)
    return [rng.uniform(0.0, 1.0) for _ in range(n)]


def _assert_health_equal(a: dict, b: dict, tol: float = 1e-6) -> None:
    for key in (
        "mean",
        "std",
        "skew",
        "kurtosis_excess",
        "deviation_from_target",
        "bimodality_coefficient",
        "health_score",
    ):
        assert key in a and key in b
        assert math.isclose(a[key], b[key], abs_tol=tol), (
            f"{key}: streaming={a[key]} vs list={b[key]}"
        )


class TestStreamingParity:
    @pytest.mark.parametrize("chunk_size", [1, 7, 100, 1000])
    def test_uniform_distribution_parity(self, chunk_size):
        values = _rnd_heats(500)
        list_health = compute_distribution_health(values, target_mean=0.4)
        chunks = [values[i : i + chunk_size] for i in range(0, len(values), chunk_size)]
        stream_health, n = compute_distribution_health_streaming(
            iter(chunks), target_mean=0.4
        )
        assert n == len(values)
        _assert_health_equal(stream_health, list_health)

    @pytest.mark.parametrize("chunk_size", [1, 5, 50, 200])
    def test_bimodal_distribution_parity(self, chunk_size):
        # 100 hot + 100 cold with jitter — a realistic stressor
        rng = random.Random(17)
        values = [0.9 + rng.uniform(-0.05, 0.05) for _ in range(100)]
        values += [0.2 + rng.uniform(-0.05, 0.05) for _ in range(100)]

        list_health = compute_distribution_health(values, target_mean=0.4)
        chunks = [values[i : i + chunk_size] for i in range(0, len(values), chunk_size)]
        stream_health, n = compute_distribution_health_streaming(
            iter(chunks), target_mean=0.4
        )
        assert n == len(values)
        _assert_health_equal(stream_health, list_health)

    def test_skipped_empty_chunks(self):
        values = _rnd_heats(100)
        list_health = compute_distribution_health(values, target_mean=0.4)
        # Interleave empty chunks — should be ignored
        chunks = [[], values[:30], [], values[30:70], [], values[70:], []]
        stream_health, n = compute_distribution_health_streaming(
            iter(chunks), target_mean=0.4
        )
        assert n == 100
        _assert_health_equal(stream_health, list_health)


class TestStreamingEdgeCases:
    def test_empty_input(self):
        health, n = compute_distribution_health_streaming(iter([]), target_mean=0.4)
        assert n == 0
        # Matches _EMPTY_HEALTH shape.
        for key in ("mean", "std", "skew", "kurtosis_excess"):
            assert health[key] == 0.0

    def test_single_value(self):
        health, n = compute_distribution_health_streaming(
            iter([[0.5]]), target_mean=0.4
        )
        assert n == 1
        assert health["mean"] == pytest.approx(0.5)
        assert health["std"] == 0.0
        # skew/kurtosis are 0 when std is degenerate
        assert health["skew"] == 0.0
