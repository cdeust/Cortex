"""Tests for Tsodyks-Markram STP in synaptic_plasticity_stp.py.

Covers: release probability (u_eff * x), facilitation (u dynamics),
depression (x dynamics / vesicle depletion), noise injection,
phase-gated plasticity, and the full stochastic Hebbian update.

Imports go through the `synaptic_plasticity` facade, which is the public
surface every consumer uses; the implementation lives in
`synaptic_plasticity_stp` (issue #233).

Mutation-testing notes (coding-standards §12.4). Measured 2026-07-29 with
mutmut 3.6.0 via `scripts/mutation_check.sh
tests_py/core/test_stochastic_transmission.py
mcp_server/core/synaptic_plasticity_stp.py`: 128 mutants, 29 initially
surviving. The inequality assertions below ("u decays", "x recovers") cannot
distinguish the published Tsodyks-Markram equations from arithmetic variants
of them, so the `Test*Exact*` cases pin the numbers the equations actually
produce. 26 of the 29 are killed that way. The remaining 3 are equivalent
mutants — no observable behaviour change — and are recorded here rather than
tested for:

  1. `_recover_between_spikes`: `if hours_elapsed <= 0` → `< 0`. The two
     differ only at `hours_elapsed == 0`, where the recovery formulas reduce
     to the identity (`u * exp(0) == u`, `1 - (1 - x) * exp(0) == x`). The
     residual is IEEE-754 reassociation round-off (~4e-17, e.g. `1.0 - 0.8`
     for x=0.2) and `update_short_term_dynamics` rounds both components to 6
     decimals before returning, so no public call can observe it.
  2. `compute_noisy_weight_update`: `if access_count <= 0` → `<= 1`. The two
     differ only at `access_count == 1`, where both branches yield
     `evidence_factor == 1.0` exactly (`1.0 / math.sqrt(1)` is `1.0`).
  3. `phase_modulate_plasticity`: `cos(2*pi*(theta_phase - 0.25))` →
     `- 1.25`. The shift is exactly one period of cosine, so the two are
     mathematically identical; the measured difference is <= 2.5e-16 across
     theta in {0, 0.125, 0.25, 0.4, 0.5, 0.75, 0.9, 1.0}. Pinning that would
     assert float noise, not behaviour.
"""

import random

import pytest

from mcp_server.core.synaptic_plasticity import (
    SynapticState,
    compute_effective_release_probability,
    stochastic_transmit,
    update_short_term_dynamics,
    compute_noisy_weight_update,
    phase_modulate_plasticity,
    apply_stochastic_hebbian_update,
)


class _FixedRandom(random.Random):
    """Deterministic rng stub making the computed noise scale observable.

    `random()` returns a caller-chosen value, so the `r < p` release
    comparison can be probed exactly at its boundary. `gauss()` returns the
    sigma it was handed, so `compute_noisy_weight_update`'s evidence scaling
    — the quantity it exists to compute — appears directly in the return
    value instead of only in the variance of a sample.
    """

    def __init__(self, uniform_value: float = 0.0) -> None:
        super().__init__()
        self._uniform_value = uniform_value
        self.last_sigma: float | None = None

    def random(self) -> float:
        return self._uniform_value

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        self.last_sigma = sigma
        return sigma


# -- Release Probability (u_eff * x) ------------------------------------------


