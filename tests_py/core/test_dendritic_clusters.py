"""Tests for dendritic_clusters — branch-specific nonlinear integration."""

import pytest
from mcp_server.core.dendritic_clusters import (
    compute_branch_affinity,
    find_best_branch,
    add_memory_to_branch,
    create_branch,
)
from mcp_server.core.dendritic_computation import (
    DendriticBranch,
    branch_subunit,
    soma_output,
    compute_dendritic_integration,
    compute_cluster_priming,
    update_branch_plasticity,
    compute_branch_statistics,
    branch_to_dict,
    branch_from_dict,
)


class TestBranchAssignment:
    def test_affinity_high_for_matching(self):
        branch = DendriticBranch(
            entity_signature={"React", "useState"}, tag_signature={"frontend"}
        )
        score = compute_branch_affinity({"React", "useEffect"}, {"frontend"}, branch)
        assert score > 0.3

    def test_affinity_low_for_unrelated(self):
        branch = DendriticBranch(
            entity_signature={"Django", "ORM"}, tag_signature={"backend"}
        )
        score = compute_branch_affinity({"React", "useState"}, {"frontend"}, branch)
        assert score < 0.1

    def test_find_best_branch(self):
        b1 = DendriticBranch(
            branch_id="b1", entity_signature={"React"}, tag_signature={"frontend"}
        )
        b2 = DendriticBranch(
            branch_id="b2", entity_signature={"Django"}, tag_signature={"backend"}
        )
        best, score = find_best_branch({"React", "hooks"}, {"frontend"}, [b1, b2])
        assert best is not None
        assert best.branch_id == "b1"

    def test_no_match_returns_none(self):
        b1 = DendriticBranch(entity_signature={"Go", "goroutine"})
        best, _ = find_best_branch({"Haskell", "monad"}, set(), [b1])
        assert best is None

    def test_full_branch_skipped(self):
        b1 = DendriticBranch(entity_signature={"React"}, memory_ids=list(range(15)))
        best, _ = find_best_branch({"React"}, set(), [b1], max_size=15)
        assert best is None


class TestBranchCreation:
    def test_create_new_branch(self):
        b = create_branch("b1", "test", 1, {"foo", "bar"}, {"tag"}, 0.9)
        assert b.branch_id == "b1"
        assert len(b.memory_ids) == 1
        assert b.avg_heat == 0.9

    def test_add_memory_updates_signatures(self):
        b = create_branch("b1", "test", 1, {"foo"}, {"tag"}, 0.8)
        b2 = add_memory_to_branch(b, 2, {"bar"}, {"tag2"}, 0.6)
        assert 2 in b2.memory_ids
        assert "bar" in b2.entity_signature
        assert "tag2" in b2.tag_signature
        assert b2.avg_heat == pytest.approx(0.7, abs=0.01)


class TestBranchSubunit:
    """Verify branch_subunit matches Poirazi (2003) Eq:
    s(n) = 1/(1+exp((3.6-n)/2)) + 0.30*n + 0.0114*n^2
    """

    def test_zero_synapses(self):
        assert branch_subunit(0) == 0.0

    def test_at_half_activation(self):
        """At n=3.6, sigmoid = 0.5, linear = 1.08, quadratic = 0.1478."""
        s = branch_subunit(3.6)
        expected = 0.5 + 0.30 * 3.6 + 0.0114 * 3.6 * 3.6
        assert s == pytest.approx(expected, abs=1e-6)

    def test_one_synapse(self):
        """s(1) = 1/(1+exp(2.6/2)) + 0.30 + 0.0114."""
        import math
        sigmoid = 1.0 / (1.0 + math.exp(2.6 / 2.0))
        expected = sigmoid + 0.30 + 0.0114
        assert branch_subunit(1) == pytest.approx(expected, abs=1e-6)

    def test_ten_synapses(self):
        """s(10) = 1/(1+exp(-6.4/2)) + 3.0 + 1.14."""
        import math
        sigmoid = 1.0 / (1.0 + math.exp(-6.4 / 2.0))
        expected = sigmoid + 3.0 + 1.14
        assert branch_subunit(10) == pytest.approx(expected, abs=1e-6)

    def test_monotonically_increasing(self):
        values = [branch_subunit(n) for n in range(1, 16)]
        for i in range(1, len(values)):
            assert values[i] > values[i - 1]


class TestSomaOutput:
    """Verify soma_output matches Poirazi (2003) Eq:
    g(x) = 0.96 * x / (1 + 1509 * exp(-0.26 * x))
    """

    def test_zero_input(self):
        assert soma_output(0.0) == 0.0

    def test_small_input_suppressed(self):
        """For small x, the 1509*exp(-0.26*x) term dominates → output near 0."""
        assert soma_output(1.0) < 0.01

    def test_large_input_approaches_linear(self):
        """For large x, exp term vanishes → g(x) ≈ 0.96*x."""
        x = 100.0
        assert soma_output(x) == pytest.approx(0.96 * x, rel=0.01)

    def test_threshold_region(self):
        """Around x=28, the function transitions from suppressed to linear."""
        low = soma_output(10.0)
        mid = soma_output(28.0)
        high = soma_output(50.0)
        assert low < mid < high
        # Mid should be a substantial fraction of 0.96*28
        assert mid > 0.1 * 0.96 * 28

    def test_monotonically_increasing(self):
        values = [soma_output(x) for x in range(1, 60)]
        for i in range(1, len(values)):
            assert values[i] > values[i - 1]


