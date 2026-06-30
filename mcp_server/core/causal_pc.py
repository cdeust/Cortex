"""Faithful PC constraint-based causal discovery over binary variables.

Implements the skeleton + v-structure phases of the PC algorithm
(Spirtes & Glymour 1991; Spirtes, Glymour & Scheines 2000, *Causation,
Prediction, and Search*, 2nd ed., §5.4.2) for discrete (here binary)
variables, using the G² (likelihood-ratio) conditional-independence test.

Each observation is one memory; each variable is the binary presence of an
entity. This is exactly the setting of a chi-square / G² PC test
(cf. causal-learn's ``chisq``/``gsq`` independence tests).

The chi-square survival function is computed in pure Python via the
regularised upper incomplete gamma function Q(a, x) (Numerical Recipes in C,
2nd ed., §6.2, ``gammq``) — no SciPy dependency.

Pure business logic — no I/O.
"""

from __future__ import annotations

import math
from itertools import combinations

# ── Chi-square survival via regularised incomplete gamma ──────────────────

_ITMAX = 300
_EPS = 1e-12
_FPMIN = 1e-300


def _gamma_p_series(a: float, x: float) -> float:
    """Lower regularised incomplete gamma P(a, x) via series (NR §6.2)."""
    gln = math.lgamma(a)
    ap = a
    total = 1.0 / a
    delta = total
    for _ in range(_ITMAX):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * _EPS:
            break
    return total * math.exp(-x + a * math.log(x) - gln)


def _gamma_q_cf(a: float, x: float) -> float:
    """Upper regularised incomplete gamma Q(a, x) via continued fraction."""
    gln = math.lgamma(a)
    b = x + 1.0 - a
    c = 1.0 / _FPMIN
    d = 1.0 / b
    h = d
    for i in range(1, _ITMAX):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = b + an / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def chi2_sf(stat: float, df: int) -> float:
    """Survival function P(χ²_df > stat) = Q(df/2, stat/2).

    Validated against textbook critical values, e.g. chi2_sf(3.841, 1)≈0.05,
    chi2_sf(5.991, 2)≈0.05, chi2_sf(9.488, 4)≈0.05.
    """
    if df <= 0 or stat <= 0.0:
        return 1.0
    a = df / 2.0
    x = stat / 2.0
    if x < a + 1.0:
        return 1.0 - _gamma_p_series(a, x)
    return _gamma_q_cf(a, x)


# ── G² conditional-independence test ──────────────────────────────────────


def g2_independent(
    presence: list[frozenset[str]],
    x: str,
    y: str,
    cond: tuple[str, ...],
    alpha: float,
) -> bool:
    """Test X ⊥ Y | cond on binary presence data via the G² statistic.

    G² = 2 Σ N_xys · ln( N_xys · N_··s / (N_x·s · N_·ys) ), summed over the
    binary states of X, Y and every configuration s of the conditioning set.
    df = 2^|cond|. Returns True (independent) iff the p-value > alpha.
    """
    # Bucket sample counts by (x_state, y_state, cond_state).
    cond_states: dict[tuple[bool, ...], list[int]] = {}
    for sample in presence:
        s_key = tuple(c in sample for c in cond)
        cell = cond_states.setdefault(s_key, [0, 0, 0, 0])
        # cell layout: [x0y0, x0y1, x1y0, x1y1]
        cell[(2 if x in sample else 0) + (1 if y in sample else 0)] += 1

    g2 = 0.0
    for cell in cond_states.values():
        n_s = cell[0] + cell[1] + cell[2] + cell[3]
        if n_s == 0:
            continue
        nx = (cell[2] + cell[3], cell[0] + cell[1])  # (X=1, X=0) marginals
        ny = (cell[1] + cell[3], cell[0] + cell[2])  # (Y=1, Y=0) marginals
        # observed counts indexed [x_state][y_state]
        obs = ((cell[0], cell[1]), (cell[2], cell[3]))
        for xi, x_state in enumerate((0, 1)):
            for yi, y_state in enumerate((0, 1)):
                n_xy = obs[xi][yi]
                if n_xy == 0:
                    continue
                expected = nx[1 - x_state] * ny[1 - y_state] / n_s
                if expected > 0.0:
                    g2 += n_xy * math.log(n_xy / expected)
    g2 *= 2.0

    df = 2 ** len(cond)
    return chi2_sf(g2, df) > alpha


# ── PC skeleton + v-structure orientation ─────────────────────────────────


def pc_skeleton(
    variables: list[str],
    presence: list[frozenset[str]],
    alpha: float,
    max_cond_size: int,
) -> tuple[set[frozenset[str]], dict[frozenset[str], frozenset[str]]]:
    """Phase 1 of PC: learn the undirected skeleton.

    Starts from the complete graph and removes edge X–Y whenever some subset
    S of X's (or Y's) current neighbours renders them conditionally
    independent, recording S as the separating set. Conditioning-set size
    grows 0, 1, … up to ``max_cond_size`` (a standard tractability cap).

    Returns (edges, sepsets) where edges is a set of 2-element frozensets.
    """
    edges: set[frozenset[str]] = {
        frozenset((a, b)) for a, b in combinations(variables, 2)
    }
    sepsets: dict[frozenset[str], frozenset[str]] = {}

    def neighbors(node: str) -> list[str]:
        return [v for v in variables if v != node and frozenset((node, v)) in edges]

    k = 0
    while True:
        for a, b in combinations(variables, 2):
            edge = frozenset((a, b))
            if edge not in edges:
                continue
            adj = [n for n in neighbors(a) if n != b]
            if len(adj) < k:
                adj_b = [n for n in neighbors(b) if n != a]
                if len(adj_b) < k:
                    continue
                adj = adj_b
            for cond in combinations(adj, k):
                if g2_independent(presence, a, b, cond, alpha):
                    edges.discard(edge)
                    sepsets[edge] = frozenset(cond)
                    break
        max_degree = max((len(neighbors(v)) for v in variables), default=0)
        k += 1
        if k > max_cond_size or k > max_degree:
            break
    return edges, sepsets


def orient_v_structures(
    variables: list[str],
    edges: set[frozenset[str]],
    sepsets: dict[frozenset[str], frozenset[str]],
) -> set[tuple[str, str]]:
    """Phase 2 of PC: orient unshielded colliders X→Z←Y.

    For every unshielded triple X–Z–Y (X, Y non-adjacent), orient both edges
    into Z iff Z is NOT in the separating set of X and Y.
    """
    directed: set[tuple[str, str]] = set()
    for z in variables:
        nbrs = [v for v in variables if frozenset((z, v)) in edges]
        for x, y in combinations(nbrs, 2):
            if frozenset((x, y)) in edges:
                continue  # shielded — x and y adjacent
            sep = sepsets.get(frozenset((x, y)))
            if sep is not None and z not in sep:
                directed.add((x, z))
                directed.add((y, z))
    return directed