class TestEffectiveReleaseProbability:
    def test_default_state(self):
        """Default: u=0, x=1 → u_eff = U=0.2, p = 0.2*1.0 = 0.2."""
        state = SynapticState()
        assert compute_effective_release_probability(state) == pytest.approx(
            0.2, abs=0.01
        )

    def test_high_facilitation_increases_p(self):
        """High u → higher u_eff → higher release probability."""
        state = SynapticState(u=0.8)
        p = compute_effective_release_probability(state)
        assert p > 0.5

    def test_depleted_vesicles_decreases_p(self):
        """Low x (depleted) → lower release despite facilitation."""
        state = SynapticState(u=0.5, x=0.2)
        p = compute_effective_release_probability(state)
        assert p < 0.2

    def test_clamped_high(self):
        """Maximum facilitation + full vesicles → capped at 0.95."""
        state = SynapticState(u=1.0, x=1.0)
        assert compute_effective_release_probability(state) == 0.95

    def test_clamped_low(self):
        """Near-empty vesicles → clamped at 0.05."""
        state = SynapticState(u=0.0, x=0.01)
        assert compute_effective_release_probability(state) == 0.05

    def test_facilitation_and_depletion_interact(self):
        """High u but low x: facilitation can't overcome empty vesicles."""
        full = SynapticState(u=0.5, x=1.0)
        depleted = SynapticState(u=0.5, x=0.3)
        assert compute_effective_release_probability(
            full
        ) > compute_effective_release_probability(depleted)

    def test_u_eff_equals_U_plus_u_times_one_minus_U(self):
        """Exact formula, not just its monotonicity (Tsodyks & Markram 1997).

        u_eff = U + u*(1 - U) = 0.2 + 0.5*0.8 = 0.6; x = 1.0, and 0.6 is
        inside the [0.05, 0.95] clamp, so p == 0.6.
        """
        state = SynapticState(u=0.5, x=1.0)
        assert compute_effective_release_probability(state) == pytest.approx(
            0.6, abs=1e-12
        )


# -- Stochastic Transmission --------------------------------------------------


class TestStochasticTransmit:
    def test_high_probability_mostly_transmits(self):
        state = SynapticState(u=0.9, x=1.0)
        rng = random.Random(42)
        transmissions = sum(stochastic_transmit(state, rng=rng) for _ in range(100))
        assert transmissions > 80

    def test_low_probability_mostly_blocks(self):
        state = SynapticState(u=0.0, x=0.3)
        rng = random.Random(42)
        transmissions = sum(stochastic_transmit(state, rng=rng) for _ in range(100))
        assert transmissions < 20

    def test_deterministic_with_fixed_rng(self):
        state = SynapticState(u=0.5, x=0.8)
        rng1 = random.Random(123)
        rng2 = random.Random(123)
        results1 = [stochastic_transmit(state, rng=rng1) for _ in range(10)]
        results2 = [stochastic_transmit(state, rng=rng2) for _ in range(10)]
        assert results1 == results2

    def test_draw_exactly_equal_to_p_does_not_transmit(self):
        """The comparison is strict: r == p blocks, r just below transmits.

        Sampling never lands on the boundary, so only a stub draw pins which
        side of `r < p` the equality case falls on.
        """
        state = SynapticState()  # u=0, x=1 → p = 0.2
        assert stochastic_transmit(state, rng=_FixedRandom(0.2)) is False
        assert stochastic_transmit(state, rng=_FixedRandom(0.19)) is True


# -- Tsodyks-Markram Dynamics --------------------------------------------------


