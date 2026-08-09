"""benchmarks.lib.capture_origin_mix — measured production origin mixture.

Contract under test:
  - CAPTURE_ORIGIN_MIX sums to 1.0 and only names origins
    mcp_server.core.capture_origin actually recognises.
  - assign_capture_origins is deterministic (same n/seed -> same output,
    every call, matching benchmarks/reproduce.sh's "hit play, get the same
    numbers" contract) and produces a mixture, not a constant column — the
    property that makes the trust-factor gated arm able to discriminate W
    (docs/provenance/trust-factor-calibration.md).
"""

from __future__ import annotations

from benchmarks.lib.capture_origin_mix import (
    CAPTURE_ORIGIN_MIX,
    DEFAULT_SEED,
    assign_capture_origins,
)
from mcp_server.core.capture_origin import ALL_ORIGINS


class TestCaptureOriginMix:
    def test_weights_sum_to_one(self):
        assert abs(sum(w for _, w in CAPTURE_ORIGIN_MIX) - 1.0) < 1e-9

    def test_every_origin_is_recognised_by_capture_origin_module(self):
        for origin, _weight in CAPTURE_ORIGIN_MIX:
            assert origin in ALL_ORIGINS

    def test_mixture_is_not_all_trusted_or_all_untrusted(self):
        """The whole point: at least one origin in the mix must be untrusted
        at read time, or the gated arm is back to a uniform multiplier."""
        from mcp_server.core.capture_origin import is_trusted_at_read

        trust = {origin: is_trusted_at_read(origin) for origin, _ in CAPTURE_ORIGIN_MIX}
        assert True in trust.values()
        assert False in trust.values()


class TestAssignCaptureOrigins:
    def test_empty_input(self):
        assert assign_capture_origins(0) == []

    def test_length_matches_n(self):
        result = assign_capture_origins(500)
        assert len(result) == 500

    def test_deterministic_across_calls(self):
        a = assign_capture_origins(200, seed=DEFAULT_SEED)
        b = assign_capture_origins(200, seed=DEFAULT_SEED)
        assert a == b

    def test_different_seed_can_differ(self):
        a = assign_capture_origins(500, seed=1)
        b = assign_capture_origins(500, seed=2)
        assert a != b

    def test_produces_a_realistic_mixture_not_a_single_value(self):
        """At n=5000, both a dominant (local_action) and a minority
        (network) origin must actually appear — asserts the harness fix
        actually mixes origins rather than collapsing to one value."""
        result = assign_capture_origins(5000)
        origins_present = set(result)
        assert "local_action" in origins_present
        assert "network" in origins_present

    def test_only_yields_declared_origins(self):
        declared = {o for o, _ in CAPTURE_ORIGIN_MIX}
        result = assign_capture_origins(1000)
        assert set(result) <= declared