class TestNonlinearIntegration:
    """Tests for the Poirazi (2003) two-layer neuron model.

    Layer 1: s(n) = 1/(1+exp((3.6-n)/2)) + 0.30*n + 0.0114*n^2
    Layer 2: g(x) = 0.96 * x / (1 + 1509 * exp(-0.26 * x))
    """

    def test_few_active_synapses_below_half_activation(self):
        """With n=1, sigmoid < 0.5 so no spike. Output is small because
        soma nonlinearity suppresses low inputs (1509 in denominator)."""
        score, spiked = compute_dendritic_integration(1, 5, [0.5])
        assert spiked is False
        assert score >= 0.0
        assert score < 0.01  # Soma suppresses weak branch input

    def test_many_active_synapses_above_half_activation(self):
        """With n=5 (> 3.6 half-activation), sigmoid > 0.5 → spike.
        Branch subunit: s(5) = sigmoid + 1.5 + 0.285 ≈ 2.74.
        Weighted by mean score, then through soma."""
        scores = [0.5, 0.6, 0.7, 0.8, 0.9]
        score, spiked = compute_dendritic_integration(5, 10, scores)
        assert spiked is True
        assert score > 0.0

    def test_at_half_activation_spikes(self):
        """At n=4 (> 3.6), sigmoid just crosses 0.5 → spike."""
        scores = [0.6, 0.7, 0.8, 0.9]
        score, spiked = compute_dendritic_integration(4, 8, scores)
        assert spiked is True

    def test_three_synapses_no_spike(self):
        """At n=3 (< 3.6 half-activation), sigmoid < 0.5 → no spike."""
        scores = [0.5, 0.6, 0.7]
        score, spiked = compute_dendritic_integration(3, 5, scores)
        assert spiked is False

    def test_single_item_no_spike(self):
        score, spiked = compute_dendritic_integration(1, 10, [0.8])
        assert spiked is False

    def test_empty_returns_zero(self):
        score, spiked = compute_dendritic_integration(0, 0, [])
        assert score == 0.0
        assert spiked is False

    def test_output_increases_with_active_count(self):
        """More co-active synapses → higher subunit → higher soma output."""
        _, _ = compute_dendritic_integration(1, 10, [0.8])
        s1, _ = compute_dendritic_integration(1, 10, [0.8])
        s3, _ = compute_dendritic_integration(3, 10, [0.8, 0.8, 0.8])
        s6, _ = compute_dendritic_integration(6, 10, [0.8] * 6)
        assert s1 < s3 < s6

    def test_higher_scores_produce_higher_output(self):
        """Higher retrieval quality scores weight the branch output up."""
        low, _ = compute_dendritic_integration(3, 5, [0.2, 0.2, 0.2])
        high, _ = compute_dendritic_integration(3, 5, [0.9, 0.9, 0.9])
        assert low < high


class TestClusterPriming:
    def test_priming_from_branch_member(self):
        b = DendriticBranch(memory_ids=[1, 2, 3, 4])
        primes = compute_cluster_priming(2, b)
        assert 1 in primes
        assert 3 in primes
        assert 4 in primes
        assert 2 not in primes  # Self not primed

    def test_priming_decays_with_distance(self):
        b = DendriticBranch(memory_ids=[1, 2, 3, 4, 5])
        primes = compute_cluster_priming(1, b)
        # Closer members should get more priming
        assert primes[2] > primes[5]

    def test_priming_nonmember_returns_empty(self):
        b = DendriticBranch(memory_ids=[1, 2, 3])
        primes = compute_cluster_priming(99, b)
        assert primes == {}


class TestBranchPlasticity:
    def test_ltp_increases_plasticity(self):
        b = DendriticBranch(plasticity=0.5)
        b2 = update_branch_plasticity(b, ltp_occurred=True, ltd_occurred=False)
        assert b2.plasticity > 0.5

    def test_ltd_decreases_plasticity(self):
        b = DendriticBranch(plasticity=0.5)
        b2 = update_branch_plasticity(b, ltp_occurred=False, ltd_occurred=True)
        assert b2.plasticity < 0.5

    def test_plasticity_bounded(self):
        b = DendriticBranch(plasticity=0.99)
        b2 = update_branch_plasticity(b, ltp_occurred=True, ltd_occurred=False)
        assert b2.plasticity <= 1.0


class TestStatistics:
    def test_empty_stats(self):
        stats = compute_branch_statistics([])
        assert stats["total_branches"] == 0

    def test_basic_stats(self):
        branches = [
            DendriticBranch(memory_ids=[1, 2, 3], plasticity=0.8),
            DendriticBranch(memory_ids=[4], plasticity=0.6),
        ]
        stats = compute_branch_statistics(branches)
        assert stats["total_branches"] == 2
        assert stats["avg_branch_size"] == 2.0
        assert stats["max_branch_size"] == 3
        assert stats["orphan_branches"] == 1


class TestSerialization:
    def test_roundtrip(self):
        b = DendriticBranch(
            branch_id="b1",
            domain="test",
            memory_ids=[1, 2],
            entity_signature={"foo", "bar"},
            tag_signature={"tag"},
            avg_heat=0.7,
            plasticity=0.9,
            spike_count=3,
        )
        d = branch_to_dict(b)
        restored = branch_from_dict(d)
        assert restored.branch_id == "b1"
        assert set(restored.entity_signature) == {"foo", "bar"}
        assert restored.spike_count == 3