class TestShortTermDynamics:
    def test_spike_increases_facilitation(self):
        """Spike boosts u: u_new = u + U*(1-u)."""
        state = SynapticState(u=0.0, x=1.0)
        updated = update_short_term_dynamics(state, hours_elapsed=0.0, is_access=True)
        assert updated.u > 0  # u should increase from 0
        assert updated.u == pytest.approx(0.2, abs=0.01)  # U=0.2, u=0+0.2*(1-0)
        assert updated.access_count == 1

    def test_spike_depletes_vesicles(self):
        """Spike depletes x: x_new = x - u_eff * x."""
        state = SynapticState(u=0.0, x=1.0)
        updated = update_short_term_dynamics(state, hours_elapsed=0.0, is_access=True)
        assert updated.x < 1.0  # vesicles depleted

    def test_repeated_spikes_deplete_further(self):
        """Rapid repeated spikes deplete vesicles progressively."""
        state = SynapticState(u=0.0, x=1.0)
        s1 = update_short_term_dynamics(state, hours_elapsed=0.0, is_access=True)
        s2 = update_short_term_dynamics(s1, hours_elapsed=0.01, is_access=True)
        assert s2.x < s1.x  # further depletion

    def test_facilitation_decays_over_time(self):
        """Between spikes: u decays exponentially to 0."""
        state = SynapticState(u=0.5, x=0.5)
        updated = update_short_term_dynamics(state, hours_elapsed=2.0, is_access=False)
        assert updated.u < 0.5  # u decays toward 0

    def test_vesicles_recover_over_time(self):
        """Between spikes: x recovers exponentially to 1."""
        state = SynapticState(u=0.0, x=0.3)
        updated = update_short_term_dynamics(state, hours_elapsed=5.0, is_access=False)
        assert updated.x > 0.3  # x recovers toward 1.0

    def test_no_elapsed_no_recovery(self):
        state = SynapticState(u=0.5, x=0.3)
        updated = update_short_term_dynamics(state, hours_elapsed=0.0, is_access=False)
        assert updated.u == 0.5
        assert updated.x == 0.3

    def test_access_resets_hours_since(self):
        state = SynapticState(hours_since_last_access=10.0)
        updated = update_short_term_dynamics(state, hours_elapsed=0.0, is_access=True)
        assert updated.hours_since_last_access == 0.0

    def test_full_recovery_after_long_time(self):
        """After very long time, u→0 and x→1."""
        state = SynapticState(u=0.9, x=0.1)
        updated = update_short_term_dynamics(
            state, hours_elapsed=100.0, is_access=False
        )
        assert updated.u < 0.01
        assert updated.x > 0.99

    def test_between_spike_recovery_exact_values(self):
        """Between-spike solution, exactly, with `is_access` left defaulted.

        u(t) = u0*exp(-t/tau_F)      = 0.5*exp(-0.3/0.5) = 0.274406 (6 dp)
        x(t) = 1-(1-x0)*exp(-t/tau_D) = 1-0.8*exp(-0.3/2.0) = 0.311434 (6 dp)

        The 6-decimal rounding is part of the contract, so the assertions are
        exact rather than approximate. Omitting `is_access` also pins its
        default: no spike is applied, so access_count is carried through and
        hours_since_last_access reports the elapsed time.
        """
        state = SynapticState(u=0.5, x=0.2, access_count=3)

        updated = update_short_term_dynamics(state, hours_elapsed=0.3)

        assert updated.u == 0.274406
        assert updated.x == 0.311434
        assert updated.access_count == 3
        assert updated.hours_since_last_access == 0.3

    def test_spike_exact_values(self):
        """Spike update, exactly, from a state that is neither u=0 nor x=1.

        u_new = u + U*(1-u) = 0.5 + 0.2*0.5 = 0.6
        x_new = x - u_new*x = 0.5 - 0.6*0.5 = 0.2

        u=0 or x=1 would make several arithmetic variants of these two lines
        agree with them, so the starting state deliberately uses neither.
        """
        state = SynapticState(u=0.5, x=0.5, access_count=2)

        updated = update_short_term_dynamics(state, hours_elapsed=0.0, is_access=True)

        assert updated.u == 0.6
        assert updated.x == 0.2
        assert updated.access_count == 3
        assert updated.hours_since_last_access == 0.0


# -- Noise Injection -----------------------------------------------------------


