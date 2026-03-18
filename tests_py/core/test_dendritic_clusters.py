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


class TestNonlinearIntegration:
    def test_sublinear_below_threshold(self):
        score, spiked = compute_dendritic_integration(1, 5, [0.5])
        assert spiked is False
        assert score == pytest.approx(0.5, abs=0.1)

    def test_supralinear_above_threshold(self):
        scores = [0.5, 0.6, 0.7]
        score, spiked = compute_dendritic_integration(3, 5, scores, spike_threshold=0.4)
        assert spiked is True
        assert score > sum(scores)  # Supralinear

    def test_single_item_no_spike(self):
        score, spiked = compute_dendritic_integration(1, 10, [0.8])
        assert spiked is False

    def test_empty_returns_zero(self):
        score, spiked = compute_dendritic_integration(0, 0, [])
        assert score == 0.0
        assert spiked is False


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
