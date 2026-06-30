"""Tests for cognitive_map — SR co-access scoring, BFS navigation, and the
SR spectral embedding (project_to_2d).

The module previously had no test coverage. These tests pin the faithful
Successor-Representation behaviour:
  - compute_sr_scores: directional affinity from seeds, seeds excluded.
  - project_to_2d: SR/Laplacian spectral embedding (Stachenfeld 2017) — the
    subdominant eigenvector (Fiedler vector) separates co-access clusters.
"""

from __future__ import annotations

import math

from mcp_server.core import cognitive_map as cm


# ── compute_sr_scores ─────────────────────────────────────────────────────


def test_sr_scores_excludes_seeds_and_sums_affinity() -> None:
    graph = {1: {2: 0.8, 3: 0.4}, 4: {2: 0.2}}
    scores = dict(cm.compute_sr_scores([1, 4], graph, top_k=10))
    # Seeds 1 and 4 are excluded from results.
    assert 1 not in scores and 4 not in scores
    # Candidate 2 reachable from both seeds: (0.8 + 0.2) / 2 seeds = 0.5.
    assert scores[2] == 0.5
    # Candidate 3 reachable from seed 1 only: 0.4 / 2 = 0.2.
    assert scores[3] == 0.2


def test_sr_scores_sorted_desc_and_top_k() -> None:
    graph = {1: {2: 0.1, 3: 0.9, 4: 0.5}}
    scores = cm.compute_sr_scores([1], graph, top_k=2)
    assert [mid for mid, _ in scores] == [3, 4]  # top-2 by score, descending


def test_sr_scores_empty_inputs() -> None:
    assert cm.compute_sr_scores([], {1: {2: 0.5}}) == []
    assert cm.compute_sr_scores([1], {}) == []


# ── build_temporal_co_access ──────────────────────────────────────────────


def test_temporal_co_access_links_within_window_only() -> None:
    mems = [
        {"id": 1, "last_accessed": "2026-01-01T10:00:00+00:00"},
        {"id": 2, "last_accessed": "2026-01-01T10:30:00+00:00"},  # +30min
        {"id": 3, "last_accessed": "2026-01-01T15:00:00+00:00"},  # +5h
    ]
    graph = cm.build_temporal_co_access(mems, window_hours=2.0)
    # 1 and 2 are within 2h → linked symmetrically.
    assert 2 in graph[1] and 1 in graph[2]
    # 3 is >2h from both → no link.
    assert 3 not in graph.get(1, {})


# ── navigate_from ─────────────────────────────────────────────────────────


def test_navigate_respects_depth_and_min_weight() -> None:
    graph = {1: {2: 0.9}, 2: {3: 0.9}, 3: {4: 0.01}}
    visited = cm.navigate_from(1, graph, max_depth=2, min_weight=0.05)
    assert 2 in visited and 3 in visited  # within depth 2, above min_weight
    assert 4 not in visited  # edge 3->4 weight 0.01 < min_weight


# ── project_to_2d — SR spectral embedding ─────────────────────────────────


def test_project_empty_and_singleton() -> None:
    assert cm.project_to_2d({}, []) == {}
    assert cm.project_to_2d({}, [7]) == {7: (0.0, 0.0)}


def test_project_coords_bounded() -> None:
    graph = {1: {2: 1.0}, 2: {1: 1.0, 3: 1.0}, 3: {2: 1.0}}
    coords = cm.project_to_2d(graph, [1, 2, 3])
    for x, y in coords.values():
        assert -1.0 - 1e-9 <= x <= 1.0 + 1e-9
        assert -1.0 - 1e-9 <= y <= 1.0 + 1e-9


def test_project_fiedler_separates_clusters() -> None:
    """Faithfulness: the subdominant SR eigenvector (Fiedler vector) must
    separate two weakly-bridged co-access clusters — the defining property of
    the spectral embedding (Stachenfeld 2017 / spectral clustering)."""
    # Two triangles {1,2,3} and {4,5,6}, joined by a single weak bridge 3-4.
    graph: dict[int, dict[int, float]] = {
        1: {2: 1.0, 3: 1.0},
        2: {1: 1.0, 3: 1.0},
        3: {1: 1.0, 2: 1.0, 4: 0.1},
        4: {5: 1.0, 6: 1.0, 3: 0.1},
        5: {4: 1.0, 6: 1.0},
        6: {4: 1.0, 5: 1.0},
    }
    coords = cm.project_to_2d(graph, [1, 2, 3, 4, 5, 6])
    cluster_a = [coords[i][0] for i in (1, 2, 3)]
    cluster_b = [coords[i][0] for i in (4, 5, 6)]
    # The x-axis (Fiedler vector) puts the two clusters on opposite sides:
    # every node in A has the opposite sign to every node in B.
    assert max(cluster_a) < min(cluster_b) or max(cluster_b) < min(cluster_a)

    # Within-cluster spread is smaller than the across-cluster gap.
    within = max(
        max(cluster_a) - min(cluster_a), max(cluster_b) - min(cluster_b)
    )
    across = abs(sum(cluster_a) / 3 - sum(cluster_b) / 3)
    assert across > within


def test_project_disconnected_nodes_embed_at_origin() -> None:
    # Node 9 has no edges → degree 0 → embeds at the origin.
    graph = {1: {2: 1.0}, 2: {1: 1.0}}
    coords = cm.project_to_2d(graph, [1, 2, 9])
    assert coords[9] == (0.0, 0.0)
    assert not math.isnan(coords[1][0])