class TestNoisyWeightUpdate:
    def test_noise_adds_variance(self):
        rng = random.Random(42)
        deltas = [
            compute_noisy_weight_update(0.05, access_count=1, rng=rng)
            for _ in range(100)
        ]
        assert not all(d == 0.05 for d in deltas)
        assert abs(sum(deltas) / len(deltas) - 0.05) < 0.02

    def test_high_access_count_less_noise(self):
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        low_evidence = [
            compute_noisy_weight_update(0.05, access_count=1, rng=rng1)
            for _ in range(200)
        ]
        high_evidence = [
            compute_noisy_weight_update(0.05, access_count=100, rng=rng2)
            for _ in range(200)
        ]
        var_low = sum((d - 0.05) ** 2 for d in low_evidence) / len(low_evidence)
        var_high = sum((d - 0.05) ** 2 for d in high_evidence) / len(high_evidence)
        assert var_high < var_low

    def test_zero_access_count_uses_full_noise(self):
        rng = random.Random(42)
        d = compute_noisy_weight_update(0.0, access_count=0, rng=rng)
        assert d != 0.0

    def test_no_evidence_uses_the_full_noise_scale_and_adds_it(self):
        """access_count <= 0 → evidence_factor 1.0 → sigma == noise_scale.

        The stub returns the sigma it was passed, so the result reveals both
        the sigma the function computed AND that the noise is ADDED to
        delta_w. It also pins that the caller's rng is the one used: the
        module-level `random` would return a sample, never exactly sigma.
        """
        rng = _FixedRandom()

        result = compute_noisy_weight_update(
            0.5, access_count=0, noise_scale=1.0, rng=rng
        )

        assert rng.last_sigma == 1.0
        assert result == 1.5

    def test_sigma_scales_by_inverse_sqrt_of_evidence(self):
        """access_count=4 → evidence_factor 1/sqrt(4) = 0.5 → sigma 0.5."""
        rng = _FixedRandom()

        result = compute_noisy_weight_update(
            0.5, access_count=4, noise_scale=1.0, rng=rng
        )

        assert rng.last_sigma == 0.5
        assert result == 1.0


# -- Phase-Gated Plasticity (Hasselmo 2005) ------------------------------------


class TestPhaseModulation:
    def test_ltp_strongest_at_encoding_peak(self):
        ltp_encoding = phase_modulate_plasticity(0.05, theta_phase=0.25, is_ltp=True)
        ltp_retrieval = phase_modulate_plasticity(0.05, theta_phase=0.75, is_ltp=True)
        assert ltp_encoding > ltp_retrieval

    def test_ltd_strongest_at_retrieval_peak(self):
        ltd_retrieval = phase_modulate_plasticity(-0.02, theta_phase=0.75, is_ltp=False)
        ltd_encoding = phase_modulate_plasticity(-0.02, theta_phase=0.25, is_ltp=False)
        assert ltd_retrieval < ltd_encoding

    def test_encoding_peak_gives_max_ltp(self):
        result = phase_modulate_plasticity(1.0, theta_phase=0.25, is_ltp=True)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_retrieval_peak_gives_min_ltp(self):
        result = phase_modulate_plasticity(1.0, theta_phase=0.75, is_ltp=True)
        assert result == pytest.approx(0.3, abs=0.01)

    def test_never_fully_zero(self):
        result = phase_modulate_plasticity(0.05, theta_phase=0.75, is_ltp=True)
        assert result > 0

    def test_ltp_envelope_exact_off_peak(self):
        """Off-peak theta pins the envelope, and `is_ltp` defaults to LTP.

        raw = cos(2*pi*(0.125 - 0.25)) = cos(-pi/4) = sqrt(2)/2
        encoding_strength = 0.65 + 0.35*raw = 0.897487...

        The existing cases sit on the peaks (theta 0.25 / 0.75) where
        raw is exactly +/-1 and several variants of the envelope coincide.
        """
        result = phase_modulate_plasticity(1.0, theta_phase=0.125)

        assert result == pytest.approx(0.8974873734152917, abs=1e-12)

    def test_ltd_envelope_exact_off_peak(self):
        """retrieval_strength = 0.65 - 0.35*raw = 0.402513... at theta=0.125."""
        result = phase_modulate_plasticity(1.0, theta_phase=0.125, is_ltp=False)

        assert result == pytest.approx(0.4025126265847084, abs=1e-12)


# -- Stochastic Hebbian Update -------------------------------------------------


