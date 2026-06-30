"""Tests for causal_graph + causal_pc — faithful PC causal discovery.

Structure is learned by the PC algorithm (G² conditional-independence tests
over binary entity-presence data, then v-structure orientation). Synthetic
data uses product/grid designs so conditional independence holds *exactly*
within each stratum, letting the tests assert PC's defining behaviour.
"""

from __future__ import annotations

from itertools import product

from mcp_server.core.causal_graph import (
    build_presence,
    compute_temporal_precedence,
    discover_causal_edges,
    find_causal_chain,
    find_common_causes,
)
from mcp_server.core.causal_pc import (
    chi2_sf,
    g2_independent,
    orient_v_structures,
    pc_skeleton,
)


# ── chi2_sf: validate against textbook critical values ────────────────────


class TestChi2SurvivalFunction:
    def test_critical_values_at_5pct(self):
        # Standard χ² 0.05 critical points: P(χ²_df > crit) ≈ 0.05.
        for crit, df in [(3.841, 1), (5.991, 2), (7.815, 3), (9.488, 4)]:
            assert abs(chi2_sf(crit, df) - 0.05) < 1e-3

    def test_zero_statistic_is_one(self):
        assert chi2_sf(0.0, 1) == 1.0
        assert chi2_sf(-1.0, 2) == 1.0

    def test_large_statistic_near_zero(self):
        assert chi2_sf(50.0, 1) < 1e-6


# ── G² conditional-independence test ──────────────────────────────────────


def _fork_presence() -> list[frozenset[str]]:
    """A←C→B with EXACT independence of A,B given C (product design).

    C present in a 6×6 grid (36 samples): A depends only on the row, B only
    on the column → A⊥B|C=1 exactly. C absent in 36 samples with neither —
    that absent stratum makes A and B strongly *marginally* dependent (both
    are driven by C) while leaving them exactly independent given C.
    """
    samples: list[frozenset[str]] = []
    for row, col in product(range(6), range(6)):
        s = {"C"}
        if row < 3:
            s.add("A")
        if col < 3:
            s.add("B")
        samples.append(frozenset(s))
    samples.extend(frozenset() for _ in range(36))
    return samples


class TestG2Independence:
    def test_conditional_independence_holds_given_common_cause(self):
        pres = _fork_presence()
        # Marginally dependent (both driven by C), independent given C.
        assert g2_independent(pres, "A", "B", (), 0.05) is False
        assert g2_independent(pres, "A", "B", ("C",), 0.05) is True

    def test_collider_marginally_independent_dependent_given_z(self):
        # A→Z←B: A,B independent marginally, dependent given the collider Z.
        samples: list[frozenset[str]] = []
        for a, b in product((0, 1), repeat=2):
            for _ in range(20):
                s: set[str] = set()
                if a:
                    s.add("A")
                if b:
                    s.add("B")
                if a or b:  # Z present iff A or B present (deterministic OR)
                    s.add("Z")
                samples.append(frozenset(s))
        assert g2_independent(samples, "A", "B", (), 0.05) is True
        assert g2_independent(samples, "A", "B", ("Z",), 0.05) is False


# ── PC skeleton + v-structure orientation ─────────────────────────────────


class TestPCSkeleton:
    def test_fork_removes_a_b_edge_with_c_in_sepset(self):
        pres = _fork_presence()
        edges, sepsets = pc_skeleton(["A", "B", "C"], pres, alpha=0.05, max_cond_size=3)
        assert frozenset(("A", "B")) not in edges  # removed: A⊥B|C
        assert frozenset(("A", "C")) in edges
        assert frozenset(("B", "C")) in edges
        # Separating set of A,B contains the common cause C → NOT a collider.
        assert "C" in sepsets[frozenset(("A", "B"))]
        assert orient_v_structures(["A", "B", "C"], edges, sepsets) == set()

    def test_collider_orients_into_z(self):
        samples: list[frozenset[str]] = []
        for a, b in product((0, 1), repeat=2):
            for _ in range(20):
                s: set[str] = set()
                if a:
                    s.add("A")
                if b:
                    s.add("B")
                if a or b:
                    s.add("Z")
                samples.append(frozenset(s))
        edges, sepsets = pc_skeleton(["A", "B", "Z"], samples, 0.05, 3)
        # A⊥B marginally → A–B removed with empty sepset → Z is a collider.
        assert frozenset(("A", "B")) not in edges
        assert sepsets[frozenset(("A", "B"))] == frozenset()
        directed = orient_v_structures(["A", "B", "Z"], edges, sepsets)
        assert ("A", "Z") in directed and ("B", "Z") in directed


# ── discover_causal_edges (orchestrator) ──────────────────────────────────