class TestStochasticHebbianUpdate:
    def test_co_accessed_may_be_blocked(self):
        """Default state has low u_eff (0.2), so many spikes are blocked."""
        edges = [{"source_entity_id": 1, "target_entity_id": 2, "weight": 0.5}]
        rng = random.Random(42)
        blocked_count = 0
        for _ in range(50):
            rng_copy = random.Random(rng.randint(0, 10**9))
            results = apply_stochastic_hebbian_update(
                edges,
                co_accessed_pairs={(1, 2)},
                entity_activities={1: 0.8, 2: 0.8},
                entity_thresholds={1: 0.3, 2: 0.3},
                rng=rng_copy,
            )
            if results[0]["action"] == "blocked":
                blocked_count += 1
        assert blocked_count > 10

    def test_facilitated_mostly_succeeds(self):
        """High u + no recovery time → high release probability → mostly LTP."""
        edges = [
            {
                "source_entity_id": 1,
                "target_entity_id": 2,
                "weight": 0.5,
                "u": 0.9,
                "x": 1.0,
            }
        ]
        rng = random.Random(42)
        ltp_count = 0
        for _ in range(50):
            rng_copy = random.Random(rng.randint(0, 10**9))
            results = apply_stochastic_hebbian_update(
                edges,
                co_accessed_pairs={(1, 2)},
                entity_activities={1: 0.8, 2: 0.8},
                entity_thresholds={1: 0.3, 2: 0.3},
                hours_since_last_update=0.0,  # No recovery decay
                rng=rng_copy,
            )
            if results[0]["action"] == "ltp":
                ltp_count += 1
        assert ltp_count > 30

    def test_returns_tsodyks_markram_state(self):
        edges = [{"source_entity_id": 1, "target_entity_id": 2, "weight": 0.5}]
        rng = random.Random(42)
        results = apply_stochastic_hebbian_update(
            edges,
            co_accessed_pairs={(1, 2)},
            entity_activities={1: 0.8, 2: 0.8},
            entity_thresholds={1: 0.3, 2: 0.3},
            rng=rng,
        )
        r = results[0]
        assert "u" in r
        assert "x" in r
        assert "access_count" in r
        assert r["access_count"] == 1

    def test_phase_gating_modulates_ltp(self):
        """LTP during encoding phase should be stronger than retrieval."""
        edges = [
            {
                "source_entity_id": 1,
                "target_entity_id": 2,
                "weight": 0.5,
                "u": 0.9,
                "x": 1.0,
            }
        ]

        enc_deltas = []
        ret_deltas = []
        for i in range(100):
            r_enc = apply_stochastic_hebbian_update(
                edges,
                co_accessed_pairs={(1, 2)},
                entity_activities={1: 0.8, 2: 0.8},
                entity_thresholds={1: 0.3, 2: 0.3},
                theta_phase=0.25,
                rng=random.Random(i),
            )
            r_ret = apply_stochastic_hebbian_update(
                edges,
                co_accessed_pairs={(1, 2)},
                entity_activities={1: 0.8, 2: 0.8},
                entity_thresholds={1: 0.3, 2: 0.3},
                theta_phase=0.75,
                rng=random.Random(i),
            )
            enc_deltas.append(r_enc[0]["delta"])
            ret_deltas.append(r_ret[0]["delta"])

        avg_enc = sum(enc_deltas) / len(enc_deltas)
        avg_ret = sum(ret_deltas) / len(ret_deltas)
        assert avg_enc > avg_ret

    def test_ltd_still_works(self):
        edges = [{"source_entity_id": 1, "target_entity_id": 2, "weight": 0.5}]
        results = apply_stochastic_hebbian_update(
            edges,
            co_accessed_pairs=set(),
            entity_activities={1: 0.5, 2: 0.5},
            entity_thresholds={1: 0.5, 2: 0.5},
            hours_since_last_update=48,
        )
        assert results[0]["action"] == "ltd"
        assert results[0]["weight"] < 0.5

    def test_empty_edges(self):
        results = apply_stochastic_hebbian_update(
            [],
            co_accessed_pairs=set(),
            entity_activities={},
            entity_thresholds={},
        )
        assert results == []