class TestDiscoverCausalEdges:
    def test_empty_inputs(self):
        assert discover_causal_edges([], []) == []
        assert discover_causal_edges(["A"], []) == []

    def test_fork_drops_spurious_a_b_edge(self):
        pres = _fork_presence()
        edges = discover_causal_edges(["A", "B", "C"], pres, min_observations=3)
        pairs = {frozenset((e["source"], e["target"])) for e in edges}
        assert frozenset(("A", "B")) not in pairs  # PC removed the spurious edge
        assert frozenset(("A", "C")) in pairs
        assert frozenset(("B", "C")) in pairs

    def test_collider_orientation_surfaces_in_edges(self):
        samples: list[frozenset[str]] = []
        for a, b in product((0, 1), repeat=2):
            for _ in range(20):
                s: set[str] = set()
                if a:
                    s.add("A")
                if b:
                    s.add("B")
                if a or b:
                    s.add("Z")
                samples.append(frozenset(s))
        edges = discover_causal_edges(["A", "B", "Z"], samples, min_observations=3)
        directed = {(e["source"], e["target"]) for e in edges if e["is_directed"]}
        assert ("A", "Z") in directed and ("B", "Z") in directed

    def test_temporal_precedence_orients_undirected_edge(self):
        # A and B co-vary (present together or absent together) → a genuine
        # dependent pair with variance → one undirected edge; temporal
        # background knowledge (A before B) orients it A→B.
        pres = [frozenset(("A", "B")) for _ in range(10)]
        pres += [frozenset() for _ in range(10)]
        edges = discover_causal_edges(
            ["A", "B"],
            pres,
            entity_first_seen={"A": "2026-01-01", "B": "2026-01-02"},
            min_observations=3,
        )
        assert len(edges) == 1
        assert edges[0]["source"] == "A" and edges[0]["target"] == "B"
        assert edges[0]["is_directed"] is True

    def test_min_observations_floor(self):
        pres = [frozenset(("A", "B")) for _ in range(2)]  # only 2 co-occurrences
        edges = discover_causal_edges(["A", "B"], pres, min_observations=3)
        assert edges == []

    def test_sorted_by_strength(self):
        edges = discover_causal_edges(
            ["A", "B", "C"], _fork_presence(), min_observations=3
        )
        strengths = [e["strength"] for e in edges]
        assert strengths == sorted(strengths, reverse=True)


# ── build_presence ────────────────────────────────────────────────────────


class TestBuildPresence:
    def test_presence_per_memory(self):
        mems = [{"content": "A and B"}, {"content": "only A"}, {"tags": []}]
        pres = build_presence(mems, ["A", "B"])
        assert pres == [frozenset(("A", "B")), frozenset(("A",)), frozenset()]

    def test_case_insensitive(self):
        pres = build_presence([{"content": "apple pie"}], ["Apple"])
        assert pres == [frozenset(("Apple",))]


# ── compute_temporal_precedence ──────────────────────────────────────────


class TestComputeTemporalPrecedence:
    def test_a_before_b(self):
        fs = {"A": "2026-01-01", "B": "2026-01-02"}
        assert compute_temporal_precedence(fs, "A", "B") == "a_before_b"

    def test_b_before_a(self):
        fs = {"A": "2026-01-02", "B": "2026-01-01"}
        assert compute_temporal_precedence(fs, "A", "B") == "b_before_a"

    def test_same_or_missing_returns_none(self):
        assert compute_temporal_precedence({"A": "x", "B": "x"}, "A", "B") is None
        assert compute_temporal_precedence({"A": "x"}, "A", "B") is None


# ── find_causal_chain / find_common_causes (unchanged traversal) ──────────


class TestFindCausalChain:
    def test_chain_of_three(self):
        edges = [
            {"source": "A", "target": "B", "is_directed": True},
            {"source": "B", "target": "C", "is_directed": True},
        ]
        paths = find_causal_chain(edges, "A")
        assert any(p[0] == "A" and p[-1] == "C" and len(p) == 3 for p in paths)

    def test_undirected_ignored_and_cycle_safe(self):
        assert (
            find_causal_chain(
                [{"source": "A", "target": "B", "is_directed": False}], "A"
            )
            == []
        )
        cyclic = [
            {"source": "A", "target": "B", "is_directed": True},
            {"source": "B", "target": "A", "is_directed": True},
        ]
        for p in find_causal_chain(cyclic, "A"):
            assert len(p) == len(set(p))


class TestFindCommonCauses:
    def test_common_cause_detected_and_sorted(self):
        edges = [
            {"source": "Z", "target": "A", "is_directed": True},
            {"source": "Z", "target": "B", "is_directed": True},
            {"source": "M", "target": "A", "is_directed": True},
            {"source": "M", "target": "B", "is_directed": True},
        ]
        assert find_common_causes(edges, "A", "B") == ["M", "Z"]

    def test_undirected_ignored(self):
        edges = [
            {"source": "C", "target": "A", "is_directed": False},
            {"source": "C", "target": "B", "is_directed": False},
        ]
        assert find_common_causes(edges, "A", "B") == []
